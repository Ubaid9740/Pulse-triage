"""The scenario replay (Team Brief 5.2; System Design 14.1): streams a pack's story into the live
server at a chosen speed, through the same paths as real data.

scenario/packs/<pack>/messages.json:
  {"start": "14:00", "speed": 60, "events": [{"t": 12.5, "kind": ..., ...}, ...]}
  t is scenario minutes after the start. Kinds:
    report    {"device", "payload"}                 an app report: signed by that phone, sealed
    text      {"sender", "text", "lat", "lng"}      a plain text message (SMS or mesh text)
    reply     {"device", "registry_id", "status"}   "I'm safe" etc. to the newest active alert;
                                                    held until an alert is active
    window    {"zone", "closes_in_min", "text"}     a zone's window, closing in real minutes
    cue       {"text"}                              a line for the presenter ("issue the warning")
    chaos     {"what": "fake" | "wrong_location" | "duplicate"}
    ai_down   {}                                    the AI reader goes offline (chaos ai_down)
    team_stop {"team"}                              that team stops moving and pinging
    hard_hit  {"zones", "text"}                     the hazard reaches more zones (marked hard-hit)
    supply    {"item", "qty", "move", "place"}      stock used or restocked (move "used" or "restock")
    place     {"id", "occupancy"}                   a shelter's head count changes
  Any other keys (such as "truth", used by simulate.py) are ignored here.

Messages arrive at the replay speed; everything they describe (hours left, windows) runs in real
time. Teams with a phone (device_id in teams.json) move too: once assigned they say "on my way",
travel toward the case at their speed x the replay speed, arrive by ping, report done with an
outcome after 10 scenario minutes, and ping their way back to base. Idle teams ping every minute.
After the last event the story is done ("story_done") but teams keep moving until the replay is
stopped (or after MAX_RUN_S, so a forgotten replay does not run all night).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from nacl.signing import SigningKey

from . import timeutil
from .cases import NotFound
from .crypto import CommandPostKeys
from .db import Database
from .devtools import phone_wire
from .packets import distance_m, geohash

log = logging.getLogger("pulsetriage.replay")

TICK_S = 1.0
IDLE_PING_S = 60
ON_SCENE_MIN = 10           # scenario minutes on scene before "done"
MAX_RUN_S = 3 * 3600
MAX_SPEED = 600


def demo_key(device: str) -> SigningKey:
    """A demo phone's key, the same every run, so the server knows it after the first time.
    Only for scenario phones: never use this for a real one."""
    return SigningKey(hashlib.sha256(f"pulsetriage-demo:{device}".encode()).digest())


def moved_toward(lat: float, lng: float, to_lat: float, to_lng: float, metres: float) -> tuple[float, float]:
    left = distance_m(lat, lng, to_lat, to_lng)
    if left <= metres or left == 0:
        return to_lat, to_lng
    f = metres / left
    return lat + (to_lat - lat) * f, lng + (to_lng - lng) * f


class Replay:
    def __init__(self, scenario_dir: Path, db: Database, keys: CommandPostKeys, ingestor, desk, cases, chaos,
                 teams, zones, supplies, ai: Callable):
        self.scenario_dir = scenario_dir
        self.db = db
        self.keys = keys
        self.ingestor = ingestor
        self.desk = desk
        self.cases = cases
        self.chaos = chaos
        self.teams = teams
        self.zones = zones
        self.supplies = supplies
        self.ai = ai
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict = {"running": False, "pack": None}

    # ---- control ----------------------------------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            s = dict(self._state)
        if s.get("running"):
            s["scenario_minutes"] = round(self._minutes(), 1)
            s["scenario_time"] = self._clock(s["scenario_minutes"])
        s.pop("events", None)
        return s

    def start(self, pack: str, speed: float | None, by: str) -> dict:
        timeline = self.load(pack)
        speed = float(speed or timeline.get("speed") or 60)
        if not 0 < speed <= MAX_SPEED:
            raise ValueError(f"speed is from 1 to {MAX_SPEED} (scenario minutes per real minute)")
        self.stop()
        events = sorted(timeline["events"], key=lambda e: e["t"])
        movers = {t["id"]: t for t in self._pack_teams(pack) if t.get("device_id")}
        with self._lock:
            self._state = {"running": True, "pack": pack, "speed": speed, "start": timeline.get("start", "00:00"),
                           "started_at": timeutil.iso(timeutil.now()), "by": by, "events": events,
                           "total": len(events), "done": 0, "sent": {}, "cues": [], "held_replies": 0,
                           "story_done": not events, "errors": []}
            self._started = time.monotonic()
            self._movers = movers
            self._stopped_teams: set[str] = set()
            self._held: list[dict] = []
            self._acked: dict[str, str] = {}          # team -> job it said "on my way" for
            self._on_scene: dict[str, float] = {}     # team -> scenario minute it arrived
            self._last_ping: dict[str, float] = {}
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="replay", daemon=True)
            self._thread.start()
        log.info("replay of %s started at %sx", pack, speed)
        return self.status()

    def stop(self) -> dict:
        thread = self._thread
        if thread and thread.is_alive():
            self._stop.set()
            thread.join(timeout=5)
        with self._lock:
            self._state["running"] = False
            self._thread = None
        return self.status()

    def load(self, pack: str) -> dict:
        path = self.scenario_dir / "packs" / pack / "messages.json"
        if not path.exists():
            raise NotFound(f"no messages.json in {path.parent} (run scenario/generate.py --pack {pack})")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
            raise ValueError(f"{path.name} needs {{\"events\": [...]}}")
        return doc

    # ---- the loop ---------------------------------------------------------------------------------------
    def _minutes(self) -> float:
        return (time.monotonic() - self._started) / 60 * self._state["speed"]

    def _clock(self, minutes: float) -> str:
        h, m = (int(x) for x in self._state["start"].split(":"))
        total = h * 60 + m + int(minutes)
        return f"{total // 60 % 24:02d}:{total % 60:02d}"

    def _run(self) -> None:
        events = self._state["events"]
        i = 0
        while not self._stop.is_set():
            minutes = self._minutes()
            while i < len(events) and events[i]["t"] <= minutes:
                self._fire(events[i], minutes)
                i += 1
                with self._lock:
                    self._state["done"] = i
            try:
                self._release_held()
                self._move_teams(minutes)
            except Exception as exc:                       # one bad tick must not stop the replay
                log.exception("replay tick failed")
                self._error(f"teams: {exc}")
            if i >= len(events) and not self._state["story_done"]:
                with self._lock:
                    self._state["story_done"] = True
            if time.monotonic() - self._started > MAX_RUN_S:
                break
            self._stop.wait(TICK_S)
        with self._lock:
            self._state["running"] = False
            self._state["finished_at"] = timeutil.iso(timeutil.now())

    def _fire(self, e: dict, minutes: float) -> None:
        kind = e.get("kind")
        try:
            if kind == "report":
                self._send("report", e["payload"], e["device"], urgency=e.get("urgency", 2))
            elif kind == "text":
                self.desk.simulate([{k: e.get(k) for k in ("text", "sender", "lat", "lng", "hazard")}],
                                   None, "replay")
            elif kind == "reply":
                self._held.append(e)
            elif kind == "window":
                self.cases.set_window(e["zone"], timeutil.now() + timedelta(minutes=e["closes_in_min"]),
                                      e.get("text"), "replay")
            elif kind == "chaos":
                self.chaos.run(e["what"])
            elif kind == "ai_down":
                self.ai().outage(True)
            elif kind == "team_stop":
                self._stopped_teams.add(e["team"])
            elif kind == "hard_hit":
                self.zones.set_hard_hit(e["zones"], True, "replay")
            elif kind == "supply":
                side = "from" if e.get("move", "used") == "used" else "to"
                self.supplies.move({"kind": e.get("move", "used"), "item": e["item"], "qty": e["qty"],
                                    side: e.get("place") or "command_post"}, "replay")
            elif kind == "place":
                self.supplies.save_shelter({"id": e["id"], "occupancy": e["occupancy"]}, "replay")
            elif kind != "cue":
                raise ValueError(f"unknown event kind {kind!r}")
            with self._lock:
                self._state["sent"][kind] = self._state["sent"].get(kind, 0) + 1
                if kind in ("cue", "window", "chaos", "ai_down", "team_stop", "hard_hit", "supply", "place"):
                    if kind == "window":
                        e = dict(e, text=f"{e['zone']}: {e.get('text') or 'window closes'} in {e['closes_in_min']:g} min")
                    text = e.get("text") or {"chaos": f"Chaos: {e.get('what')}", "ai_down": "Internet cut: AI offline",
                                             "team_stop": f"{e.get('team')} stops moving",
                                             "hard_hit": f"Hard-hit: {', '.join(e.get('zones', []))}",
                                             "supply": f"{e.get('qty')} {e.get('item')} {e.get('move', 'used')}",
                                             "place": f"{e.get('id')} now holds {e.get('occupancy')}"}.get(kind, kind)
                    self._state["cues"] = ([{"at": self._clock(e["t"]), "kind": kind, "text": text}]
                                           + self._state["cues"])[:12]
        except Exception as exc:
            log.warning("replay event %s at t=%s failed: %s", kind, e.get("t"), exc)
            self._error(f"{kind} at {self._clock(e.get('t', 0))}: {exc}")

    def _error(self, text: str) -> None:
        with self._lock:
            self._state["errors"] = ([text] + self._state["errors"])[:10]

    def _release_held(self) -> None:
        """Alert replies wait for an active alert (the presenter issues it on cue)."""
        if not self._held:
            with self._lock:
                self._state["held_replies"] = 0
            return
        with self.db.read() as conn:
            active = self.desk.coverage.active_alerts(conn, timeutil.now())
        alert = max(active, key=lambda a: a["issued_at"]) if active else None
        if alert is not None:
            for e in self._held:
                payload = {"alert_id": alert["id"], "status": e.get("status", "safe"),
                           "registry_id": e.get("registry_id"), "lat": e.get("lat"), "lng": e.get("lng")}
                self._send("alert_reply", payload, e["device"], urgency=1)
            self._held = []
        with self._lock:
            self._state["held_replies"] = len(self._held)

    # ---- teams --------------------------------------------------------------------------------------------
    def _move_teams(self, minutes: float) -> None:
        if not self._movers:
            return
        now = timeutil.now()
        speedup = self._state["speed"]
        views = {t["id"]: t for t in self.teams.views(now)}
        for team_id, spec in self._movers.items():
            t = views.get(team_id)
            if t is None or team_id in self._stopped_teams or t["device_id"] != spec["device_id"]:
                continue
            device = spec["device_id"]
            if t["lat"] is None:
                continue
            target, status = None, t["status"]
            if status in ("assigned", "en_route") and t["case_id"]:
                if self._acked.get(team_id) != t["job_id"]:
                    self._send("ack", {"team_id": team_id, "job_id": t["job_id"], "status": "en_route"}, device, 3)
                    self._acked[team_id] = t["job_id"]
                    status = "en_route"
                case = self.db.one("SELECT lat, lng, people FROM cases WHERE id = ?", (t["case_id"],))
                if case and case["lat"] is not None:
                    target = (case["lat"], case["lng"])
            elif status == "on_scene" and t["job_id"]:
                arrived = self._on_scene.setdefault(team_id, minutes)
                if minutes - arrived >= ON_SCENE_MIN:
                    case = self.db.one("SELECT people FROM cases WHERE id = ?", (t["case_id"],))
                    outcome = {"people_helped": case["people"] if case else 1, "taken_to": None, "supplies_used": {}}
                    self._send("ack", {"team_id": team_id, "job_id": t["job_id"], "status": "done",
                                       "outcome": outcome}, device, 3)
                    self._on_scene.pop(team_id, None)
                continue
            elif status == "returning":
                base = self.db.one("SELECT base_lat, base_lng FROM teams WHERE id = ?", (team_id,))
                if base and base["base_lat"] is not None:
                    target = (base["base_lat"], base["base_lng"])
            if target is not None:
                step = (t["speed_kmh"] or 10) * 1000 / 3600 * TICK_S * speedup
                lat, lng = moved_toward(t["lat"], t["lng"], target[0], target[1], step)
                self._ping(t, device, lat, lng, status)
            elif time.monotonic() - self._last_ping.get(team_id, 0) >= IDLE_PING_S:
                self._ping(t, device, t["lat"], t["lng"], status)

    def _ping(self, t: dict, device: str, lat: float, lng: float, status: str) -> None:
        payload = {"team_id": t["id"], "lat": round(lat, 6), "lng": round(lng, 6), "gps_accuracy_m": 10,
                   "at": timeutil.iso(timeutil.now()), "status": status, "case_id": t["case_id"],
                   "battery": t["battery"] if t["battery"] is not None else 90, "fuel": t["fuel"]}
        self._send("team_ping", payload, device, 1, replace_key=f"ping:{t['id']}")
        self._last_ping[t["id"]] = time.monotonic()

    # ---- packets ------------------------------------------------------------------------------------------
    def _send(self, kind: str, payload: dict, device: str, urgency: int, replace_key: str | None = None) -> None:
        lat, lng = payload.get("lat"), payload.get("lng")
        area = geohash(lat, lng, 5) if lat is not None and lng is not None else "0"
        wire = phone_wire(kind, payload, device_id=device, signing_key=demo_key(device), box_pk=self.keys.box_pk,
                          urgency=urgency, area=area, replace_key=replace_key)
        result = self.ingestor.ingest_wire(wire)
        if result.status == "rejected":
            raise ValueError(f"{kind} from {device} rejected: {result.reason} {result.detail}".strip())

    def _pack_teams(self, pack: str) -> list[dict]:
        path = self.scenario_dir / "packs" / pack / "teams.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

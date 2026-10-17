"""Team tracker (System Design 9.7; Team Brief 3.7).

Every team is in exactly one state, and only the server changes it. Phones send acks and pings
that ask for a change:

  available -> assigned        the dispatcher assigns a job (suggest.py)
  assigned  -> en_route        ack "en_route" (On my way)
  -> on_scene                  a ping within tracker.arrival_radius_m of the case, or ack "arrived"
  on_scene  -> returning       ack "done" with the outcome form
  returning -> available       ack "ready", or a ping back at base
  any       -> out_of_service  ack or dispatcher, with a reason; never suggested until cleared

A phone speaks only for its own team (the team linked to its device). Late acks from the mesh
never move a team backwards. The scheduler flags a team overdue when it has not arrived by its
ETA plus 50% of the travel time (at least 10 min), and not heard from after 15 min without a
ping while en route. Every change goes into team_status_log and the audit log.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from . import timeutil
from .cases import CaseBook, NotFound
from .db import Database
from .packets import distance_m
from .supplies import SupplyBook

STATUSES = ("available", "assigned", "en_route", "on_scene", "returning", "out_of_service")
ON_JOB = ("assigned", "en_route", "on_scene")
STEP = {"available": 0, "assigned": 1, "en_route": 2, "on_scene": 3, "returning": 4}
NEED_LABELS = {"boat": "Boats", "truck": "Trucks", "medic": "Medics", "rescue": "Search and rescue",
               "fire": "Fire crews", "evac": "Evacuation vehicles", "welfare": "Welfare teams"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "team"


def hhmm(iso: str | None) -> str:
    return timeutil.parse(iso).strftime("%H:%M") if iso else "?"


def capabilities(team_type: str, skills: list[str], constants: dict) -> list[str]:
    """What a team can do, from its type and its crew's skills. Anyone can do a welfare check."""
    t = constants["teams"]
    found = set(t["capabilities_by_type"].get(team_type, [])) | {"welfare"}
    for skill in skills:
        found |= set(t["capabilities_by_skill"].get(skill, []))
    return [n for n in t["needs"] if n in found]


def travel_minutes(lat1: float, lng1: float, lat2: float, lng2: float, speed_kmh: float, detour: float) -> float:
    """Straight-line distance x detour / speed (Team Brief 3.9 i)."""
    return distance_m(lat1, lng1, lat2, lng2) / 1000 * detour / speed_kmh * 60


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class TeamBook:
    def __init__(self, db: Database, cases: CaseBook, supplies: SupplyBook, constants: dict):
        self.db = db
        self.cases = cases
        self.supplies = supplies
        self.constants = constants
        self.rules = constants["tracker"]

    # ---- the dispatcher -------------------------------------------------------------------------------
    def save(self, req: dict, by: str, now: datetime | None = None) -> dict:
        """Add a team or change its details (POST /api/teams). New teams start available at (lat, lng)."""
        now = now or timeutil.now()
        types = self.constants["teams"]["types"]
        with self.db.write() as conn:
            tid = req.get("id") or self._free_id(conn, slug(req.get("name") or ""))
            old = conn.execute("SELECT * FROM teams WHERE id = ?", (tid,)).fetchone()
            team = dict(old) if old else {"id": tid, "name": None, "type": None, "capabilities": None,
                                          "device_id": None, "status": "available", "status_since": timeutil.iso(now),
                                          "lat": None, "lng": None, "fuel": None, "battery": None, "speed_kmh": None,
                                          "base_lat": None, "base_lng": None, "flags": "[]"}
            for key in ("name", "type", "device_id", "fuel", "battery", "speed_kmh"):
                if req.get(key) is not None:
                    team[key] = req[key]
            if not team["name"] or team["type"] not in types:
                raise ValueError(f"a team needs a name and a type ({', '.join(types)})")
            if req.get("capabilities") is not None:              # the dispatcher's list replaces the derived one
                unknown = sorted(set(req["capabilities"]) - set(self.constants["teams"]["needs"]))
                if unknown:
                    raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
                wanted = set(req["capabilities"]) | {"welfare"}
                team["capabilities"] = json.dumps([n for n in self.constants["teams"]["needs"] if n in wanted])
            elif old is None or req.get("type") is not None or req.get("skills") is not None:
                team["capabilities"] = json.dumps(capabilities(team["type"], req.get("skills") or [], self.constants))
            if req.get("lat") is not None and req.get("lng") is not None:
                team["lat"], team["lng"] = req["lat"], req["lng"]
                if old is None or req.get("base", False):
                    team["base_lat"], team["base_lng"] = req["lat"], req["lng"]
            if team["device_id"]:
                other = conn.execute("SELECT id FROM teams WHERE device_id = ? AND id != ?",
                                     (team["device_id"], tid)).fetchone()
                if other:
                    raise ValueError(f"device {team['device_id']} already belongs to team {other[0]}")
            team["speed_kmh"] = team["speed_kmh"] or self.constants["teams"]["speed_kmh"][team["type"]]
            self._write(conn, team)
            self.cases.audit(conn, now, by, "team" if old is None else "team_update", f"team:{tid}",
                             f"{team['name']} ({team['type']})")
        return self.view(tid, now)

    def set_status(self, team_id: str, status: str, reason: str | None, by: str,
                   now: datetime | None = None) -> dict:
        """The dispatcher sets a status by hand (POST /api/teams/{id}/status), e.g. after a radio call."""
        now = now or timeutil.now()
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if status == "out_of_service" and not reason:
            raise ValueError("out of service needs a reason")
        with self.db.write() as conn:
            team = self._team(conn, team_id)
            job = self._job(conn, team)
            if status in ("en_route", "on_scene") and job is None:
                raise ValueError(f"{team['name']} has no job")
            if status == "assigned":
                raise ValueError("assign a job with POST /api/assign")
            if status == "on_scene":
                self._arrive(conn, team, job, now, by)
            elif status == "en_route":
                self._advance(conn, team, job, "en_route", now, by, reason)
            elif status == "returning" and job is not None:
                self._done(conn, team, job, {}, now, by)        # finished, reported by radio: no outcome form
            else:
                if job is not None:
                    self._end_job(conn, team, job, "cancelled", now, by, reason or f"{team['name']} set {status}")
                self._set(conn, team, status, now, by, reason)
        return self.view(team_id, now)

    # ---- phones (inside the ingest transaction) --------------------------------------------------------
    def upsert_volunteer(self, conn: sqlite3.Connection, body: dict, payload: dict, created: datetime,
                         now: datetime) -> str:
        """A volunteer or rescue-team phone at setup. It joins the team that already uses its device,
        or claims a dispatcher-made team of the same name with no phone yet, or starts a new team."""
        device = body["from_device"]
        team_type = payload.get("team_type") or ("volunteer" if payload["role"] == "volunteer" else "rescue")
        row = conn.execute("SELECT * FROM teams WHERE device_id = ?", (device,)).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM teams WHERE id = ? AND device_id IS NULL", (slug(payload["name"]),)).fetchone()
        caps = capabilities(team_type, payload["skills"], self.constants)
        if row is None:
            team = {"id": self._free_id(conn, slug(payload["name"])), "status": "available",
                    "status_since": timeutil.iso(now), "fuel": None, "battery": None, "flags": "[]",
                    "lat": payload.get("lat"), "lng": payload.get("lng"),
                    "base_lat": payload.get("lat"), "base_lng": payload.get("lng")}
            action = "team"
        else:
            team = dict(row)
            caps = list(dict.fromkeys(caps + json.loads(team["capabilities"] or "[]")))
            if team["lat"] is None and payload.get("lat") is not None:
                team.update(lat=payload["lat"], lng=payload["lng"], base_lat=payload["lat"], base_lng=payload["lng"])
            action = "team_update"
        team.update(name=payload["name"], type=team_type, capabilities=json.dumps(caps), device_id=device,
                    speed_kmh=team.get("speed_kmh") or self.constants["teams"]["speed_kmh"][team_type])
        self._write(conn, team)
        self.cases.audit(conn, now, device, action, f"team:{team['id']}",
                         f"{payload['name']} ({team_type}); {', '.join(caps)}")
        return team["id"]

    def on_ping(self, conn: sqlite3.Connection, body: dict, payload: dict, created: datetime,
                now: datetime) -> int | None:
        """A location ping. Only the newest position counts; arrival and 'back at base' follow from it.
        Returns the case ID when the ping put the team on scene."""
        team = self._team_of(conn, body["from_device"], payload["team_id"], now, "ping")
        if team is None:
            return None
        try:
            at = min(timeutil.parse(payload["at"]), now)       # a phone clock ahead of ours is trusted no further
        except ValueError:
            at = created
        conn.execute("INSERT INTO team_pings(team_id, lat, lng, accuracy_m, at, status, battery, fuel, received_at) "
                     "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (team["id"], payload["lat"], payload["lng"], payload.get("gps_accuracy_m"), timeutil.iso(at),
                      payload["status"], payload.get("battery"), payload.get("fuel"), timeutil.iso(now)))
        if team["ping_at"] and at < timeutil.parse(team["ping_at"]):
            return None                                          # an older position, relayed late: trail only
        team.update(lat=payload["lat"], lng=payload["lng"], accuracy_m=payload.get("gps_accuracy_m"),
                    ping_at=timeutil.iso(at), ping_received_at=timeutil.iso(now))
        if payload.get("battery") is not None:
            team["battery"] = payload["battery"]
        if payload.get("fuel") is not None:
            team["fuel"] = payload["fuel"]
        flags = [f for f in json.loads(team["flags"] or "[]") if f != "not_heard_from"]
        team["flags"] = json.dumps(flags)
        self._write(conn, team)
        radius = self.rules["arrival_radius_m"]
        job = self._job(conn, team)
        if team["status"] in ("assigned", "en_route") and job is not None:
            case = conn.execute("SELECT lat, lng FROM cases WHERE id = ?", (job["case_id"],)).fetchone()
            if case and case["lat"] is not None and distance_m(payload["lat"], payload["lng"], case["lat"],
                                                               case["lng"]) <= radius:
                self._arrive(conn, team, job, at, "ping")
                return job["case_id"]
        if team["status"] == "returning" and team["base_lat"] is not None and distance_m(
                payload["lat"], payload["lng"], team["base_lat"], team["base_lng"]) <= radius:
            self._set(conn, team, "available", at, "ping", "back at base")
        return None

    def on_ack(self, conn: sqlite3.Connection, body: dict, payload: dict, created: datetime,
               now: datetime) -> int | None:
        """en_route, arrived, done (with the outcome), cant_reach, ready or out_of_service.
        Returns the case ID it changed, if any."""
        device = body["from_device"]
        team = self._team_of(conn, device, payload["team_id"], now, "ack")
        if team is None:
            return None
        status, reason = payload["status"], payload.get("reason") or None
        job = self._job(conn, team)
        if status in ("en_route", "arrived", "done", "cant_reach"):
            if job is None or (payload.get("job_id") and payload["job_id"] != job["id"]):
                self.cases.audit(conn, now, device, "ack_ignored", f"team:{team['id']}",
                                 f"{status} for {payload.get('job_id')}, which is not its open job")
                return None
            if status == "en_route":
                self._advance(conn, team, job, "en_route", created, device, reason)
            elif status == "arrived":
                self._arrive(conn, team, job, created, "team")
            elif status == "done":
                self._done(conn, team, job, payload.get("outcome") or {}, created, device)
            else:
                self._end_job(conn, team, job, "cant_reach", created, device, reason or "can't reach")
                self._set(conn, team, "available", created, device, reason or "can't reach")
            return job["case_id"]
        if status == "ready":
            if team["status"] in ON_JOB:
                self.cases.audit(conn, now, device, "ack_ignored", f"team:{team['id']}", "ready while on a job")
                return None
            self._set(conn, team, "available", created, device, reason)
            return None
        case_id = job["case_id"] if job else None                    # out_of_service
        if job is not None:
            self._end_job(conn, team, job, "cancelled", created, device, f"team out of service: {reason or 'no reason'}")
        self._set(conn, team, "out_of_service", created, device, reason)
        return case_id

    # ---- jobs (assign is in suggest.py) -----------------------------------------------------------------
    def start_job(self, conn: sqlite3.Connection, team: dict, job_id: str, case_id: int, eta: str,
                  now: datetime, by: str) -> None:
        team = self._team(conn, team["id"])
        team.update(job_id=job_id, case_id=case_id, eta=eta, flags="[]")
        self._write(conn, team)
        self._set(conn, team, "assigned", now, by, f"job {job_id} for case #{case_id}")

    def release(self, conn: sqlite3.Connection, team_id: str, now: datetime, by: str, why: str) -> None:
        """A job is taken from a team (reassigned): the team is available again."""
        team = self._team(conn, team_id)
        job = self._job(conn, team)
        if job is not None:
            self._end_job(conn, team, job, "cancelled", now, by, why, release_case=False)
        self._set(conn, team, "available", now, by, why)

    # ---- the scheduler -------------------------------------------------------------------------------------
    def checks(self, now: datetime | None = None) -> int:
        """Overdue and not-heard-from flags. Returns how many teams carry a flag."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            teams = _rows(conn, "SELECT * FROM teams")
            jobs = {j["id"]: j for j in _rows(conn, "SELECT * FROM jobs WHERE status IN ('assigned', 'en_route', 'on_scene')")}
        changes, flagged = [], 0
        for t in teams:
            flags = set()
            job = jobs.get(t["job_id"])
            if t["status"] in ("assigned", "en_route") and job and job["eta"]:
                grace = max((self.rules["overdue_factor"] - 1) * (job["travel_min"] or 0), self.rules["overdue_min_minutes"])
                if now > timeutil.parse(job["eta"]) + timedelta(minutes=grace):
                    flags.add("overdue")
            if t["status"] == "en_route":
                last = t["ping_at"] or t["status_since"]
                if last and now - timeutil.parse(last) > timedelta(minutes=self.rules["not_heard_minutes"]):
                    flags.add("not_heard_from")
            old = set(json.loads(t["flags"] or "[]"))
            flagged += bool(flags)
            if flags != old:
                changes.append((t, flags, flags - old))
        if changes:
            with self.db.write() as conn:
                for t, flags, raised in changes:
                    conn.execute("UPDATE teams SET flags = ? WHERE id = ?", (json.dumps(sorted(flags)), t["id"]))
                    for flag in sorted(raised):
                        self.cases.audit(conn, now, "server", flag, f"team:{t['id']}", "")
        return flagged

    # ---- views -----------------------------------------------------------------------------------------------
    def views(self, now: datetime | None = None) -> list[dict]:
        now = now or timeutil.now()
        with self.db.read() as conn:
            teams = _rows(conn, "SELECT t.*, d.last_upload_at FROM teams t LEFT JOIN devices d ON d.id = t.device_id "
                                "ORDER BY t.name")
            trails: dict[str, list] = {}
            for p in _rows(conn, "SELECT team_id, lat, lng, at FROM team_pings ORDER BY at DESC"):
                trail = trails.setdefault(p["team_id"], [])
                if len(trail) < self.rules["trail"]:
                    trail.append({"lat": p["lat"], "lng": p["lng"], "at": p["at"]})
            jobs = {j["id"]: j for j in _rows(conn, "SELECT * FROM jobs")}
            cases = {c["id"]: c for c in _rows(conn, "SELECT id, lat, lng, landmark, zone FROM cases WHERE id IN "
                                                     "(SELECT case_id FROM teams WHERE case_id IS NOT NULL)")}
            loads = self.supplies.loads(conn)
        stale_after = timedelta(minutes=self.rules["stale_icon_minutes"])
        out = []
        for t in teams:
            job = jobs.get(t["job_id"]) if t["job_id"] else None
            case = cases.get(t["case_id"]) if t["case_id"] else None
            away = None
            if case and case["lat"] is not None and t["lat"] is not None:
                away = round(distance_m(t["lat"], t["lng"], case["lat"], case["lng"]))
            out.append({
                "id": t["id"], "name": t["name"], "type": t["type"],
                "capabilities": json.loads(t["capabilities"] or "[]"), "device_id": t["device_id"],
                "status": t["status"], "status_since": t["status_since"], "flags": json.loads(t["flags"] or "[]"),
                "case_id": t["case_id"], "job_id": t["job_id"], "eta": t["eta"],
                "arrived_at": job["arrived_at"] if job else None, "lat": t["lat"], "lng": t["lng"],
                "accuracy_m": t["accuracy_m"], "ping_at": t["ping_at"], "ping_received_at": t["ping_received_at"],
                "last_contact": t["last_upload_at"],
                "stale": t["ping_at"] is None or now - timeutil.parse(t["ping_at"]) > stale_after,
                "battery": t["battery"], "fuel": t["fuel"], "speed_kmh": t["speed_kmh"],
                "distance_to_case_m": away, "trail": trails.get(t["id"], []), "load": loads.get(t["id"], {}),
            })
        return out

    def view(self, team_id: str, now: datetime | None = None) -> dict:
        found = next((t for t in self.views(now) if t["id"] == team_id), None)
        if found is None:
            raise NotFound(f"unknown team {team_id}")
        return found

    def summary(self, views: list[dict]) -> tuple[dict, list[str]]:
        """Counters per status and per capability, and the warnings for the top bar."""
        counts = {s: sum(1 for t in views if t["status"] == s) for s in STATUSES}
        by_need = {}
        for need in self.constants["teams"]["needs"]:
            able = [t for t in views if need in t["capabilities"] and t["status"] != "out_of_service"]
            if able and need != "welfare":
                by_need[need] = {"total": len(able), "free": sum(1 for t in able if t["status"] == "available")}
        warnings = []
        for t in views:
            if "overdue" in t["flags"]:
                away = f", {t['distance_to_case_m'] / 1000:.1f} km away" if t["distance_to_case_m"] is not None else ""
                warnings.append(f"{t['name']} overdue: ETA {hhmm(t['eta'])}, last seen {hhmm(t['ping_at'])}{away}")
            if "not_heard_from" in t["flags"]:
                warnings.append(f"{t['name']} not heard from since {hhmm(t['ping_at'] or t['status_since'])}")
        warnings += [f"{NEED_LABELS[n]}: none free" for n, c in by_need.items() if c["free"] == 0]
        return dict(counts, by_capability=by_need), warnings

    # ---- helpers -----------------------------------------------------------------------------------------
    def _team(self, conn: sqlite3.Connection, team_id: str) -> dict:
        row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if row is None:
            raise NotFound(f"unknown team {team_id}")
        return dict(row)

    def _team_of(self, conn: sqlite3.Connection, device: str, claimed: str, now: datetime, what: str) -> dict | None:
        """The team a phone speaks for: the one linked to its device, whatever team_id it sends."""
        row = conn.execute("SELECT * FROM teams WHERE device_id = ?", (device,)).fetchone()
        if row is None:
            self.cases.audit(conn, now, device, f"{what}_ignored", f"device:{device}",
                             f"no team uses this phone (it said {claimed})")
            return None
        return dict(row)

    @staticmethod
    def _job(conn: sqlite3.Connection, team: dict) -> dict | None:
        if not team.get("job_id"):
            return None
        row = conn.execute("SELECT * FROM jobs WHERE id = ? AND status IN ('assigned', 'en_route', 'on_scene')",
                           (team["job_id"],)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _free_id(conn: sqlite3.Connection, base: str) -> str:
        tid, n = base, 2
        while conn.execute("SELECT 1 FROM teams WHERE id = ?", (tid,)).fetchone():
            tid, n = f"{base}_{n}", n + 1
        return tid

    @staticmethod
    def _write(conn: sqlite3.Connection, team: dict) -> None:
        cols = ("id", "name", "type", "capabilities", "device_id", "status", "status_since", "case_id", "eta", "lat",
                "lng", "ping_at", "battery", "fuel", "load", "flags", "speed_kmh", "job_id", "base_lat", "base_lng",
                "accuracy_m", "ping_received_at")
        row = {c: team.get(c) for c in cols}
        conn.execute(f"INSERT INTO teams({', '.join(cols)}) VALUES({', '.join(':' + c for c in cols)}) "
                     f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols[1:])}", row)

    def _set(self, conn: sqlite3.Connection, team: dict, status: str, at: datetime, by: str,
             reason: str | None) -> None:
        if status in ("available", "returning", "out_of_service"):
            team.update(case_id=None, job_id=None, eta=None, flags="[]")
        team.update(status=status, status_since=timeutil.iso(at))
        self._write(conn, team)
        conn.execute("INSERT INTO team_status_log(team_id, status, at, by, reason) VALUES(?, ?, ?, ?, ?)",
                     (team["id"], status, timeutil.iso(at), by, reason))
        self.cases.audit(conn, at, by, f"team_{status}", f"team:{team['id']}", reason or "")

    def _advance(self, conn: sqlite3.Connection, team: dict, job: dict, status: str, at: datetime, by: str,
                 reason: str | None) -> None:
        """Move along the job; a late ack from the mesh never moves a team backwards."""
        if STEP.get(team["status"], 9) >= STEP[status]:
            return
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job["id"]))
        self._case_status(conn, job["case_id"], status, at, by)
        self._set(conn, team, status, at, by, reason)

    def _arrive(self, conn: sqlite3.Connection, team: dict, job: dict, at: datetime, by: str) -> None:
        """On scene, by a ping near the case or by the team's 'Arrived'. Both together confirm it."""
        if team["status"] == "on_scene":
            if job["arrived_by"] and job["arrived_by"] != by:
                conn.execute("UPDATE jobs SET arrived_by = 'both' WHERE id = ?", (job["id"],))
                self.cases.audit(conn, at, by, "arrival_confirmed", f"case:{job['case_id']}", f"{team['name']}, ping and team")
            return
        conn.execute("UPDATE jobs SET arrived_at = ?, arrived_by = ? WHERE id = ?", (timeutil.iso(at), by, job["id"]))
        self._advance(conn, team, job, "on_scene", at, by, f"arrived ({by})")

    def _done(self, conn: sqlite3.Connection, team: dict, job: dict, outcome: dict, at: datetime, by: str) -> None:
        """'Done' with the outcome form: the case closes, the place's head count and the stock update."""
        people, taken = outcome.get("people_helped"), outcome.get("taken_to")
        conn.execute("UPDATE jobs SET status = 'done', outcome = ?, done_at = ? WHERE id = ?",
                     (json.dumps(outcome), timeutil.iso(at), job["id"]))
        if people and taken and taken not in ("hospital", "stayed"):
            if not self.supplies.add_people(conn, taken, people, at, by):
                self.cases.audit(conn, at, by, "unknown_place", f"case:{job['case_id']}", f"taken to {taken}")
        self.supplies.use_load(conn, team["id"], outcome.get("supplies_used") or {}, job["id"], at, by)
        self._case_status(conn, job["case_id"], "done", at, by,
                          f"{team['name']}: {people if people is not None else '?'} helped"
                          + (f", taken to {taken}" if taken else ""))
        self._set(conn, team, "returning", at, by, f"job {job['id']} done")

    def _end_job(self, conn: sqlite3.Connection, team: dict, job: dict, status: str, at: datetime, by: str,
                 why: str, release_case: bool = True) -> None:
        """The job stops without being done; the case goes back to the queue for another team."""
        conn.execute("UPDATE jobs SET status = ?, outcome = ? WHERE id = ?",
                     (status, json.dumps({"reason": why}), job["id"]))
        if release_case:
            conn.execute("UPDATE cases SET status = CASE WHEN verified THEN 'verified' ELSE 'new' END, team_id = NULL "
                         "WHERE id = ? AND team_id = ?", (job["case_id"], team["id"]))
            self.cases.audit(conn, at, by, "unassigned", f"case:{job['case_id']}", f"{team['name']}: {why}")

    def _case_status(self, conn: sqlite3.Connection, case_id: int, status: str, at: datetime, by: str,
                     detail: str = "") -> None:
        conn.execute("UPDATE cases SET status = ? WHERE id = ?", (status, case_id))
        self.cases.audit(conn, at, by, status, f"case:{case_id}", detail)

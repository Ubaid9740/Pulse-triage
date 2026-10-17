"""Alerts (System Design 5.1 and 8.3; Team Brief 3.2): create, update, cancel and announce.

POST /api/alerts makes a new alert. With "replaces" it updates an active alert (anything left
out is kept); with "cancel" as well it is the all-clear that ends it. Headline and steps come
from the hazard profile's template for the severity unless the dispatcher wrote them; places
default to the nearest shelters (cooling centres for heat) with space.

Every alert is a public packet signed with the command post key, queued at urgency 4 with
replace_key "alert:<first alert of the chain>", so relays keep only the newest version, and it
expires when the alert does. Phones show only alerts whose signature matches the setup key.
"""
from __future__ import annotations

import json
import re
import sqlite3
import string
from datetime import datetime, timedelta

from . import outbound, timeutil
from .cases import CaseBook, NotFound
from .coverage import Coverage
from .crypto import CommandPostKeys
from .db import Database
from .packets import distance_m, geohash
from .profiles import Profiles
from .schemas import Schemas
from .zones import ZoneBook, ZoneMap, centroid

SEVERITIES = ("watch", "warning", "emergency")
PLACE_TYPES = ("shelter", "cooling_centre", "hospital", "other")
CURRENT = ("active", "all_clear")


def join_names(names: list[str], word: str | None) -> str:
    """'A', 'A and B', 'A, B and C' (just commas when the language has no joining word)."""
    if len(names) <= 1 or not word:
        return ", ".join(names)
    return f"{', '.join(names[:-1])} {word} {names[-1]}"


def fill(text: str, values: dict) -> str:
    """Fill {placeholders}. A missing value is an error the dispatcher can fix."""
    missing = [f for _, f, _, _ in string.Formatter().parse(text) if f and f not in values]
    if missing:
        raise ValueError(f"the template needs {', '.join('{' + m + '}' for m in missing)}; send it in 'fill'")
    return text.format_map(values)


def sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class AlertBook:
    def __init__(self, db: Database, keys: CommandPostKeys, schemas: Schemas, profiles: Profiles,
                 zone_map: ZoneMap, coverage: Coverage, zones: ZoneBook, cases: CaseBook, constants: dict):
        self.db = db
        self.keys = keys
        self.schemas = schemas
        self.profiles = profiles
        self.zone_map = zone_map
        self.coverage = coverage
        self.zones = zones
        self.cases = cases
        self.constants = constants
        self.rules = constants["alerts"]

    # ---- create, update, cancel ----------------------------------------------------------------
    def issue(self, req: dict, by: str, now: datetime | None = None) -> dict:
        """Sign and queue an alert (POST /api/alerts). Returns its ID, packet and outbound seq."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            alert_id = self._next_id(conn)
            payload, prev, root = self._build(conn, req, alert_id, now)
            hours = max(timeutil.hours_between(now, timeutil.parse(payload["valid_until"])), 1 / 60)
            queued = outbound.enqueue(conn, self.keys, self.constants, "alert", payload, area=self._area(payload["zones"]),
                                      replace_key=f"alert:{root}", expiry_hours=hours, created=now)
            conn.execute("INSERT INTO alerts(id, hazard, severity, zones, body, issued_at, valid_until, replaces, "
                         "packet_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (alert_id, payload["hazard"], payload["severity"], json.dumps(payload["zones"]),
                          json.dumps(payload), payload["issued_at"], payload["valid_until"], payload["replaces"],
                          queued["packet_id"]))
            if prev:
                conn.execute("UPDATE alerts SET ended_at = ?, ended_why = ? WHERE id = ?",
                             (payload["issued_at"], "cancelled" if payload["cancel"] else "replaced", prev["id"]))
            action = "all_clear" if payload["cancel"] else "alert_update" if prev else "alert"
            self.cases.audit(conn, now, by, action, f"alert:{alert_id}",
                             f"{payload['severity']} {payload['hazard']} for {', '.join(payload['zones'])}"
                             + (f", replaces {prev['id']}" if prev else ""))
        self.zones.update(now)
        return {"alert_id": alert_id, "packet_id": queued["packet_id"], "outbound_seq": queued["seq"],
                "alert": self.view(alert_id, now)}

    def preview(self, req: dict, now: datetime | None = None) -> dict:
        """The payload POST /api/alerts would send, for the composer's phone preview. Nothing is queued."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            payload, _, _ = self._build(conn, req, self._next_id(conn), now)
        return payload

    def expire(self, now: datetime | None = None) -> int:
        """Mark alerts past valid_until as ended (the scheduler). Returns how many."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            due = [r for r in _rows(conn, "SELECT id, valid_until FROM alerts WHERE ended_at IS NULL")
                   if timeutil.parse(r["valid_until"]) <= now]
        if not due:
            return 0
        with self.db.write() as conn:
            for r in due:
                conn.execute("UPDATE alerts SET ended_at = ?, ended_why = 'expired' WHERE id = ?", (r["valid_until"], r["id"]))
                self.cases.audit(conn, now, "server", "alert_expired", f"alert:{r['id']}", f"valid until {r['valid_until']}")
        self.zones.mark_dirty()
        return len(due)

    # ---- views ------------------------------------------------------------------------------------
    def views(self, now: datetime | None = None, current_only: bool = False) -> list[dict]:
        """Every alert, newest first, with its status, replies and coverage (alert_summary.schema.json).
        current_only: the active alerts and all-clears still in force (the snapshot)."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            rows = _rows(conn, "SELECT * FROM alerts ORDER BY issued_at DESC, id DESC")
            replies: dict[str, dict[str, int]] = {}
            for r in _rows(conn, "SELECT alert_id, status, COUNT(*) AS n FROM alert_replies GROUP BY alert_id, status"):
                replies.setdefault(r["alert_id"], {})[r["status"]] = r["n"]
            active = {a["id"]: a for a in self.coverage.active_alerts(conn, now)}
            counts = self.coverage.zone_counts(conn, list(active.values()))
        by_id = {r["id"]: r for r in rows}
        out = []
        for r in rows:
            status = self._status(r, now)
            if current_only and status not in CURRENT:
                continue
            chain = self._chain(by_id, r["id"])
            heard = {s: sum(replies.get(a, {}).get(s, 0) for a in chain) for s in ("safe", "need_help", "helping")}
            body = json.loads(r["body"])
            coverage = None
            if r["id"] in active:
                registered = sum(counts.get(z, (0, 0))[0] for z in body["zones"])
                confirmed = sum(counts.get(z, (0, 0))[1] for z in body["zones"])
                coverage = {"registered": registered, "confirmed": confirmed,
                            "coverage": round(confirmed / registered, 2) if registered else None}
            out.append({
                "id": r["id"], "hazard": body["hazard"], "severity": body["severity"], "zones": body["zones"],
                "headline": body["headline"], "do_now": body["do_now"], "places": body["places"],
                "issued_at": body["issued_at"], "valid_until": body["valid_until"], "replaces": body["replaces"],
                "cancel": body["cancel"], "status": status, "ended_at": r["ended_at"], "packet_id": r["packet_id"],
                "replies": dict(heard, total=sum(heard.values())), "coverage": coverage,
                "timeout_at": self.coverage.timeout_at(active[r["id"]]) if r["id"] in active else None,
            })
        return out

    def view(self, alert_id: str, now: datetime | None = None) -> dict:
        found = next((a for a in self.views(now) if a["id"] == alert_id), None)
        if found is None:
            raise NotFound(f"unknown alert {alert_id}")
        return found

    def announcement(self, alert_id: str, languages: list[str] | None = None) -> dict:
        """The loudspeaker and radio script (about 20 seconds), one per language. If a script runs
        long, the closing repeat of the headline is left out."""
        alert = self.view(alert_id)
        frames = self.profiles.common.get("announcement", {})
        wpm, target = self.rules["announcement_words_per_minute"], self.rules["announcement_target_seconds"]
        scripts = []
        for lang in languages or list(alert["headline"]):
            if lang not in alert["headline"]:
                raise ValueError(f"{alert_id} has no text in {lang!r}")
            if lang not in frames:
                raise ValueError(f"no announcement wording in {lang!r} in shared/profiles/common.json")
            frame, headline = frames[lang], alert["headline"][lang]
            parts = [fill(frame["intro"], {"zones": join_names(alert["zones"], frame["and"])}), sentence(headline)]
            parts += [sentence(step) for step in alert["do_now"].get(lang, [])]
            if alert["places"] and not alert["cancel"]:
                parts.append(fill(frame["place"], {"places": join_names([p["name"] for p in alert["places"]], frame["and"])}))
            parts.append(frame["pass_on"])
            full = parts + [sentence(fill(frame["repeat"], {"headline": headline}))]
            text = " ".join(full)
            if len(text.split()) / wpm * 60 > target:
                text = " ".join(parts)
            words = len(text.split())
            scripts.append({"language": lang, "text": text, "words": words, "seconds": round(words / wpm * 60)})
        return {"alert_id": alert_id, "target_seconds": target, "scripts": scripts}

    # ---- building the payload -------------------------------------------------------------------------
    def _build(self, conn: sqlite3.Connection, req: dict, alert_id: str, now: datetime) -> tuple[dict, dict | None, str]:
        replaces, cancel = req.get("replaces"), bool(req.get("cancel"))
        prev = None
        if replaces:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (replaces,)).fetchone()
            if row is None:
                raise NotFound(f"unknown alert {replaces}")
            prev = dict(row)
            status = self._status(prev, now)
            if status != "active":
                raise ValueError(f"{replaces} is {status.replace('_', ' ')}; only an active alert can be updated or cancelled")
        elif cancel:
            raise ValueError("an all-clear needs 'replaces': the alert it ends")
        old = json.loads(prev["body"]) if prev else {}
        hazard = req.get("hazard") or old.get("hazard")
        severity = req.get("severity") or old.get("severity")
        zones = list(dict.fromkeys(req.get("zones") or old.get("zones") or []))
        if not (hazard and severity and zones):
            raise ValueError("a new alert needs hazard, severity and zones")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        known = set(self.zone_map.names)
        if not known:
            raise ValueError("no zones loaded yet; POST /api/zones/import first")
        unknown = [z for z in zones if z not in known]
        if unknown:
            raise ValueError(f"unknown zones: {', '.join(unknown)}")
        keep = bool(old) and not cancel and (old["hazard"], old["severity"], old["zones"]) == (hazard, severity, zones)
        languages = req.get("languages") or list(req.get("headline") or {}) or (list(old["headline"]) if keep else ["en"])
        languages = ["en"] + [lang for lang in dict.fromkeys(languages) if lang != "en"]
        headline, do_now = self._wording(hazard, severity, zones, languages, req, old if keep else None, cancel)
        payload = {
            "alert_id": alert_id, "hazard": hazard, "severity": severity, "zones": zones,
            "headline": headline, "do_now": do_now,
            "places": self._places(conn, req.get("places"), old, hazard, zones),
            "issued_at": timeutil.iso(now), "valid_until": timeutil.iso(self._valid_until(req.get("valid_until"), old, now, cancel)),
            "replaces": replaces, "cancel": cancel,
        }
        self.schemas.check("payloads/alert", payload)
        root = self._root(conn, prev["id"]) if prev else alert_id
        return payload, prev, root

    def _wording(self, hazard: str, severity: str, zones: list[str], languages: list[str], req: dict,
                 kept: dict | None, cancel: bool) -> tuple[dict, dict]:
        """Headline and steps: what the dispatcher wrote, else the current text (an update that
        changes nothing they mention), else the template filled in."""
        given_headline, given_steps = req.get("headline"), req.get("do_now")
        if given_headline and given_steps is not None:
            return given_headline, given_steps
        if kept:
            return given_headline or kept["headline"], kept["do_now"] if given_steps is None else given_steps
        if cancel:
            template, what = self.profiles.common.get("all_clear"), "all-clear"
        else:
            template, what = self.profiles.get(hazard).get("alert_templates", {}).get(severity), f"{hazard} {severity}"
        if not template:
            raise ValueError(f"no {what} template; write the headline and steps")
        missing = [lang for lang in languages if lang not in template]
        if missing:
            raise ValueError(f"no {what} template in {', '.join(missing)}; write the text or leave the language out")
        frames = self.profiles.common.get("announcement", {})
        headline, steps = {}, {}
        for lang in languages:
            values = {"zones": join_names(zones, frames.get(lang, {}).get("and")), **(req.get("fill") or {})}
            headline[lang] = fill(template[lang]["headline"], values)
            steps[lang] = [fill(step, values) for step in template[lang]["do_now"]]
        return given_headline or headline, given_steps if given_steps is not None else steps

    def _places(self, conn: sqlite3.Connection, ids: list[str] | None, old: dict, hazard: str,
                zones: list[str]) -> list[dict]:
        """Named places; else the replaced alert's; else the nearest with space (cooling centres
        first in a heatwave, shelters otherwise)."""
        rows = {r["id"]: r for r in _rows(conn, "SELECT * FROM shelters")}
        if ids is None and old:
            return old["places"]
        if ids is not None:
            unknown = [i for i in ids if i not in rows]
            if unknown:
                raise ValueError(f"unknown places: {', '.join(unknown)}")
            chosen = [rows[i] for i in dict.fromkeys(ids)]
            unplaced = [r["id"] for r in chosen if r["lat"] is None or r["lng"] is None]
            if unplaced:
                raise ValueError(f"places without a position: {', '.join(unplaced)}")
        else:
            centre = self._centre(zones)
            if centre is None:
                return []
            prefer = "cooling_centre" if hazard == "heat" else "shelter"
            free = [r for r in rows.values() if r["type"] in ("shelter", "cooling_centre") and r["lat"] is not None
                    and r["lng"] is not None and (r["capacity"] is None or (r["occupancy"] or 0) < r["capacity"])]
            free.sort(key=lambda r: (r["type"] != prefer, distance_m(centre[0], centre[1], r["lat"], r["lng"])))
            chosen = free[:self.rules["max_places"]]
        return [{"id": r["id"], "name": r["name"], "type": r["type"] if r["type"] in PLACE_TYPES else "other",
                 "lat": r["lat"], "lng": r["lng"],
                 "space_left": None if r["capacity"] is None else max(0, r["capacity"] - (r["occupancy"] or 0))}
                for r in chosen]

    def _valid_until(self, text: str | None, old: dict, now: datetime, cancel: bool) -> datetime:
        if text:
            try:
                until = timeutil.parse(text)
            except ValueError as exc:
                raise ValueError("valid_until is not a date") from exc
        elif cancel:
            until = now + timedelta(hours=self.rules["all_clear_valid_hours"])
        elif old:
            until = timeutil.parse(old["valid_until"])
        else:
            until = now + timedelta(hours=self.rules["default_valid_hours"])
        if until <= now:
            raise ValueError("valid_until must be in the future")
        if until > now + timedelta(hours=self.rules["max_valid_hours"]):
            raise ValueError(f"valid_until can be at most {self.rules['max_valid_hours']} hours ahead")
        return until

    # ---- helpers ------------------------------------------------------------------------------------------
    def _centre(self, zones: list[str]) -> tuple[float, float] | None:
        points = [centroid(g) for g in (self.zone_map.geometry(z) for z in zones) if g]
        if not points:
            return None
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))

    def _area(self, zones: list[str]) -> str:
        """The geohash outside the packet: about a 5 km box around the alert's zones."""
        centre = self._centre(zones)
        return geohash(*centre, 5) if centre else "0"

    @staticmethod
    def _next_id(conn: sqlite3.Connection) -> str:
        numbers = [int(m.group(1)) for (alert_id,) in conn.execute("SELECT id FROM alerts")
                   if (m := re.fullmatch(r"A-(\d+)", alert_id))]
        return f"A-{max(numbers, default=0) + 1:04d}"

    @staticmethod
    def _root(conn: sqlite3.Connection, alert_id: str) -> str:
        seen = set()
        while alert_id not in seen:
            seen.add(alert_id)
            row = conn.execute("SELECT replaces FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None or not row[0]:
                break
            alert_id = row[0]
        return alert_id

    @staticmethod
    def _chain(by_id: dict[str, dict], alert_id: str) -> list[str]:
        chain = [alert_id]
        while by_id.get(chain[-1], {}).get("replaces") in by_id and by_id[chain[-1]]["replaces"] not in chain:
            chain.append(by_id[chain[-1]]["replaces"])
        return chain

    @staticmethod
    def _status(row: dict, now: datetime) -> str:
        """active | all_clear (an all-clear still in force) | replaced | cancelled | expired"""
        if row["ended_why"]:
            return row["ended_why"]
        if timeutil.parse(row["valid_until"]) <= now:
            return "expired"
        return "all_clear" if json.loads(row["body"]).get("cancel") else "active"

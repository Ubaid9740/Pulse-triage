"""Warning coverage and the opt-in registry (System Design 9.5; Team Brief 3.2 step 4).

A registered vulnerable person is confirmed when they reply to an alert, a helper does a
welfare check on them, or a report names them (registry_id). Confirmations count for a zone
from the earliest active alert covering it; with no active alert, any confirmation counts.

Warning coverage = confirmed / registered, per zone. When an alert has been out longer than
coverage_timeout_minutes[severity] (emergency 30 min, warning 2 h), everyone in its zones who
is still unconfirmed becomes an "unconfirmed" case (source "silence", confidence 0.3).

An update replaces an alert but keeps its clock: for each zone, waiting and confirmations count
from the first alert in the chain that covered that zone. The alerts table is written by
alerts.py; its body column holds the alert payload (payloads/alert.schema.json).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timedelta

from . import timeutil
from .cases import CaseBook
from .db import Database, setting
from .profiles import Profiles
from .zones import ZoneMap

REGISTRY_COLUMNS = ("id", "name", "zone", "lat", "lng", "conditions", "phone", "consent_at")
REQUIRED_COLUMNS = ("id", "name", "conditions", "consent_at")
MEDICAL = {"oxygen", "dialysis", "insulin", "power_dependent"}
MAX_REGISTRY_BYTES = 2_000_000


def priority(conditions: list[str]) -> str:
    """Outreach order: medical needs first, then people who live alone, then everyone else."""
    if MEDICAL & set(conditions):
        return "medical"
    return "alone" if "alone" in conditions else "other"


_PRIORITY_ORDER = {"medical": 0, "alone": 1, "other": 2}


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class Coverage:
    def __init__(self, db: Database, cases: CaseBook, zone_map: ZoneMap, profiles: Profiles, constants: dict):
        self.db = db
        self.cases = cases
        self.zone_map = zone_map
        self.profiles = profiles
        self.timeouts_min = constants["coverage_timeout_minutes"]

    # ---- alerts ------------------------------------------------------------------------------
    @staticmethod
    def active_alerts(conn: sqlite3.Connection, now: datetime) -> list[dict]:
        """Alerts not replaced, not cancelled (all-clear) and not past valid_until. Each carries
        root_id (the first alert of its update chain) and since (zone -> when the chain first
        covered it)."""
        rows = _rows(conn, "SELECT * FROM alerts ORDER BY issued_at")
        by_id = {r["id"]: dict(r, zones=json.loads(r["zones"] or "[]")) for r in rows}
        replaced = {r["replaces"] for r in rows if r["replaces"]}
        out = []
        for a in by_id.values():
            body = json.loads(a["body"] or "{}")
            if a["id"] in replaced or body.get("cancel"):
                continue
            if a["valid_until"] and timeutil.parse(a["valid_until"]) <= now:
                continue
            chain, seen = [a], {a["id"]}
            while chain[-1]["replaces"] in by_id and chain[-1]["replaces"] not in seen:
                chain.append(by_id[chain[-1]["replaces"]])
                seen.add(chain[-1]["id"])
            since = {zone: min(c["issued_at"] for c in chain if zone in c["zones"]) for zone in a["zones"]}
            out.append(dict(a, root_id=chain[-1]["id"], since=since))
        return out

    @staticmethod
    def window_starts(alerts: list[dict]) -> dict[str, str]:
        """Zone -> when the earliest active alert chain covering it started."""
        starts: dict[str, str] = {}
        for a in alerts:
            for zone, since in a["since"].items():
                starts[zone] = min(starts.get(zone, since), since)
        return starts

    @staticmethod
    def _confirmed(person: dict, start: str | None) -> bool:
        if not person["confirmed_at"]:
            return False
        return start is None or timeutil.parse(person["confirmed_at"]) >= timeutil.parse(start)

    def zone_counts(self, conn: sqlite3.Connection, alerts: list[dict]) -> dict[str, tuple[int, int]]:
        """Zone -> (registered, confirmed)."""
        starts = self.window_starts(alerts)
        out: dict[str, list[int]] = {}
        for p in _rows(conn, "SELECT zone, confirmed_at FROM registry WHERE zone IS NOT NULL"):
            counts = out.setdefault(p["zone"], [0, 0])
            counts[0] += 1
            counts[1] += self._confirmed(p, starts.get(p["zone"]))
        return {zone: (n, c) for zone, (n, c) in out.items()}

    def unconfirmed(self, conn: sqlite3.Connection, now: datetime, zone: str | None = None) -> list[dict]:
        """The outreach list: unconfirmed registered people, highest risk first."""
        starts = self.window_starts(self.active_alerts(conn, now))
        where, params = ("WHERE zone = ?", (zone,)) if zone else ("", ())
        out = []
        for p in _rows(conn, f"SELECT * FROM registry {where}", params):
            if self._confirmed(p, starts.get(p["zone"])):
                continue
            conditions = json.loads(p["conditions"] or "[]")
            out.append({"id": p["id"], "name": p["name"], "zone": p["zone"], "conditions": conditions,
                        "phone": p["phone"], "lat": p["lat"], "lng": p["lng"], "confirmed_at": p["confirmed_at"],
                        "priority": priority(conditions)})
        out.sort(key=lambda p: (_PRIORITY_ORDER[p["priority"]], -len(p["conditions"]), p["id"]))
        return out

    def summary(self, now: datetime | None = None) -> dict:
        """GET /api/coverage: coverage per zone, overall, the outreach list and when timeouts fall."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            alerts = self.active_alerts(conn, now)
            counts = self.zone_counts(conn, alerts)
            waiting = self.unconfirmed(conn, now)
        zones = [{"name": name, "registered": n, "confirmed": c, "coverage": round(c / n, 2)}
                 for name, (n, c) in sorted(counts.items())]
        registered = sum(z["registered"] for z in zones)
        confirmed = sum(z["confirmed"] for z in zones)
        return {
            "zones": zones,
            "overall": {"registered": registered, "confirmed": confirmed,
                        "coverage": round(confirmed / registered, 2) if registered else None},
            "alerts": [{"id": a["id"], "hazard": a["hazard"], "severity": a["severity"], "zones": a["zones"],
                        "issued_at": a["issued_at"], "timeout_at": self.timeout_at(a)} for a in alerts],
            "unconfirmed": waiting,
        }

    def timeout_at(self, alert: dict) -> str | None:
        """When the first of the alert's zones runs out of waiting time."""
        wait = self.timeouts_min.get(alert["severity"])
        if wait is None or not alert["since"]:
            return None
        return timeutil.iso(timeutil.parse(min(alert["since"].values())) + timedelta(minutes=wait))

    # ---- the registry --------------------------------------------------------------------------
    def import_registry(self, text: str, by: str, now: datetime | None = None) -> dict:
        """Add or update people from a CSV file (columns: REGISTRY_COLUMNS; conditions separated
        by ';'). Confirmations already recorded are kept. Rows without consent are skipped."""
        now = now or timeutil.now()
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        header = [h.strip() for h in reader.fieldnames or []]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"registry CSV needs the columns {', '.join(REQUIRED_COLUMNS)}; missing "
                             f"{', '.join(missing)}")
        known = set(self.profiles.conditions)
        people, skipped, seen = [], [], set()
        for line, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
            problem, person = self._registry_row(row, known, seen)
            if problem:
                skipped.append({"line": line, "id": row.get("id") or None, "reason": problem})
            else:
                seen.add(person["id"])
                people.append(person)
        added = updated = 0
        with self.db.write() as conn:
            for p in people:
                exists = conn.execute("SELECT 1 FROM registry WHERE id = ?", (p["id"],)).fetchone()
                conn.execute(
                    "INSERT INTO registry(id, name, zone, lat, lng, conditions, phone, consent_at) "
                    "VALUES(:id, :name, :zone, :lat, :lng, :conditions, :phone, :consent_at) "
                    "ON CONFLICT(id) DO UPDATE SET name = excluded.name, zone = excluded.zone, lat = excluded.lat, "
                    "lng = excluded.lng, conditions = excluded.conditions, phone = excluded.phone, "
                    "consent_at = excluded.consent_at", p)
                updated += bool(exists)
                added += not exists
            self.cases.audit(conn, now, by, "registry_import", "registry",
                             f"{added} added, {updated} updated, {len(skipped)} skipped")
            total = conn.execute("SELECT COUNT(*) FROM registry").fetchone()[0]
        return {"added": added, "updated": updated, "skipped": skipped, "total": total}

    def _registry_row(self, row: dict, known: set[str], seen: set[str]) -> tuple[str | None, dict | None]:
        pid = row.get("id", "")
        if not pid:
            return "missing id", None
        if pid in seen:
            return "the same id appears twice", None
        if not row.get("name"):
            return "missing name", None
        if not row.get("consent_at"):
            return "no consent_at: the registry is opt-in", None
        try:
            timeutil.parse(row["consent_at"])
        except ValueError:
            return "consent_at is not a date", None
        conditions = [c.strip() for c in re.split(r"[;|]", row.get("conditions", "")) if c.strip()]
        unknown = [c for c in conditions if c not in known]
        if unknown:
            return f"unknown condition {unknown[0]!r}", None
        lat = lng = None
        if row.get("lat") or row.get("lng"):
            try:
                lat, lng = float(row["lat"]), float(row["lng"])
            except (KeyError, ValueError):
                return "lat and lng must both be numbers", None
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return "lat or lng out of range", None
        zone = self.zone_map.locate(lat, lng) or row.get("zone") or None
        return None, {"id": pid, "name": row["name"], "zone": zone, "lat": lat, "lng": lng,
                      "conditions": json.dumps(list(dict.fromkeys(conditions))), "phone": row.get("phone") or None,
                      "consent_at": row["consent_at"]}

    # ---- confirmations (called inside the ingest transaction) -------------------------------------
    def confirm(self, conn: sqlite3.Connection, registry_id: str | None, at: datetime, by: str) -> bool:
        """Record that a registered person was reached. False when the ID is not in the registry."""
        if not registry_id:
            return False
        cur = conn.execute("UPDATE registry SET confirmed_at = ?, confirmed_by = ? WHERE id = ? "
                           "AND (confirmed_at IS NULL OR confirmed_at < ?)",
                           (timeutil.iso(at), by, registry_id, timeutil.iso(at)))
        return bool(cur.rowcount) or bool(
            conn.execute("SELECT 1 FROM registry WHERE id = ?", (registry_id,)).fetchone())

    def record_reply(self, conn: sqlite3.Connection, body: dict, payload: dict, created: datetime,
                     now: datetime) -> None:
        """'I'm safe', 'I need help' or 'I'm helping' on an alert."""
        device = body["from_device"]
        conn.execute("INSERT OR IGNORE INTO alert_replies(id, alert_id, device_id, registry_id, status, lat, lng, at) "
                     "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                     (body["id"], payload["alert_id"], device, payload.get("registry_id"), payload["status"],
                      payload.get("lat"), payload.get("lng"), timeutil.iso(created)))
        rid = payload.get("registry_id")
        if self.confirm(conn, rid, created, f"alert_reply from {device}") and payload["status"] == "safe":
            self.cases.close_unconfirmed(conn, rid, now, device, f"alert reply: safe ({payload['alert_id']})")

    def record_check(self, conn: sqlite3.Connection, body: dict, payload: dict, created: datetime,
                     now: datetime) -> int | None:
        """A helper checked on someone. 'needs_help' becomes a report at once, so the person is
        ranked even before the helper's full report arrives. Returns that report's case ID."""
        device, result = body["from_device"], payload["result"]
        rid = payload.get("registry_id")
        person = None
        if rid:
            row = conn.execute("SELECT * FROM registry WHERE id = ?", (rid,)).fetchone()
            person = dict(row) if row else None
        open_case = self.cases.open_case_of(conn, rid) if person else None
        if open_case is not None:
            self.cases.audit(conn, now, device, "welfare_check", f"case:{open_case}",
                             result + (f": {payload['note']}" if payload.get("note") else ""))
        if person and result in ("safe", "needs_help"):
            self.confirm(conn, rid, created, f"welfare_check from {device}")
        if person and result == "safe":
            self.cases.close_unconfirmed(conn, rid, now, device, "welfare check: safe")
        if result != "needs_help":
            return None
        hazard = (conn.execute("SELECT hazard FROM cases WHERE id = ?", (open_case,)).fetchone()[0]
                  if open_case is not None else setting(conn, "active_hazard", "flood"))
        located = payload.get("lat") is not None and payload.get("lng") is not None
        return self.cases.add_report(conn, {
            "id": body["id"], "packet_id": body["id"], "source": "welfare_check", "hazard": hazard,
            "for_whom": "other", "people": 1,
            "conditions": json.loads(person["conditions"] or "[]") if person else [], "details": {},
            "note": payload.get("note") or "Welfare check: needs help",
            "lat": payload["lat"] if located else (person or {}).get("lat"),
            "lng": payload["lng"] if located else (person or {}).get("lng"),
            "landmark": payload.get("landmark"), "device_id": device, "reporter_role": "volunteer",
            "reader": "form", "reader_conf": 1.0, "created_at": timeutil.iso(created),
            "received_at": timeutil.iso(now), "registry_id": rid if person else None,
            "zone": None if located or not person else person["zone"]}, now)

    # ---- the scheduler ---------------------------------------------------------------------------
    def timeouts(self, now: datetime | None = None) -> int:
        """Unconfirmed registered people in an alert's zones become cases once its wait has passed.
        Returns how many cases were made."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            due = []
            for a in self.active_alerts(conn, now):
                wait = self.timeouts_min.get(a["severity"])
                if wait is None:
                    continue
                zones = [z for z, since in a["since"].items()
                         if now - timeutil.parse(since) >= timedelta(minutes=wait)]
                if zones:
                    due.append((a, wait, zones))
        if not due:
            return 0
        made = 0
        with self.db.write() as conn:
            for alert, wait, zones in due:
                people = _rows(conn, f"SELECT * FROM registry WHERE zone IN ({','.join('?' * len(zones))})",
                               tuple(zones))
                for p in people:
                    if self._confirmed(p, alert["since"][p["zone"]]):
                        continue
                    made += self.cases.ensure_unconfirmed(conn, p, alert, wait, now) is not None
        return made

"""Cases: store reports, attach them to cases, rebuild a case from its reports, rescore, verify, split.

The reports table is the source of truth. A case is always rebuilt from all of its reports,
so merging, splitting and trusting a device can never leave a case out of step with what
people actually said. Every merge, split, verify and trust change goes into audit_log.

Besides reports from people, the server makes two kinds itself: "silence" (a registered person
who has not confirmed an alert in time) and "zone_task" (a welfare-check sweep of a Silent Zone).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import merge, scoring, timeutil
from .db import Database, setting
from .outbound import COMMAND_POST
from .profiles import Profiles
from .scoring import SYSTEM_SOURCES, SYSTEM_SQL

if TYPE_CHECKING:
    from .zones import ZoneMap

OPEN_STATUSES = ("new", "verified", "assigned", "en_route", "on_scene")
OPEN_SQL = f"status IN ({','.join('?' * len(OPEN_STATUSES))})"

REPORT_COLUMNS = ("id", "packet_id", "source", "hazard", "for_whom", "people", "conditions", "details", "note",
                  "lat", "lng", "accuracy_m", "landmark", "device_id", "reporter_role", "reader", "reader_conf",
                  "created_at", "received_at", "registry_id", "zone")


class NotFound(LookupError):
    """An unknown case, report, device or zone. The API answers 404."""


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def hours_left(row: dict, now: datetime) -> float | None:
    if row["hours_at_report"] is None:
        return None
    ref = timeutil.parse(row.get("hours_ref_at") or row["reported_at"])
    return round(max(0.0, row["hours_at_report"] - timeutil.hours_between(ref, now)), 2)


def case_view(row: dict, now: datetime) -> dict:
    """A cases row as the dashboard sees it (case.schema.json)."""
    return {
        "id": row["id"],
        "hazard": row["hazard"],
        "status": row["status"],
        "zone": row["zone"],
        "lat": row["lat"],
        "lng": row["lng"],
        "accuracy_m": row["accuracy_m"],
        "landmark": row["landmark"],
        "people": row["people"],
        "conditions": json.loads(row["conditions"]),
        "details": json.loads(row["details"]),
        "hours_left": hours_left(row, now),
        "window_closes_at": row["window_closes_at"],
        "points": int(round(row["points"] or 0)),
        "reasons": json.loads(row["reasons"] or "[]"),
        "confidence": row["confidence"],
        "needs": json.loads(row["needs"] or "[]"),
        "badges": json.loads(row["badges"] or "[]"),
        "team_id": row["team_id"],
        "shelter_id": row["shelter_id"],
        "report_count": row["report_count"],
        "source": row["source"],
        "reader": row["reader"],
        "note": row["note"],
        "reported_at": row["reported_at"],
        "last_update": row["last_update"],
    }


def rank_key(view: dict) -> tuple:
    """The ranked list: most points first; ties go to less time left, then the older report."""
    return (-view["points"], view["hours_left"] if view["hours_left"] is not None else 99, view["reported_at"])


def report_view(r: dict) -> dict:
    return {k: r[k] for k in (
        "id", "source", "device_id", "reporter_role", "reader", "hazard", "people", "conditions", "details",
        "note", "lat", "lng", "accuracy_m", "landmark", "zone", "registry_id", "created_at", "received_at")} | {
        "trusted": bool(r["trusted"])}


def _wait_text(minutes: float) -> str:
    return f"{minutes / 60:g} h" if minutes >= 60 else f"{minutes:g} min"


class CaseBook:
    def __init__(self, db: Database, profiles: Profiles, constants: dict, zone_map: "ZoneMap | None" = None):
        self.db = db
        self.profiles = profiles
        self.constants = constants
        self.zone_map = zone_map

    # ---- reports in (called inside the caller's transaction) --------------------------------
    def add_report(self, conn: sqlite3.Connection, report: dict, now: datetime, merge: bool = True) -> int:
        """Store a report (REPORT_COLUMNS; conditions and details as Python values), place it in
        its zone and put it into a case. merge=False always starts a new case. Returns the case ID."""
        row = {k: report.get(k) for k in REPORT_COLUMNS}
        row["packet_id"] = row["packet_id"] or None
        row["conditions"] = json.dumps(list(row["conditions"] or []))
        row["details"] = json.dumps(row["details"] or {})
        if row["zone"] is None and self.zone_map is not None:
            row["zone"] = self.zone_map.locate(row["lat"], row["lng"])
        conn.execute(f"INSERT INTO reports({', '.join(REPORT_COLUMNS)}, case_id) "
                     f"VALUES({', '.join('?' * len(REPORT_COLUMNS))}, NULL)", tuple(row.values()))
        return self.attach_report(conn, row["id"], now, merge=merge)

    def attach_report(self, conn: sqlite3.Connection, report_id: str, now: datetime, merge: bool = True) -> int:
        """Put a stored report into the best matching open case, or a new one. Returns the case ID.
        A report about a registered person joins that person's open case first."""
        report = self._reports(conn, "r.id = ?", (report_id,))[0]
        found: tuple[int, str] | None = None
        if merge and report["registry_id"]:
            case_id = self.open_case_of(conn, report["registry_id"])
            if case_id is not None:
                found = (case_id, f"report {report_id} from {report['device_id']}, "
                                  f"same registered person {report['registry_id']}")
        if merge and found is None:
            best = self._closest_case(conn, report)
            if best is not None:
                found = (best[1], f"report {report_id} from {report['device_id']}, {best[0]:.0f} m away")
        if found is None:
            case_id = self._new_case(conn, report)
            self.audit(conn, now, "server", "new_case", f"case:{case_id}", f"report {report_id}")
        else:
            case_id = found[0]
            self.audit(conn, now, "server", "merge", f"case:{case_id}", found[1])
        conn.execute("UPDATE reports SET case_id = ? WHERE id = ?", (case_id, report_id))
        self.rebuild(conn, case_id, now)
        return case_id

    def ensure_unconfirmed(self, conn: sqlite3.Connection, person: dict, alert: dict, wait_minutes: float,
                           now: datetime) -> int | None:
        """A registered person who has not confirmed the alert in time becomes a case (once per
        alert and its updates, and not while they already have an open case). Returns the case ID."""
        report_id = f"unconfirmed:{alert.get('root_id', alert['id'])}:{person['id']}"
        if conn.execute("SELECT 1 FROM reports WHERE id = ?", (report_id,)).fetchone():
            return None
        if self.open_case_of(conn, person["id"]) is not None:
            return None
        at = timeutil.iso(now)
        case_id = self.add_report(conn, {
            "id": report_id, "source": "silence", "hazard": alert["hazard"], "for_whom": "other", "people": 1,
            "conditions": json.loads(person["conditions"] or "[]"), "details": {},
            "note": f"Registered, not confirmed {_wait_text(wait_minutes)} after alert {alert['id']}",
            "lat": person["lat"], "lng": person["lng"], "device_id": COMMAND_POST, "reporter_role": "system",
            "reader": "system", "created_at": at, "received_at": at, "registry_id": person["id"],
            "zone": person["zone"]}, now, merge=False)
        self.audit(conn, now, "server", "unconfirmed", f"case:{case_id}",
                   f"registry {person['id']} after alert {alert['id']}")
        return case_id

    def close_unconfirmed(self, conn: sqlite3.Connection, registry_id: str, now: datetime, by: str,
                          why: str) -> list[int]:
        """The person was reached and is safe: close their open cases that only the server made."""
        closed = []
        for row in _rows(conn, f"SELECT DISTINCT c.id FROM cases c JOIN reports r ON r.case_id = c.id "
                               f"WHERE r.registry_id = ? AND r.source = 'silence' AND c.{OPEN_SQL}",
                         (registry_id,) + OPEN_STATUSES):
            real = conn.execute(f"SELECT COUNT(*) FROM reports WHERE case_id = ? AND source NOT IN {SYSTEM_SQL}",
                                (row["id"],)).fetchone()[0]
            if not real:
                conn.execute("UPDATE cases SET status = 'closed' WHERE id = ?", (row["id"],))
                self.audit(conn, now, by, "close", f"case:{row['id']}", why)
                closed.append(row["id"])
        return closed

    @staticmethod
    def open_case_of(conn: sqlite3.Connection, registry_id: str) -> int | None:
        row = conn.execute(f"SELECT c.id FROM cases c JOIN reports r ON r.case_id = c.id "
                           f"WHERE r.registry_id = ? AND c.source != 'zone_task' AND c.{OPEN_SQL} "
                           "ORDER BY c.id LIMIT 1", (registry_id,) + OPEN_STATUSES).fetchone()
        return row[0] if row else None

    def relocate(self, conn: sqlite3.Connection, now: datetime) -> int:
        """New zone shapes: put every located report in its zone and refresh the open cases."""
        located = 0
        for r in _rows(conn, "SELECT id, lat, lng FROM reports WHERE lat IS NOT NULL AND lng IS NOT NULL "
                             "AND source != 'zone_task'"):
            zone = self.zone_map.locate(r["lat"], r["lng"])
            located += zone is not None
            conn.execute("UPDATE reports SET zone = ? WHERE id = ?", (zone, r["id"]))
        for row in _rows(conn, f"SELECT id FROM cases WHERE {OPEN_SQL}", OPEN_STATUSES):
            self.rebuild(conn, row["id"], now)
        return located

    # ---- rebuilding and scoring --------------------------------------------------------------
    def rebuild(self, conn: sqlite3.Connection, case_id: int, now: datetime) -> None:
        """Fold every report of the case, oldest first, into the case row, then rescore."""
        reports = self._reports(conn, "r.case_id = ?", (case_id,))
        if not reports:
            return
        real = [r for r in reports if r["source"] not in SYSTEM_SOURCES]
        lead = (real or reports)[0]
        zone_task = lead["source"] == "zone_task"
        hazard = next((r["hazard"] for r in reports if r["hazard"] != "other"), "other")
        conditions: list[str] = []
        details: dict = {}
        hours = ref = text = None
        for r in reports:
            conditions += [c for c in r["conditions"] if c not in conditions]
            details.update(r["details"])               # newer answers win
            if zone_task:
                continue
            at = timeutil.parse(r["created_at"])
            h, t = self.profiles.hours_to_critical(hazard, details, conditions)
            if ref is None:
                hours, ref, text = h, at, t
                continue
            # Each report is judged from its own time. The clock keeps running on the
            # earlier estimate unless the new one is more urgent.
            remaining = max(0.0, hours - timeutil.hours_between(ref, at))
            if h < remaining:
                hours, ref, text = h, at, t
            else:
                hours, ref = remaining, at
        located = [r for r in reports if r["lat"] is not None and r["lng"] is not None]
        best = min(located, key=lambda r: r["accuracy_m"] if r["accuracy_m"] is not None else 1e9) if located else {}
        needs = ["welfare"] if zone_task else self.profiles.needs(hazard, details, conditions)
        conn.execute(
            "UPDATE cases SET hazard = ?, zone = ?, lat = ?, lng = ?, accuracy_m = ?, landmark = ?, people = ?, "
            "conditions = ?, details = ?, hours_at_report = ?, hours_ref_at = ?, hours_text = ?, reported_at = ?, "
            "needs = ?, source = ?, reader = ?, report_count = ?, note = ?, last_update = ? WHERE id = ?",
            (hazard, best.get("zone") or next((r["zone"] for r in reports if r["zone"]), None),
             best.get("lat"), best.get("lng"), best.get("accuracy_m"),
             next((r["landmark"] for r in reports if r["landmark"]), None),
             max(r["people"] for r in reports), json.dumps(conditions), json.dumps(details),
             hours, timeutil.iso(ref) if ref else None, text, reports[0]["created_at"], json.dumps(needs),
             lead["source"], lead["reader"], len(real) or len(reports),
             next((r["note"] for r in reversed(reports) if r["note"]), None),
             max(r["created_at"] for r in reports), case_id))
        self.rescore(conn, case_id, now, reports)

    def rescore(self, conn: sqlite3.Connection, case_id: int, now: datetime,
                reports: list[dict] | None = None) -> scoring.Score:
        """Points from the rules (with the weights in force), then the dispatcher's override, if any."""
        case = self._case(conn, case_id)
        if case["source"] == "zone_task":
            registered = conn.execute("SELECT COUNT(*) FROM registry WHERE zone = ?", (case["zone"],)).fetchone()[0]
            points, reasons = scoring.zone_task_score(case["zone"], registered, self.constants["silent"])
            result = scoring.Score(points, reasons, 1.0, ["zone task"], None)
        else:
            if reports is None:
                reports = self._reports(conn, "r.case_id = ?", (case_id,))
            result = scoring.score(self._state(case, reports), now, self.rules(conn))
        override = json.loads(case["override"]) if case["override"] else None
        if override and override.get("points") is not None:
            result.reasons.append({"text": f"Changed by dispatcher: {override['reason']} (rules gave {result.points})",
                                   "points": override["points"], "kind": "override"})
            result.points = override["points"]
            result.badges.append("override")
        conn.execute("UPDATE cases SET points = ?, reasons = ?, confidence = ?, badges = ? WHERE id = ?",
                     (result.points, json.dumps(result.reasons), result.confidence, json.dumps(result.badges),
                      case_id))
        return result

    def rescore_all(self, now: datetime | None = None) -> int:
        """Hours left shrink and confidence decays with time, so the scheduler calls this."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            by_case: dict[int, list[dict]] = {}
            for r in self._reports(conn, f"r.case_id IN (SELECT id FROM cases WHERE {OPEN_SQL})", OPEN_STATUSES):
                by_case.setdefault(r["case_id"], []).append(r)
            for case_id, reports in by_case.items():
                self.rescore(conn, case_id, now, reports)
            conn.execute("INSERT INTO settings(key, value) VALUES('scheduler_last_run', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(timeutil.iso(now)),))
        return len(by_case)

    def rules(self, conn: sqlite3.Connection) -> dict:
        """The constants, with the weights the dispatcher set (POST /api/settings/weights)."""
        weights = setting(conn, "weights")
        if not weights:
            return self.constants
        points = dict(self.constants["points"], weights=dict(self.constants["points"]["weights"], **weights))
        return dict(self.constants, points=points)

    def weights(self) -> dict:
        with self.db.read() as conn:
            current = self.rules(conn)["points"]["weights"]
        return {"weights": current, "defaults": self.constants["points"]["weights"]}

    def set_weights(self, weights: dict, reset: bool, by: str, now: datetime | None = None) -> dict:
        """Tune the points (the weights panel). Every open case is rescored at once."""
        now = now or timeutil.now()
        defaults = self.constants["points"]["weights"]
        unknown = sorted(set(weights) - set(defaults))
        if unknown:
            raise ValueError(f"unknown weights: {', '.join(unknown)} (known: {', '.join(defaults)})")
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 200 for v in weights.values()):
            raise ValueError("weights are numbers from 0 to 200")
        with self.db.write() as conn:
            current = {} if reset else dict(setting(conn, "weights") or {})
            current.update(weights)
            conn.execute("INSERT INTO settings(key, value) VALUES('weights', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(current),))
            self.audit(conn, now, by, "weights", "settings", "reset to defaults" if reset and not weights
                       else json.dumps(current))
        return dict(self.weights(), cases_rescored=self.rescore_all(now))

    def override(self, case_id: int, points: int | None, status: str | None, reason: str, by: str,
                 now: datetime | None = None) -> dict:
        """The dispatcher changes a case's points or status, with a reason. The rules' points stay on
        the card ("rules gave 69") and in the audit log. points None clears a points override."""
        now = now or timeutil.now()
        if not reason or not reason.strip():
            raise ValueError("an override needs a reason")
        with self.db.write() as conn:
            case = self._case(conn, case_id)
            before = {"points": case["points"], "status": case["status"]}
            if status is not None:
                if status not in ("new", "verified", "closed", "done"):
                    raise ValueError("status can be set to new, verified, closed or done; teams move the rest")
                if case["team_id"] and case["status"] in ("assigned", "en_route", "on_scene"):
                    raise ValueError(f"team {case['team_id']} is on this case; change the team's status first")
                conn.execute("UPDATE cases SET status = ? WHERE id = ?", (status, case_id))
            if points is not None or status is None:
                value = None if points is None else {"points": int(points), "reason": reason.strip(), "by": by,
                                                     "at": timeutil.iso(now)}
                conn.execute("UPDATE cases SET override = ? WHERE id = ?", (json.dumps(value) if value else None, case_id))
            self.rescore(conn, case_id, now)
            after = self._case(conn, case_id)
            self.audit(conn, now, by, "override", f"case:{case_id}",
                       json.dumps({"reason": reason.strip(), "before": before,
                                   "after": {"points": after["points"], "status": after["status"]}}))
        return self.detail(case_id, now)

    # ---- dispatcher actions --------------------------------------------------------------------
    def verify(self, case_id: int, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        with self.db.write() as conn:
            self._case(conn, case_id)
            conn.execute("UPDATE cases SET verified = 1, status = CASE WHEN status = 'new' THEN 'verified' "
                         "ELSE status END WHERE id = ?", (case_id,))
            self.audit(conn, now, by, "verify", f"case:{case_id}", "")
            self.rescore(conn, case_id, now)
        return self.detail(case_id, now)

    def split(self, case_id: int, report_id: str, by: str, now: datetime | None = None) -> dict:
        """Undo a wrong merge: the report leaves the case and starts its own."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            self._case(conn, case_id)
            reports = self._reports(conn, "r.case_id = ?", (case_id,))
            report = next((r for r in reports if r["id"] == report_id), None)
            if report is None:
                raise NotFound(f"report {report_id} is not in case {case_id}")
            if len(reports) < 2:
                raise ValueError("a case with one report cannot be split")
            new_id = self._new_case(conn, report)
            conn.execute("UPDATE reports SET case_id = ? WHERE id = ?", (new_id, report_id))
            self.rebuild(conn, case_id, now)
            self.rebuild(conn, new_id, now)
            self.audit(conn, now, by, "split", f"case:{case_id}", f"report {report_id} moved to case {new_id}")
            self.audit(conn, now, by, "split_from", f"case:{new_id}", f"report {report_id} from case {case_id}")
        return {"case_id": case_id, "new_case_id": new_id}

    def set_trusted(self, device_id: str, trusted: bool, by: str, now: datetime | None = None) -> int:
        """Mark a phone as a known helper or team. Rescores its open cases; returns how many."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone():
                raise NotFound(f"unknown device {device_id}")
            conn.execute("UPDATE devices SET trusted = ? WHERE id = ?", (int(trusted), device_id))
            self.audit(conn, now, by, "trust" if trusted else "untrust", f"device:{device_id}", "")
            case_ids = [r["case_id"] for r in _rows(
                conn, f"SELECT DISTINCT case_id FROM reports WHERE device_id = ? AND case_id IN "
                      f"(SELECT id FROM cases WHERE {OPEN_SQL})", (device_id,) + OPEN_STATUSES)]
            for case_id in case_ids:
                self.rescore(conn, case_id, now)
        return len(case_ids)

    def detail(self, case_id: int, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        with self.db.read() as conn:
            case = self._case(conn, case_id)
            reports = self._reports(conn, "r.case_id = ?", (case_id,))
            history = _rows(conn, "SELECT at, actor, action, detail FROM audit_log WHERE target = ? ORDER BY id",
                            (f"case:{case_id}",))
        return {"case": case_view(case, now), "reports": [report_view(r) for r in reports], "history": history}

    # ---- helpers ----------------------------------------------------------------------------------
    @staticmethod
    def _case(conn: sqlite3.Connection, case_id: int) -> dict:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise NotFound(f"unknown case {case_id}")
        return dict(row)

    @staticmethod
    def _reports(conn: sqlite3.Connection, where: str, params: tuple) -> list[dict]:
        rows = _rows(conn, "SELECT r.*, COALESCE(d.trusted, 0) AS trusted FROM reports r "
                           f"LEFT JOIN devices d ON d.id = r.device_id WHERE {where} "
                           "ORDER BY r.created_at, r.received_at, r.rowid", params)   # ties: arrival order
        for r in rows:
            r["conditions"] = json.loads(r["conditions"] or "[]")
            r["details"] = json.loads(r["details"] or "{}")
        return rows

    def _closest_case(self, conn: sqlite3.Connection, report: dict) -> tuple[float, int] | None:
        place = self._report_place(report)
        window = timedelta(hours=self.constants["merge"]["window_hours"])
        candidates = _rows(conn, f"SELECT * FROM cases WHERE {OPEN_SQL} AND source != 'zone_task' "
                                 "AND last_update >= ? AND reported_at <= ?",
                           OPEN_STATUSES + (timeutil.iso(place.at - window), timeutil.iso(place.at + window)))
        best: tuple[float, int] | None = None
        for case in candidates:
            metres = merge.match_distance(self._case_place(conn, case), place, self.constants["merge"])
            if metres is not None and (best is None or metres < best[0]):
                best = (metres, case["id"])
        return best

    @staticmethod
    def _new_case(conn: sqlite3.Connection, report: dict) -> int:
        """An empty case; rebuild() fills it from its reports."""
        cur = conn.execute(
            "INSERT INTO cases(hazard, people, conditions, details, reported_at, last_update, status, source, "
            "reader, report_count, verified, points, reasons, confidence, needs, badges) "
            "VALUES(?, ?, '[]', '{}', ?, ?, 'new', ?, ?, 0, 0, 0, '[]', 0, '[]', '[]')",
            (report["hazard"], report["people"], report["created_at"], report["created_at"],
             report["source"], report["reader"]))
        return cur.lastrowid

    @staticmethod
    def _report_place(r: dict) -> merge.Place:
        return merge.Place(hazard=r["hazard"], people=r["people"], at=timeutil.parse(r["created_at"]),
                           lat=r["lat"], lng=r["lng"], landmarks=[r["landmark"]] if r["landmark"] else [],
                           conditions=set(r["conditions"]), words=merge.key_words(r["note"], r["landmark"]))

    def _case_place(self, conn: sqlite3.Connection, case: dict) -> merge.Place:
        # The server's own notes ("Registered, not confirmed ...") say nothing about the place.
        texts = _rows(conn, f"SELECT note, landmark FROM reports WHERE case_id = ? AND source NOT IN {SYSTEM_SQL}",
                      (case["id"],))
        return merge.Place(hazard=case["hazard"], people=case["people"], at=timeutil.parse(case["last_update"]),
                           lat=case["lat"], lng=case["lng"],
                           landmarks=[t["landmark"] for t in texts if t["landmark"]],
                           conditions=set(json.loads(case["conditions"])),
                           words=merge.key_words(*(x for t in texts for x in (t["note"], t["landmark"]))))

    @staticmethod
    def _state(case: dict, reports: list[dict]) -> scoring.CaseState:
        return scoring.CaseState(
            people=case["people"],
            conditions=json.loads(case["conditions"]),
            hours_at_ref=case["hours_at_report"],
            hours_ref_at=timeutil.parse(case["hours_ref_at"] or case["reported_at"]),
            hours_text=case["hours_text"],
            last_update=timeutil.parse(case["last_update"]),
            reports=[scoring.ReportInfo(r["device_id"], r["reporter_role"], r["reader"], r["source"],
                                        timeutil.parse(r["created_at"]), r["lat"], r["lng"], r["accuracy_m"],
                                        bool(r["trusted"])) for r in reports],
            verified=bool(case["verified"]),
            has_location=case["lat"] is not None,
            window_closes_at=timeutil.parse(case["window_closes_at"]) if case["window_closes_at"] else None)

    @staticmethod
    def audit(conn: sqlite3.Connection, now: datetime, actor: str, action: str, target: str, detail: str) -> None:
        conn.execute("INSERT INTO audit_log(at, actor, action, target, detail) VALUES(?, ?, ?, ?, ?)",
                     (timeutil.iso(now), actor, action, target, detail))

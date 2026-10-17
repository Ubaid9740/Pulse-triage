"""Cases: attach reports to cases, rebuild a case from its reports, rescore, verify, split.

The reports table is the source of truth. A case is always rebuilt from all of its reports,
so merging, splitting and trusting a device can never leave a case out of step with what
people actually said. Every merge, split, verify and trust change goes into audit_log.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import merge, scoring, timeutil
from .db import Database
from .profiles import Profiles

OPEN_STATUSES = ("new", "verified", "assigned", "en_route", "on_scene")
_OPEN_SQL = f"status IN ({','.join('?' * len(OPEN_STATUSES))})"


class NotFound(LookupError):
    """An unknown case, report or device. The API answers 404."""


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


def report_view(r: dict) -> dict:
    return {k: r[k] for k in (
        "id", "source", "device_id", "reporter_role", "reader", "hazard", "people", "conditions", "details",
        "note", "lat", "lng", "accuracy_m", "landmark", "created_at", "received_at")} | {"trusted": bool(r["trusted"])}


class CaseBook:
    def __init__(self, db: Database, profiles: Profiles, constants: dict):
        self.db = db
        self.profiles = profiles
        self.constants = constants

    # ---- reports in (called inside the ingest transaction) ---------------------------------
    def attach_report(self, conn: sqlite3.Connection, report_id: str, now: datetime) -> int:
        """Put a stored report into the best matching open case, or a new one. Returns the case ID."""
        report = self._reports(conn, "r.id = ?", (report_id,))[0]
        place = self._report_place(report)
        window = timedelta(hours=self.constants["merge"]["window_hours"])
        candidates = _rows(conn, f"SELECT * FROM cases WHERE {_OPEN_SQL} AND last_update >= ? AND reported_at <= ?",
                           OPEN_STATUSES + (timeutil.iso(place.at - window), timeutil.iso(place.at + window)))
        best: tuple[float, int] | None = None
        for case in candidates:
            metres = merge.match_distance(self._case_place(conn, case), place, self.constants["merge"])
            if metres is not None and (best is None or metres < best[0]):
                best = (metres, case["id"])
        if best is None:
            case_id = self._new_case(conn, report)
            self._audit(conn, now, "server", "new_case", f"case:{case_id}", f"report {report_id}")
        else:
            case_id = best[1]
            self._audit(conn, now, "server", "merge", f"case:{case_id}",
                        f"report {report_id} from {report['device_id']}, {best[0]:.0f} m away")
        conn.execute("UPDATE reports SET case_id = ? WHERE id = ?", (case_id, report_id))
        self.rebuild(conn, case_id, now)
        return case_id

    # ---- rebuilding and scoring --------------------------------------------------------------
    def rebuild(self, conn: sqlite3.Connection, case_id: int, now: datetime) -> None:
        """Fold every report of the case, oldest first, into the case row, then rescore."""
        reports = self._reports(conn, "r.case_id = ?", (case_id,))
        if not reports:
            return
        hazard = next((r["hazard"] for r in reports if r["hazard"] != "other"), "other")
        conditions: list[str] = []
        details: dict = {}
        hours = ref = text = None
        for r in reports:
            conditions += [c for c in r["conditions"] if c not in conditions]
            details.update(r["details"])               # newer answers win
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
        conn.execute(
            "UPDATE cases SET hazard = ?, lat = ?, lng = ?, accuracy_m = ?, landmark = ?, people = ?, conditions = ?, "
            "details = ?, hours_at_report = ?, hours_ref_at = ?, hours_text = ?, reported_at = ?, needs = ?, "
            "source = ?, reader = ?, report_count = ?, note = ?, last_update = ? WHERE id = ?",
            (hazard, best.get("lat"), best.get("lng"), best.get("accuracy_m"),
             next((r["landmark"] for r in reports if r["landmark"]), None),
             max(r["people"] for r in reports), json.dumps(conditions), json.dumps(details),
             hours, timeutil.iso(ref), text, reports[0]["created_at"],
             json.dumps(self.profiles.needs(hazard, details, conditions)),
             reports[0]["source"], reports[0]["reader"], len(reports),
             next((r["note"] for r in reversed(reports) if r["note"]), None),
             max(r["created_at"] for r in reports), case_id))
        self.rescore(conn, case_id, now, reports)

    def rescore(self, conn: sqlite3.Connection, case_id: int, now: datetime,
                reports: list[dict] | None = None) -> scoring.Score:
        case = self._case(conn, case_id)
        if reports is None:
            reports = self._reports(conn, "r.case_id = ?", (case_id,))
        result = scoring.score(self._state(case, reports), now, self.constants)
        conn.execute("UPDATE cases SET points = ?, reasons = ?, confidence = ?, badges = ? WHERE id = ?",
                     (result.points, json.dumps(result.reasons), result.confidence, json.dumps(result.badges),
                      case_id))
        return result

    def rescore_all(self, now: datetime | None = None) -> int:
        """Hours left shrink and confidence decays with time, so the scheduler calls this."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            by_case: dict[int, list[dict]] = {}
            for r in self._reports(conn, f"r.case_id IN (SELECT id FROM cases WHERE {_OPEN_SQL})", OPEN_STATUSES):
                by_case.setdefault(r["case_id"], []).append(r)
            for case_id, reports in by_case.items():
                self.rescore(conn, case_id, now, reports)
            conn.execute("INSERT INTO settings(key, value) VALUES('scheduler_last_run', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(timeutil.iso(now)),))
        return len(by_case)

    # ---- dispatcher actions --------------------------------------------------------------------
    def verify(self, case_id: int, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        with self.db.write() as conn:
            self._case(conn, case_id)
            conn.execute("UPDATE cases SET verified = 1, status = CASE WHEN status = 'new' THEN 'verified' "
                         "ELSE status END WHERE id = ?", (case_id,))
            self._audit(conn, now, by, "verify", f"case:{case_id}", "")
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
            self._audit(conn, now, by, "split", f"case:{case_id}", f"report {report_id} moved to case {new_id}")
            self._audit(conn, now, by, "split_from", f"case:{new_id}", f"report {report_id} from case {case_id}")
        return {"case_id": case_id, "new_case_id": new_id}

    def set_trusted(self, device_id: str, trusted: bool, by: str, now: datetime | None = None) -> int:
        """Mark a phone as a known helper or team. Rescores its open cases; returns how many."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone():
                raise NotFound(f"unknown device {device_id}")
            conn.execute("UPDATE devices SET trusted = ? WHERE id = ?", (int(trusted), device_id))
            self._audit(conn, now, by, "trust" if trusted else "untrust", f"device:{device_id}", "")
            case_ids = [r["case_id"] for r in _rows(
                conn, f"SELECT DISTINCT case_id FROM reports WHERE device_id = ? AND case_id IN "
                      f"(SELECT id FROM cases WHERE {_OPEN_SQL})", (device_id,) + OPEN_STATUSES)]
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
        texts = _rows(conn, "SELECT note, landmark FROM reports WHERE case_id = ?", (case["id"],))
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
    def _audit(conn: sqlite3.Connection, now: datetime, actor: str, action: str, target: str, detail: str) -> None:
        conn.execute("INSERT INTO audit_log(at, actor, action, target, detail) VALUES(?, ?, ?, ?, ?)",
                     (timeutil.iso(now), actor, action, target, detail))

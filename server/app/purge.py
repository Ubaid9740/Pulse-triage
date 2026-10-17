"""Data retention after an incident (System Design 10.4; Team Brief 3.11).

The incident's personal data is deleted; only anonymous counts are kept for the after-action
review, written to a JSON file first.

  deleted   reports, cases, registry, alert replies, team pings and status log, jobs, raw
            packets, devices, supply moves, the audit log and the AI cache; the outbound queue
            keeps one empty row so its sequence carries on
  cleared   on each team: phone, position, battery, job (the team, its type and base stay)
  kept      zones, alerts (public text), places and their head counts, stock levels, settings
            and the command post keys

Counts per zone below purge.min_count show as "<N", so a small zone cannot point at a person.
The database is vacuumed afterwards so deleted rows do not linger in free pages. Backups hold
the same data and are deleted too, unless asked not to.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import timeutil
from .db import Database

DELETED = ("reports", "cases", "registry", "alert_replies", "team_pings", "team_status_log", "jobs", "packets",
           "devices", "supply_moves", "audit_log", "ai_cache")
MIN_COUNT = 5


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _suppress(counts: dict, min_count: int) -> dict:
    """Small numbers in a breakdown become '<min_count'."""
    return {k: (v if v >= min_count else f"<{min_count}") for k, v in sorted(counts.items(), key=lambda kv: str(kv[0]))}


def _minutes(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (timeutil.parse(end) - timeutil.parse(start)).total_seconds() / 60


def after_action(db: Database, min_count: int = MIN_COUNT) -> dict:
    """Anonymous counts of the incident: nothing that names, locates or describes a person."""
    with db.read() as conn:
        reports = _rows(conn, "SELECT source, hazard, reader, created_at FROM reports")
        cases = _rows(conn, "SELECT status, zone, people, report_count, source FROM cases")
        jobs = _rows(conn, "SELECT status, created_at, arrived_at, outcome FROM jobs")
        alerts = _rows(conn, "SELECT severity, body FROM alerts")
        replies = _rows(conn, "SELECT status FROM alert_replies")
        registry = _rows(conn, "SELECT confirmed_at FROM registry")
        used = _rows(conn, "SELECT item, SUM(qty) AS qty FROM supply_moves WHERE reason = 'used' GROUP BY item")
        teams = _rows(conn, "SELECT type FROM teams")
        actions = Counter(r["action"] for r in _rows(conn, "SELECT action FROM audit_log"))
        silent = sorted({r["target"][5:] for r in _rows(conn, "SELECT target FROM audit_log WHERE action = 'silent'")})
    times = sorted(r["created_at"] for r in reports)
    outcomes = [json.loads(j["outcome"]) for j in jobs if j["outcome"]]
    response = [m for m in (_minutes(j["created_at"], j["arrived_at"]) for j in jobs) if m is not None]
    real = [c for c in cases if c["source"] not in ("silence", "zone_task")]
    return {
        "made_at": timeutil.iso(timeutil.now()),
        "incident": {"first_report": times[0] if times else None, "last_report": times[-1] if times else None},
        "reports": {"total": len(reports), "by_source": dict(Counter(r["source"] for r in reports)),
                    "by_hazard": dict(Counter(r["hazard"] for r in reports)),
                    "by_reader": dict(Counter(r["reader"] for r in reports))},
        "cases": {"total": len(cases), "from_reports": len(real),
                  "merged": sum(1 for c in cases if (c["report_count"] or 0) > 1),
                  "unconfirmed_registered": sum(1 for c in cases if c["source"] == "silence"),
                  "zone_tasks": sum(1 for c in cases if c["source"] == "zone_task"),
                  "people": sum(c["people"] or 0 for c in real),
                  "by_status": dict(Counter(c["status"] for c in cases)),
                  "by_zone": _suppress(Counter(c["zone"] or "unknown" for c in real), min_count)},
        "jobs": {"total": len(jobs), "by_status": dict(Counter(j["status"] for j in jobs)),
                 "people_helped": sum(o.get("people_helped") or 0 for o in outcomes),
                 "median_minutes_to_arrive": round(statistics.median(response), 1) if response else None},
        "alerts": {"total": len(alerts), "by_severity": dict(Counter(a["severity"] for a in alerts)),
                   "all_clears": sum(1 for a in alerts if json.loads(a["body"] or "{}").get("cancel")),
                   "replies": dict(Counter(r["status"] for r in replies))},
        "registry": {"registered": len(registry), "confirmed": sum(1 for r in registry if r["confirmed_at"])},
        "zones_that_went_silent": silent,
        "supplies_used": {u["item"]: u["qty"] for u in used},
        "teams_by_type": dict(Counter(t["type"] for t in teams)),
        "dispatcher": {"overrides": actions.get("override", 0), "splits": actions.get("split", 0),
                       "verified": actions.get("verify", 0), "revoked_phones": actions.get("revoke", 0)},
        "small_counts_shown_as": f"<{min_count}",
    }


def planned(db: Database) -> dict:
    """Rows that a purge would delete, per table."""
    with db.read() as conn:
        rows = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in DELETED}
        rows["outbound"] = conn.execute("SELECT COUNT(*) FROM outbound WHERE wire IS NOT NULL").fetchone()[0]
    return rows


def purge(db: Database, report_dir: Path, backups_dir: Path | None, now: datetime | None = None,
          min_count: int = MIN_COUNT) -> dict:
    """Write the after-action counts, then delete. backups_dir None keeps the backups."""
    now = now or timeutil.now()
    summary = after_action(db, min_count)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"after-action-{now.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    deleted = planned(db)
    with db.write() as conn:
        for table in DELETED:
            conn.execute(f"DELETE FROM {table}")
        top = conn.execute("SELECT MAX(seq) FROM outbound").fetchone()[0]
        if top is not None:
            conn.execute("DELETE FROM outbound WHERE seq < ?", (top,))
            conn.execute("UPDATE outbound SET wire = NULL, packet_id = NULL, to_device = NULL WHERE seq = ?", (top,))
        conn.execute("UPDATE teams SET device_id = NULL, lat = base_lat, lng = base_lng, accuracy_m = NULL, "
                     "ping_at = NULL, ping_received_at = NULL, battery = NULL, case_id = NULL, job_id = NULL, "
                     "eta = NULL, flags = '[]', status = 'available', status_since = ?", (timeutil.iso(now),))
        conn.execute("UPDATE zones SET actual = 0, registered = 0, confirmed = 0, silent = 0, quiet = 0, unheard = 0, "
                     "silent_since = NULL")
        conn.execute("INSERT INTO settings(key, value) VALUES('last_purge', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(timeutil.iso(now)),))
    db.vacuum()
    removed = []
    if backups_dir is not None and backups_dir.exists():
        for f in sorted(backups_dir.glob("*.db")):
            f.unlink()
            removed.append(f.name)
    return {"after_action": str(report), "deleted_rows": deleted, "backups_deleted": len(removed)}

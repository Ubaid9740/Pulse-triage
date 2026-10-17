"""GET /api/snapshot: everything the dashboard shows, in one response (snapshot.schema.json).

Cached per database revision and per minute (hours left shrink as time passes).
Sections not built yet return empty lists.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta

from . import timeutil
from .config import Settings
from .db import Database

OPEN_STATUSES = ("new", "verified", "assigned", "en_route", "on_scene")


class SnapshotBuilder:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._cached: dict | None = None

    def get(self) -> dict:
        now = timeutil.now()
        key = (self.db.rev(), now.strftime("%Y%m%d%H%M"))
        with self._lock:
            if key != self._key:
                self._cached = self._build(now, key[0])
                self._key = key
            return self._cached

    def _build(self, now, rev: int) -> dict:
        cases = [self._case(row, now) for row in self.db.all(
            f"SELECT * FROM cases WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})", OPEN_STATUSES)]
        # Until scoring is built, points are 0, so time left decides the order.
        cases.sort(key=lambda c: (-c["points"], c["hours_left"] if c["hours_left"] is not None else 99,
                                  c["reported_at"]))
        five_min_ago = timeutil.iso(now - timedelta(minutes=5))
        return {
            "rev": rev,
            "now": timeutil.iso(now),
            "hazard": self.db.get_setting("active_hazard", "flood"),
            "status": {
                "ai_online": False,
                "packets_last_5_min": self.db.scalar(
                    "SELECT COUNT(*) FROM packets WHERE received_at >= ? AND result = 'accepted'", (five_min_ago,)),
                "require_signatures": self.settings.require_signatures,
                "require_sealing": self.settings.require_sealing,
                "scheduler_last_run": None,
            },
            "alerts": [],
            "summary": {"open_cases": len(cases), "teams": {}, "warnings": []},
            "cases": cases,
            "zones": [],
            "teams": [],
            "shelters": [],
            "supplies": [],
        }

    @staticmethod
    def _case(row: dict, now) -> dict:
        hours_left = None
        if row["hours_at_report"] is not None:
            elapsed = timeutil.hours_between(timeutil.parse(row["reported_at"]), now)
            hours_left = round(max(0.0, row["hours_at_report"] - elapsed), 2)
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
            "hours_left": hours_left,
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

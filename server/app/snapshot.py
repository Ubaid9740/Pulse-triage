"""GET /api/snapshot: everything the dashboard shows, in one response (snapshot.schema.json).

Cached per database revision and per minute (hours left shrink as time passes). Points are
recomputed at ingest and by the scheduler every server.scheduler_s seconds; zones are
recomputed here first when a packet has changed them.
"""
from __future__ import annotations

import threading
from datetime import timedelta

from . import timeutil
from .alerts import AlertBook
from .cases import OPEN_STATUSES, case_view, rank_key
from .config import Settings
from .db import Database
from .supplies import SupplyBook
from .teams import TeamBook
from .zones import ZoneBook


class SnapshotBuilder:
    def __init__(self, db: Database, settings: Settings, zones: ZoneBook, alerts: AlertBook, teams: TeamBook,
                 supplies: SupplyBook):
        self.db = db
        self.settings = settings
        self.zones = zones
        self.alerts = alerts
        self.teams = teams
        self.supplies = supplies
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._cached: dict | None = None

    def get(self) -> dict:
        self.zones.refresh_if_dirty()
        now = timeutil.now()
        key = (self.db.rev(), now.strftime("%Y%m%d%H%M"))
        with self._lock:
            if key != self._key:
                self._cached = self._build(now, key[0])
                self._key = key
            return self._cached

    def _build(self, now, rev: int) -> dict:
        cases = [case_view(row, now) for row in self.db.all(
            f"SELECT * FROM cases WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})", OPEN_STATUSES)]
        cases.sort(key=rank_key)
        five_min_ago = timeutil.iso(now - timedelta(minutes=5))
        zones = self.zones.views()
        teams = self.teams.views(now)
        team_counts, team_warnings = self.teams.summary(teams)
        shelters = self.supplies.shelters()
        supplies = self.supplies.views(now)
        warnings = ([f"Silent Zone: {z['name']}" for z in zones if z["silent"]] + team_warnings
                    + self.supplies.warnings(supplies, shelters))
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
                "scheduler_last_run": self.db.get_setting("scheduler_last_run"),
            },
            "alerts": self.alerts.views(now, current_only=True),
            "summary": {"open_cases": len(cases), "teams": team_counts, "warnings": warnings},
            "cases": cases,
            "zones": zones,
            "teams": teams,
            "shelters": shelters,
            "supplies": supplies,
        }

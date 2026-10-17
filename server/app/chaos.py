"""The chaos panel (System Design 13.4; Team Brief 3.6, demo only): inject the problems a real
incident brings, each through the normal path, so the dashboard reacts exactly as it would.

  duplicate       a second phone reports the top case again, 20 m off   "2 reports" badge
  fake            an unknown phone claims 50 people at the stadium        low trust, "verify" badge
  wrong_location  a phone gives the top case's landmark, GPS 2 km off     a new case (too far to merge) with
                                                                          lower trust and "check location"
  ai_down         the AI reader acts as if the API were unreachable       offline banner, keyword rules
                  (call again with on=false to end it)

Reports are real phone packets: signed with a fresh key (so an unknown phone) and sealed to the
command post, then ingested like any packet from the mesh.
"""
from __future__ import annotations

import json
import math
import secrets
from collections.abc import Callable
from datetime import datetime

from nacl.signing import SigningKey

from . import timeutil
from .ai_reader import AIReader
from .cases import OPEN_SQL, OPEN_STATUSES, NotFound
from .crypto import CommandPostKeys
from .db import Database
from .devtools import phone_wire
from .ingest import Ingestor
from .packets import geohash
from .zones import centroid

KINDS = ("duplicate", "fake", "wrong_location", "ai_down")
FAKE_PEOPLE = 50


def moved(lat: float, lng: float, east_m: float, north_m: float) -> tuple[float, float]:
    """A point east_m metres east and north_m metres north of (lat, lng)."""
    return (round(lat + north_m / 111_320, 6),
            round(lng + east_m / (111_320 * math.cos(math.radians(lat))), 6))


class Chaos:
    def __init__(self, db: Database, keys: CommandPostKeys, ingestor: Ingestor, ai: Callable[[], AIReader]):
        self.db = db
        self.keys = keys
        self.ingestor = ingestor
        self.ai = ai                    # looked up on each call: the app may swap its reader

    def run(self, kind: str, on: bool = True, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        if kind == "ai_down":
            reader = self.ai()
            reader.outage(on)
            return {"kind": kind, "ai": reader.status()}
        if kind == "duplicate":
            case, report = self._top_case()
            lat, lng = moved(report["lat"], report["lng"], 15, 12)
            payload = self._copy(report, lat, lng, note=f"Same here: {report['note'] or report['landmark'] or 'please help'}")
        elif kind == "wrong_location":
            case, report = self._top_case(need_landmark=True)
            lat, lng = moved(report["lat"], report["lng"], 1600, -1200)            # 2 km off
            payload = self._copy(report, lat, lng, note=report["note"])
        elif kind == "fake":
            case = None
            payload = self._fake(now)
        else:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        result = self._send(payload, now)
        if result.status != "accepted":
            raise ValueError(f"the {kind} report was {result.status}: {result.reason or ''} {result.detail}".strip())
        reports = self.db.scalar("SELECT report_count FROM cases WHERE id = ?", (result.case_id,)) or 1
        return {"kind": kind, "report_id": result.id, "case_id": result.case_id, "merged": reports > 1,
                "top_case": case["id"] if case else None}

    # ---- the reports -----------------------------------------------------------------------------------
    def _top_case(self, need_landmark: bool = False) -> tuple[dict, dict]:
        """The open case with the most points that has a phone report with GPS (and a landmark)."""
        rows = self.db.all(
            f"SELECT c.id, c.points, r.* FROM cases c JOIN reports r ON r.case_id = c.id "
            f"WHERE c.{OPEN_SQL} AND r.lat IS NOT NULL AND r.source NOT IN ('silence', 'zone_task') "
            f"{'AND r.landmark IS NOT NULL ' if need_landmark else ''}"
            f"ORDER BY c.points DESC, r.created_at LIMIT 1", OPEN_STATUSES)
        if not rows:
            raise NotFound("no open case with a located report" + (" and a landmark" if need_landmark else ""))
        row = rows[0]
        return {"id": row["case_id"]}, row

    def _copy(self, report: dict, lat: float, lng: float, note: str | None) -> dict:
        payload = {"hazard": report["hazard"], "for_whom": "neighbour", "people": report["people"],
                   "conditions": json.loads(report["conditions"] or "[]"),
                   "details": json.loads(report["details"] or "{}"),
                   "lat": lat, "lng": lng, "gps_accuracy_m": 25, "reporter_role": "helper", "contact": ""}
        if note:
            payload["note"] = note[:500]
        if report["landmark"]:
            payload["landmark"] = report["landmark"]
        return payload

    def _fake(self, now: datetime) -> dict:
        """A big claim from nowhere: the most populous zone's centre, a little off so it never merges."""
        zone = self.db.one("SELECT name, polygon FROM zones ORDER BY hard_hit DESC, population DESC LIMIT 1")
        if zone is None:
            raise NotFound("no zones loaded")
        lat, lng = moved(*centroid(json.loads(zone["polygon"])), 350, 250)
        hazard = self.db.get_setting("active_hazard", "flood")
        return {"hazard": hazard, "for_whom": "other", "people": FAKE_PEOPLE, "conditions": [], "details": {},
                "note": f"{FAKE_PEOPLE} people trapped at the stadium, come now!!", "landmark": "the stadium",
                "lat": lat, "lng": lng, "gps_accuracy_m": 80, "reporter_role": "helper", "contact": ""}

    def _send(self, payload: dict, now: datetime):
        device = f"chaos_{secrets.token_hex(3)}"
        wire = phone_wire("report", payload, device_id=device, signing_key=SigningKey.generate(),
                          box_pk=self.keys.box_pk, urgency=2, area=geohash(payload["lat"], payload["lng"], 5),
                          created=now)
        return self.ingestor.ingest_wire(wire, received_at=now)

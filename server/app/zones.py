"""Zones and Silent Zones (System Design 9.5; Team Brief 4.4 h).

A zone is a named shape of the demo town with a population (scenario/zones.geojson).
A zone is hard-hit when the dispatcher (or the replay) marks it, or, for profiles whose
"affected" is "alert_zones" (heat), when an active alert of that hazard covers it.

For every hard-hit zone:
  rate      median reports per 100 people across the other hard-hit zones (default if none)
  expected  population / 100 x rate
  quiet     expected >= silent.min_expected and actual / expected < silent.ratio
  unheard   an alert covers it, registered >= silent.min_registered and confirmed / registered < silent.coverage
  silent    quiet or unheard
Actual counts the reports placed in the zone, not cases the server made itself.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from . import timeutil
from .cases import OPEN_SQL, OPEN_STATUSES, CaseBook, NotFound
from .db import Database, setting
from .profiles import Profiles
from .schemas import Schemas
from .scoring import SYSTEM_SQL, zone_task_score

if TYPE_CHECKING:
    from .coverage import Coverage


# ---- geometry (GeoJSON order: [lng, lat]) ------------------------------------------------------
def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygons(geometry: dict) -> list[list]:
    return [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]


def contains(geometry: dict, lat: float, lng: float) -> bool:
    """Point in a Polygon or MultiPolygon; holes are respected."""
    return any(_in_ring(lng, lat, rings[0]) and not any(_in_ring(lng, lat, hole) for hole in rings[1:])
               for rings in _polygons(geometry))


def centroid(geometry: dict) -> tuple[float, float]:
    """(lat, lng) of the largest outer ring's centroid; the vertex average for degenerate shapes."""
    best = None
    for rings in _polygons(geometry):
        ring = rings[0]
        area = cx = cy = 0.0
        for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:] + ring[:1]):
            cross = x1 * y2 - x2 * y1
            area += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if best is None or abs(area) > abs(best[0]):
            best = (area, cx, cy, ring)
    area, cx, cy, ring = best
    if abs(area) < 1e-15:
        return (sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring))
    return (cy / (3 * area), cx / (3 * area))


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    points = [p for rings in _polygons(geometry) for p in rings[0]]
    return (min(p[1] for p in points), min(p[0] for p in points), max(p[1] for p in points),
            max(p[0] for p in points))


class ZoneMap:
    """Zone shapes in memory, so every report can be placed in its zone at ingest."""

    def __init__(self, rows: list[dict] | None = None):
        self._zones: list[tuple[str, tuple, dict]] = []
        self.load(rows or [])

    @classmethod
    def from_db(cls, db: Database) -> "ZoneMap":
        return cls(db.all("SELECT name, polygon FROM zones"))

    def load(self, rows: list[dict]) -> None:
        zones = []
        for row in sorted(rows, key=lambda r: r["name"]):
            geometry = row["polygon"] if isinstance(row["polygon"], dict) else json.loads(row["polygon"])
            zones.append((row["name"], _bbox(geometry), geometry))
        self._zones = zones                       # one assignment, so readers never see half a list

    @property
    def names(self) -> list[str]:
        return [name for name, _, _ in self._zones]

    def geometry(self, name: str) -> dict | None:
        return next((g for n, _, g in self._zones if n == name), None)

    def locate(self, lat: float | None, lng: float | None) -> str | None:
        """The zone a point is in (the first by name if shapes overlap), or None."""
        if lat is None or lng is None:
            return None
        for name, (s, w, n, e), geometry in self._zones:
            if s <= lat <= n and w <= lng <= e and contains(geometry, lat, lng):
                return name
        return None


# ---- the Silent Zone test (pure) -----------------------------------------------------------------
@dataclass
class ZoneCount:
    name: str
    population: int
    hard_hit: bool
    actual: int
    registered: int
    confirmed: int
    warned: bool = True          # an active alert covers the zone: before a warning there is no coverage


@dataclass
class Silence:
    name: str
    hard_hit: bool
    rate: float | None
    expected: float | None
    ratio: float | None
    coverage: float | None
    quiet: bool
    unheard: bool

    @property
    def silent(self) -> bool:
        return self.quiet or self.unheard


def find_silent(zones: list[ZoneCount], rules: dict) -> dict[str, Silence]:
    hard = [z for z in zones if z.hard_hit]
    out = {}
    for z in zones:
        coverage = z.confirmed / z.registered if z.registered else None
        if not z.hard_hit:
            out[z.name] = Silence(z.name, False, None, None, None, coverage, False, False)
            continue
        rates = [o.actual / o.population * 100 for o in hard if o is not z and o.population > 0]
        rate = (statistics.median(rates) if rates else 0) or rules["default_rate_per_100"]
        expected = z.population / 100 * rate
        ratio = z.actual / expected if expected else None
        quiet = expected >= rules["min_expected"] and ratio < rules["ratio"]
        unheard = (z.warned and z.registered >= rules["min_registered"]
                   and z.confirmed / z.registered < rules["coverage"])
        out[z.name] = Silence(z.name, True, rate, expected, ratio, coverage, quiet, unheard)
    return out


def pct(x: float | None) -> str:
    return "" if x is None else f"{round(x * 100)}%"


# ---- the zones table -------------------------------------------------------------------------------
class ZoneBook:
    def __init__(self, db: Database, zone_map: ZoneMap, cases: CaseBook, coverage: "Coverage",
                 profiles: Profiles, schemas: Schemas, constants: dict):
        self.db = db
        self.zone_map = zone_map
        self.cases = cases
        self.coverage = coverage
        self.profiles = profiles
        self.schemas = schemas
        self.rules = constants["silent"]
        self._lock = threading.Lock()
        self._dirty = True

    def mark_dirty(self) -> None:
        self._dirty = True

    def refresh_if_dirty(self) -> None:
        if self._dirty:
            self.update()

    # ---- import and marking ----------------------------------------------------------------
    def import_geojson(self, doc: object, by: str, now: datetime | None = None) -> dict:
        """Replace the town's zones. Hard-hit marks are kept for zones that keep their name."""
        now = now or timeutil.now()
        errors = self.schemas.errors("zones", doc)
        if errors:
            raise ValueError("not a zones file: " + "; ".join(errors[:3]))
        rows = [{"name": f["properties"]["name"].strip(), "population": f["properties"]["population"],
                 "polygon": f["geometry"]} for f in doc["features"]]
        names = [r["name"] for r in rows]
        if len(set(names)) != len(names):
            raise ValueError("zone names must be unique")
        with self.db.write() as conn:
            marked = {r["name"]: r["marked_at"] for r in _rows(conn, "SELECT name, marked_at FROM zones")}
            conn.execute("DELETE FROM zones")
            for r in rows:
                conn.execute("INSERT INTO zones(name, polygon, population, hard_hit, actual, registered, confirmed, "
                             "silent, quiet, unheard, marked_at) VALUES(?, ?, ?, 0, 0, 0, 0, 0, 0, 0, ?)",
                             (r["name"], json.dumps(r["polygon"]), r["population"], marked.get(r["name"])))
            self.zone_map.load(rows)
            located = self.cases.relocate(conn, now)
            for p in _rows(conn, "SELECT id, lat, lng FROM registry WHERE lat IS NOT NULL AND lng IS NOT NULL"):
                zone = self.zone_map.locate(p["lat"], p["lng"])
                if zone:
                    conn.execute("UPDATE registry SET zone = ? WHERE id = ?", (zone, p["id"]))
            self.cases.audit(conn, now, by, "zones_import", "zones", f"{len(rows)} zones")
        self.update(now)
        return {"zones": len(rows), "reports_located": located}

    def set_hard_hit(self, names: list[str], hard_hit: bool, by: str, now: datetime | None = None) -> list[dict]:
        """The dispatcher (or the replay) marks zones inside the hazard extent, or clears them."""
        now = now or timeutil.now()
        unknown = sorted(set(names) - set(self.zone_map.names))
        if unknown:
            raise ValueError(f"unknown zones: {', '.join(unknown)}")
        with self.db.write() as conn:
            for name in names:
                conn.execute("UPDATE zones SET marked_at = CASE WHEN ? THEN COALESCE(marked_at, ?) END WHERE name = ?",
                             (int(hard_hit), timeutil.iso(now), name))
                self.cases.audit(conn, now, by, "hard_hit" if hard_hit else "not_hard_hit", f"zone:{name}", "")
        self.update(now)
        return [z for z in self.views() if z["name"] in names]

    def create_task(self, name: str, by: str, now: datetime | None = None) -> dict:
        """'Send welfare-check team': one open zone task per zone, ranked with the cases."""
        now = now or timeutil.now()
        if name not in self.zone_map.names:
            raise NotFound(f"unknown zone {name}")
        with self.db.write() as conn:
            case_id = self._open_task(conn, name)
            if case_id is None:
                zone = dict(conn.execute("SELECT * FROM zones WHERE name = ?", (name,)).fetchone())
                lat, lng = centroid(json.loads(zone["polygon"]))
                waiting = len(self.coverage.unconfirmed(conn, now, zone=name))
                case_id = self.cases.add_report(conn, {
                    "id": f"zone_task:{uuid.uuid4()}", "source": "zone_task",
                    "hazard": setting(conn, "active_hazard", "flood"), "for_whom": "other", "people": max(1, waiting),
                    "conditions": [], "details": {}, "lat": round(lat, 6), "lng": round(lng, 6), "landmark": name,
                    "note": f"Welfare-check sweep of {name}: {waiting} of {zone['registered']} registered "
                            "vulnerable people unconfirmed",
                    "device_id": by, "reporter_role": "dispatcher", "reader": "system",
                    "created_at": timeutil.iso(now), "received_at": timeutil.iso(now), "zone": name}, now, merge=False)
                conn.execute("UPDATE cases SET verified = 1, status = 'verified' WHERE id = ?", (case_id,))
                self.cases.rescore(conn, case_id, now)
        return self.cases.detail(case_id, now)

    # ---- recompute (scheduler, and the snapshot when dirty) -------------------------------------
    def update(self, now: datetime | None = None) -> None:
        now = now or timeutil.now()
        with self._lock:
            self._dirty = False
            with self.db.read() as conn:
                zones = _rows(conn, "SELECT * FROM zones ORDER BY name")
                if not zones:
                    return
                hazard = setting(conn, "active_hazard", "flood")
                alerts = self.coverage.active_alerts(conn, now)
                actual = dict(conn.execute(
                    f"SELECT zone, COUNT(*) FROM reports WHERE zone IS NOT NULL AND source NOT IN {SYSTEM_SQL} "
                    "GROUP BY zone").fetchall())
                people = self.coverage.zone_counts(conn, alerts)
            by_alert: dict[str, str] = {}
            if self.profiles.get(hazard).get("affected") == "alert_zones":
                for a in alerts:
                    if a["hazard"] == hazard:
                        for name in a["zones"]:
                            by_alert[name] = min(by_alert.get(name, a["issued_at"]), a["issued_at"])
            warned = self.coverage.window_starts(alerts)
            counts, since = [], {}
            for z in zones:
                times = [t for t in (z["marked_at"], by_alert.get(z["name"])) if t]
                since[z["name"]] = min(times) if times else None
                registered, confirmed = people.get(z["name"], (0, 0))
                counts.append(ZoneCount(z["name"], z["population"] or 0, bool(times), actual.get(z["name"], 0),
                                        registered, confirmed, z["name"] in warned))
            found = find_silent(counts, self.rules)
            changes = []
            for z, c in zip(zones, counts):
                s = found[z["name"]]
                row = {"hard_hit": int(s.hard_hit), "hard_hit_since": since[z["name"]],
                       "expected": None if s.expected is None else round(s.expected, 1),
                       "rate": None if s.rate is None else round(s.rate, 2), "actual": c.actual,
                       "registered": c.registered, "confirmed": c.confirmed, "quiet": int(s.quiet),
                       "unheard": int(s.unheard), "silent": int(s.silent),
                       "silent_since": (z["silent_since"] or timeutil.iso(now)) if s.silent else None}
                if any(z[k] != v for k, v in row.items()):
                    changes.append((z, row, s))
            if not changes:
                return
            with self.db.write() as conn:
                for z, row, s in changes:
                    conn.execute(f"UPDATE zones SET {', '.join(f'{k} = ?' for k in row)} WHERE name = ?",
                                 (*row.values(), z["name"]))
                    if bool(z["silent"]) != s.silent:
                        detail = "; ".join(_lines(dict(z, **row), hazard))
                        self.cases.audit(conn, now, "server", "silent" if s.silent else "not_silent",
                                         f"zone:{z['name']}", detail)

    # ---- views ---------------------------------------------------------------------------------------
    def views(self) -> list[dict]:
        with self.db.read() as conn:
            hazard = setting(conn, "active_hazard", "flood")
            zones = _rows(conn, "SELECT * FROM zones ORDER BY name")
            tasks = {r["zone"]: r["id"] for r in _rows(
                conn, f"SELECT zone, id FROM cases WHERE source = 'zone_task' AND {OPEN_SQL}", OPEN_STATUSES)}
        return [_view(z, hazard, tasks.get(z["name"])) for z in zones]

    def card(self, name: str, now: datetime | None = None) -> dict:
        """The zone card: the numbers, the outreach list (highest risk first) and the zone task."""
        now = now or timeutil.now()
        self.refresh_if_dirty()
        zone = next((z for z in self.views() if z["name"] == name), None)
        if zone is None:
            raise NotFound(f"unknown zone {name}")
        with self.db.read() as conn:
            waiting = self.coverage.unconfirmed(conn, now, zone=name)
        medical = sum(1 for p in waiting if p["priority"] == "medical")
        lines = list(zone["lines"])
        if medical:
            lines.append(f"{medical} of the unconfirmed need oxygen, dialysis, insulin or power for a device")
        points, reasons = zone_task_score(name, zone["registered"], self.rules)
        return {"zone": zone, "lines": lines, "unconfirmed": waiting,
                "task": {"case_id": zone["task_case_id"], "points": points, "reasons": reasons}}

    @staticmethod
    def _open_task(conn: sqlite3.Connection, name: str) -> int | None:
        row = conn.execute(f"SELECT id FROM cases WHERE source = 'zone_task' AND zone = ? AND {OPEN_SQL} "
                           "ORDER BY id LIMIT 1", (name,) + OPEN_STATUSES).fetchone()
        return row[0] if row else None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _lines(z: dict, hazard: str) -> list[str]:
    """The zone card's explanation, one plain line per fact."""
    if not z["hard_hit"]:
        lines = [f"Not hard-hit by the current {hazard}"]
    else:
        expected = round(z["expected"])
        lines = [f"Expected about {expected} report{'' if expected == 1 else 's'}, got {z['actual']}"]
    if z["registered"]:
        coverage = z["confirmed"] / z["registered"]
        lines.append(f"Warning coverage: {z['confirmed']} of {z['registered']} registered vulnerable people "
                     f"confirmed ({pct(coverage)})")
    if z["quiet"]:
        lines.append("Very few reports for its size: possible phone or power outage")
    if z["unheard"]:
        lines.append("Most registered vulnerable people have not confirmed the warning")
    return lines


def _view(z: dict, hazard: str, task_case_id: int | None) -> dict:
    return {
        "name": z["name"],
        "population": z["population"] or 0,
        "hard_hit": bool(z["hard_hit"]),
        "hard_hit_since": z["hard_hit_since"],
        "silent": bool(z["silent"]),
        "silent_since": z["silent_since"],
        "quiet": bool(z["quiet"]),
        "unheard": bool(z["unheard"]),
        "expected": z["expected"],
        "actual": z["actual"] or 0,
        "rate": z["rate"],
        "registered": z["registered"] or 0,
        "confirmed": z["confirmed"] or 0,
        "coverage": round(z["confirmed"] / z["registered"], 2) if z["registered"] else None,
        "lines": _lines(z, hazard),
        "task_case_id": task_case_id,
        "polygon": json.loads(z["polygon"]),
    }

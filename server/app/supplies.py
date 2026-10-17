"""Shelters, cooling centres and supplies (System Design 9.8; Team Brief 3.7 and 3.9 i).

Places: every shelter, cooling centre or hospital has a capacity and a head count. One that is
nearly full names the nearest other place with space.

Stock lives at places: "command_post", "shelter:<id>" and "team:<id>" (a team's load). Every
movement is a row in supply_moves: restock, load, unload, deliver, transfer, used.
  left            = stock at every place
  used per hour   = "used" moves in the last supplies.burn_window_hours / that many hours
  runs out in     = left / used per hour (none if nothing was used)
  low             = left <= the item's warning level
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import timeutil
from .cases import CaseBook, NotFound
from .db import Database
from .packets import distance_m

PLACE_TYPES = ("shelter", "cooling_centre", "hospital", "other")
COMMAND_POST = "command_post"
# kind -> (from place: required / default command post / none, to place: the same)
MOVES = {
    "restock": (None, "default"),
    "used": ("default", None),
    "load": ("default", "team"),
    "unload": ("team", "default"),
    "deliver": ("default", "shelter"),
    "transfer": ("any", "any"),
}


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class SupplyBook:
    def __init__(self, db: Database, cases: CaseBook, constants: dict):
        self.db = db
        self.cases = cases
        self.rules = constants["supplies"]

    # ---- places ---------------------------------------------------------------------------------
    def save_shelter(self, req: dict, by: str, now: datetime | None = None) -> dict:
        """Add a place or change it (POST /api/shelters). A shelter manager sends just id and occupancy."""
        now = now or timeutil.now()
        sid = req["id"]
        with self.db.write() as conn:
            old = conn.execute("SELECT * FROM shelters WHERE id = ?", (sid,)).fetchone()
            row = dict(old) if old else {"id": sid, "name": None, "type": "shelter", "lat": None, "lng": None,
                                         "capacity": None, "occupancy": 0}
            row.update({k: v for k, v in req.items() if k in row and v is not None and k != "id"})
            if not row["name"]:
                raise ValueError("a new place needs a name")
            if row["type"] not in PLACE_TYPES:
                raise ValueError(f"type must be one of {', '.join(PLACE_TYPES)}")
            if (row["capacity"] is not None and row["capacity"] < 0) or row["occupancy"] < 0:
                raise ValueError("capacity and occupancy cannot be negative")
            conn.execute("INSERT INTO shelters(id, name, type, lat, lng, capacity, occupancy, updated_at) "
                         "VALUES(:id, :name, :type, :lat, :lng, :capacity, :occupancy, :updated_at) "
                         "ON CONFLICT(id) DO UPDATE SET name = excluded.name, type = excluded.type, lat = excluded.lat, "
                         "lng = excluded.lng, capacity = excluded.capacity, occupancy = excluded.occupancy, "
                         "updated_at = excluded.updated_at", dict(row, updated_at=timeutil.iso(now)))
            self.cases.audit(conn, now, by, "place" if old is None else "place_update", f"shelter:{sid}",
                             f"{row['occupancy']}/{row['capacity'] if row['capacity'] is not None else '?'}")
        return next(s for s in self.shelters() if s["id"] == sid)

    def add_people(self, conn: sqlite3.Connection, shelter_id: str, people: int, now: datetime, by: str) -> bool:
        """A team brought people to a place: its head count goes up. False if the place is unknown."""
        cur = conn.execute("UPDATE shelters SET occupancy = COALESCE(occupancy, 0) + ?, updated_at = ? WHERE id = ?",
                           (people, timeutil.iso(now), shelter_id))
        if cur.rowcount:
            self.cases.audit(conn, now, by, "arrivals", f"shelter:{shelter_id}", f"+{people}")
        return bool(cur.rowcount)

    def nearest_place(self, conn: sqlite3.Connection, lat: float | None, lng: float | None, prefer: str,
                      people: int = 1, exclude: tuple = ()) -> dict | None:
        """The nearest shelter or cooling centre with room for these people; the preferred type first."""
        if lat is None or lng is None:
            return None
        best = None
        for s in _rows(conn, "SELECT * FROM shelters WHERE type IN ('shelter', 'cooling_centre') "
                             "AND lat IS NOT NULL AND lng IS NOT NULL"):
            space = None if s["capacity"] is None else s["capacity"] - (s["occupancy"] or 0)
            if s["id"] in exclude or (space is not None and space < people):
                continue
            key = (s["type"] != prefer, distance_m(lat, lng, s["lat"], s["lng"]))
            if best is None or key < best[0]:
                best = (key, s, space)
        if best is None:
            return None
        (_, metres), s, space = best
        return {"id": s["id"], "name": s["name"], "type": s["type"], "lat": s["lat"], "lng": s["lng"],
                "space_left": space, "distance_km": round(metres / 1000, 2)}

    def shelters(self) -> list[dict]:
        with self.db.read() as conn:
            rows = _rows(conn, "SELECT * FROM shelters ORDER BY name")
            out = []
            for s in rows:
                space = None if s["capacity"] is None else max(0, s["capacity"] - (s["occupancy"] or 0))
                nearly = bool(s["capacity"]) and (s["occupancy"] or 0) >= self.rules["shelter_nearly_full"] * s["capacity"]
                nxt = self.nearest_place(conn, s["lat"], s["lng"], s["type"], exclude=(s["id"],)) if nearly else None
                out.append({"id": s["id"], "name": s["name"], "type": s["type"], "lat": s["lat"], "lng": s["lng"],
                            "capacity": s["capacity"], "occupancy": s["occupancy"] or 0, "space_left": space,
                            "nearly_full": nearly, "next": None if nxt is None else {"id": nxt["id"], "name": nxt["name"]},
                            "updated_at": s["updated_at"]})
        return out

    # ---- stock ------------------------------------------------------------------------------------
    def set_level(self, item: str, warn_at: float | None, unit: str | None, by: str,
                  now: datetime | None = None) -> dict:
        """POST /api/supplies: the item's low-stock level and unit."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            unit = unit or self._unit(conn, item)
            self._add(conn, item, COMMAND_POST, 0, unit)
            conn.execute("UPDATE supplies SET unit = ? WHERE item = ?", (unit, item))
            conn.execute("UPDATE supplies SET warn_at = ? WHERE item = ? AND place = ?", (warn_at, item, COMMAND_POST))
            self.cases.audit(conn, now, by, "supply_level", f"supply:{item}", f"warn at {warn_at}, unit {unit}")
        return next(s for s in self.views(now) if s["item"] == item)

    def move(self, req: dict, by: str, now: datetime | None = None) -> dict:
        """POST /api/supplies/move: restock, load, unload, deliver, transfer or used. Returns the item's row."""
        now = now or timeutil.now()
        kind, item, qty = req["kind"], req["item"], float(req["qty"])
        if kind not in MOVES:
            raise ValueError(f"kind must be one of {', '.join(MOVES)}")
        if qty <= 0:
            raise ValueError("qty must be more than 0")
        with self.db.write() as conn:
            src = self._place(conn, req.get("from"), MOVES[kind][0], "from", kind)
            dst = self._place(conn, req.get("to"), MOVES[kind][1], "to", kind)
            if src is not None:
                have = self.stock(conn, item, src)
                if have < qty:
                    raise ValueError(f"only {have:g} {item} at {src}")
            unit = req.get("unit") or self._unit(conn, item)
            if src is not None:
                self._add(conn, item, src, -qty, unit)
            if dst is not None:
                self._add(conn, item, dst, qty, unit)
            self._log(conn, item, src, dst, qty, now, by, kind, req.get("job_id"))
        return next(s for s in self.views(now) if s["item"] == item)

    def use_load(self, conn: sqlite3.Connection, team_id: str, used: dict, job_id: str | None, now: datetime,
                 by: str) -> None:
        """The outcome form's supplies used leave the team's load (never below zero)."""
        place = f"team:{team_id}"
        for item, qty in used.items():
            if qty <= 0:
                continue
            have = self.stock(conn, item, place)
            self._add(conn, item, place, -min(have, qty), self._unit(conn, item))
            self._log(conn, item, place, None, qty, now, by, "used", job_id)

    @staticmethod
    def stock(conn: sqlite3.Connection, item: str, place: str) -> float:
        row = conn.execute("SELECT qty FROM supplies WHERE item = ? AND place = ?", (item, place)).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    @staticmethod
    def tracked(conn: sqlite3.Connection, item: str) -> bool:
        return conn.execute("SELECT 1 FROM supplies WHERE item = ? LIMIT 1", (item,)).fetchone() is not None

    def loads(self, conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
        """team ID -> {item: qty} for what each team carries."""
        out: dict[str, dict[str, float]] = {}
        for r in _rows(conn, "SELECT item, place, qty FROM supplies WHERE place LIKE 'team:%' AND qty > 0"):
            out.setdefault(r["place"][5:], {})[r["item"]] = r["qty"]
        return out

    def views(self, now: datetime | None = None) -> list[dict]:
        """One row per item: where it is, what was used, how long it lasts."""
        now = now or timeutil.now()
        window = self.rules["burn_window_hours"]
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db.read() as conn:
            rows = _rows(conn, "SELECT * FROM supplies ORDER BY item, place")
            used = _rows(conn, "SELECT item, qty, at FROM supply_moves WHERE reason = 'used' AND at >= ?",
                         (timeutil.iso(min(today, now - timedelta(hours=window))),))
        items: dict[str, dict] = {}
        for r in rows:
            v = items.setdefault(r["item"], {"item": r["item"], "unit": r["unit"] or self.rules["default_unit"],
                                             "command_post": 0.0, "shelters": 0.0, "teams": 0.0, "places": {},
                                             "warn_at": None})
            qty = r["qty"] or 0.0
            v["places"][r["place"]] = qty
            v["command_post" if r["place"] == COMMAND_POST else "teams" if r["place"].startswith("team:")
              else "shelters"] += qty
            if r["warn_at"] is not None:
                v["warn_at"] = max(v["warn_at"] or 0, r["warn_at"])
        for v in items.values():
            moves = [u for u in used if u["item"] == v["item"]]
            v["used_today"] = sum(u["qty"] for u in moves if timeutil.parse(u["at"]) >= today)
            recent = sum(u["qty"] for u in moves if timeutil.parse(u["at"]) >= now - timedelta(hours=window))
            v["left"] = v["command_post"] + v["shelters"] + v["teams"]
            v["per_hour"] = round(recent / window, 2)
            v["runs_out_in_hours"] = round(v["left"] / v["per_hour"], 1) if v["per_hour"] else None
            v["low"] = v["warn_at"] is not None and v["left"] <= v["warn_at"]
        return list(items.values())

    @staticmethod
    def warnings(views: list[dict], shelters: list[dict]) -> list[str]:
        out = []
        for v in views:
            if v["low"]:
                runs = f", runs out in about {v['runs_out_in_hours']:g} h" if v["runs_out_in_hours"] is not None else ""
                out.append(f"{v['item'].replace('_', ' ').capitalize()}: {v['left']:g} left (warn at {v['warn_at']:g}){runs}")
        for s in shelters:
            if s["nearly_full"]:
                nxt = f"; next: {s['next']['name']}" if s["next"] else "; no other place with space"
                out.append(f"{s['name']} nearly full ({s['occupancy']}/{s['capacity']}){nxt}")
        return out

    # ---- helpers -------------------------------------------------------------------------------------
    def _place(self, conn: sqlite3.Connection, given: str | None, rule: str | None, side: str, kind: str) -> str | None:
        if rule is None:
            if given:
                raise ValueError(f"a {kind} move has no '{side}' place")
            return None
        place = given or (COMMAND_POST if rule == "default" else None)
        if place is None:
            raise ValueError(f"a {kind} move needs a '{side}' place")
        if place == COMMAND_POST:
            if rule in ("team", "shelter"):
                raise ValueError(f"a {kind} move goes {side} a {rule}")
            return place
        prefix, _, ident = place.partition(":")
        if prefix not in ("team", "shelter") or not ident:
            raise ValueError(f"place must be 'command_post', 'team:<id>' or 'shelter:<id>', not {place!r}")
        if rule in ("team", "shelter") and prefix != rule:
            raise ValueError(f"a {kind} move goes {side} a {rule}")
        table = "teams" if prefix == "team" else "shelters"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (ident,)).fetchone():
            raise NotFound(f"unknown {prefix} {ident}")
        return place

    def _unit(self, conn: sqlite3.Connection, item: str) -> str:
        row = conn.execute("SELECT unit FROM supplies WHERE item = ? AND unit IS NOT NULL LIMIT 1", (item,)).fetchone()
        return row[0] if row else self.rules["units"].get(item, self.rules["default_unit"])

    @staticmethod
    def _add(conn: sqlite3.Connection, item: str, place: str, qty: float, unit: str) -> None:
        conn.execute("INSERT INTO supplies(item, unit, place, qty) VALUES(?, ?, ?, ?) "
                     "ON CONFLICT(item, place) DO UPDATE SET qty = COALESCE(qty, 0) + excluded.qty",
                     (item, unit, place, qty))

    def _log(self, conn: sqlite3.Connection, item: str, src: str | None, dst: str | None, qty: float, now: datetime,
             by: str, kind: str, job_id: str | None) -> None:
        conn.execute("INSERT INTO supply_moves(item, from_place, to_place, qty, at, by, reason, job_id) "
                     "VALUES(?, ?, ?, ?, ?, ?, ?, ?)", (item, src, dst, qty, timeutil.iso(now), by, kind, job_id))
        self.cases.audit(conn, now, by, f"supply_{kind}", f"supply:{item}",
                         json.dumps({"qty": qty, "from": src, "to": dst, "job": job_id}))

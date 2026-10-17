"""Suggest a team and a place, show the trade-off, and assign (System Design 9.6; Team Brief 3.9 i).

A team can be suggested for a case when it is available, its fuel is not low, its position is
known, it can do everything the case needs (constants teams.capabilities_*), and for each supply
the case needs (profile supply_rules) it carries some or the command post has some to fetch on
the way. Supplies nobody has entered yet do not block anyone. Travel = distance x detour / speed.

Trade-off: if the best team is also the best for another unassigned case in the top
suggest.top_cases, the answer says how much longer that case would wait with its next best team.

A person always confirms. POST /api/assign makes the job: a public packet signed by the command
post, addressed to the team's phone (to_device). It carries only what the team needs, no names.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import outbound, timeutil
from .cases import OPEN_SQL, OPEN_STATUSES, CaseBook, NotFound, case_view, rank_key
from .crypto import CommandPostKeys
from .db import Database, next_number
from .packets import distance_m, geohash
from .profiles import Profiles
from .schemas import Schemas
from .supplies import COMMAND_POST, SupplyBook
from .teams import TeamBook, travel_minutes

PHRASES = {"elderly": "elderly", "child": "child", "infant": "infant", "pregnant": "pregnant",
           "cannot_walk": "cannot walk", "disabled": "disabled", "oxygen": "needs oxygen",
           "dialysis": "needs dialysis", "insulin": "needs insulin", "power_dependent": "medical device needs power",
           "other_medicine": "needs medicine", "injured": "injured", "bleeding": "bleeding",
           "unconscious": "unconscious", "alone": "alone", "no_food_water": "no food or water"}


def job_summary(case: dict) -> str:
    """'1 person, elderly, cannot walk, needs oxygen; water at waist and rising'"""
    people = case["people"]
    parts = [f"{people} {'person' if people == 1 else 'people'}"]
    parts += [PHRASES.get(c, c.replace("_", " ")) for c in json.loads(case["conditions"])]
    text = ", ".join(parts)
    if case["hours_text"]:
        text += "; " + case["hours_text"][0].lower() + case["hours_text"][1:]
    return text[:200]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class Dispatch:
    def __init__(self, db: Database, keys: CommandPostKeys, schemas: Schemas, profiles: Profiles, cases: CaseBook,
                 teams: TeamBook, supplies: SupplyBook, constants: dict):
        self.db = db
        self.keys = keys
        self.schemas = schemas
        self.profiles = profiles
        self.cases = cases
        self.teams = teams
        self.supplies = supplies
        self.constants = constants
        self.rules = constants["suggest"]

    # ---- suggestions ----------------------------------------------------------------------------------
    def suggest(self, case_id: int, now: datetime | None = None) -> dict:
        """GET /api/suggest?case_id=: best team, alternatives, trade-off, teams about to be free, place."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            case = self.cases._case(conn, case_id)
            world = self._world(conn, now)
            ranked = world["ranked"]
            rank = next((i for i, c in enumerate(ranked, 1) if c["id"] == case_id), None)
            options, why = self._options(case, world)
            best = options[0] if options else None
            tradeoff = tradeoff_case = None
            if best is not None:
                for other_rank, other in enumerate(ranked[:self.rules["top_cases"]], 1):
                    if other["id"] == case_id or other["team_id"]:
                        continue
                    theirs, _ = self._options(world["rows"][other["id"]], world)
                    if theirs and theirs[0]["team_id"] == best["team_id"]:
                        tradeoff_case = other["id"]
                        if len(theirs) > 1:
                            extra = round(theirs[1]["_minutes"] - theirs[0]["_minutes"])
                            tradeoff = (f"{best['name']} is also best for case #{other_rank}. If it goes here, "
                                        f"#{other_rank} waits about {extra} more min (next best: {theirs[1]['name']})")
                        else:
                            tradeoff = (f"{best['name']} is also best for case #{other_rank}. If it goes here, "
                                        f"no other free team can go to #{other_rank}")
                        break
            place = self.supplies.nearest_place(conn, case["lat"], case["lng"],
                                                "cooling_centre" if case["hazard"] == "heat" else "shelter",
                                                case["people"])
        return {
            "case_id": case_id, "rank": rank, "needs": json.loads(case["needs"] or "[]"),
            "supplies": self._items(case),
            "best": _public(best), "alternatives": [_public(o) for o in options[1:1 + self.rules["alternatives"]]],
            "tradeoff": tradeoff, "tradeoff_case_id": tradeoff_case,
            "soon_free": self._soon_free(case, world, now), "place": place, "why_none": None if best else why,
        }

    def suggest_all(self, now: datetime | None = None) -> dict:
        """Walk down the ranked list and give each unassigned case its fastest free team, each team
        once. Nothing is assigned: a person confirms each one."""
        now = now or timeutil.now()
        with self.db.read() as conn:
            world = self._world(conn, now)
        used, plans = set(), []
        for rank, case in enumerate(world["ranked"], 1):
            if case["team_id"]:
                continue
            options, why = self._options(world["rows"][case["id"]], world)
            options = [o for o in options if o["team_id"] not in used]
            if options:
                used.add(options[0]["team_id"])
            plans.append({"case_id": case["id"], "rank": rank, "points": case["points"],
                          "team": _public(options[0]) if options else None,
                          "why_none": None if options else why or "every capable team is suggested higher up"})
        return {"plans": plans}

    # ---- assign ---------------------------------------------------------------------------------------------
    def assign(self, req: dict, by: str, now: datetime | None = None) -> dict:
        """POST /api/assign: the dispatcher confirms a team for a case. Creates and queues the job."""
        now = now or timeutil.now()
        warnings = []
        with self.db.write() as conn:
            case = self.cases._case(conn, req["case_id"])
            if case["status"] not in OPEN_STATUSES:
                raise ValueError(f"case #{case['id']} is {case['status']}")
            team = self.teams._team(conn, req["team_id"])
            if team["status"] != "available":
                raise ValueError(f"{team['name']} is {team['status'].replace('_', ' ')}, not available")
            if case["team_id"]:
                if not req.get("reassign"):
                    raise ValueError(f"case #{case['id']} already has team {case['team_id']}; "
                                     "send reassign: true to replace it")
                self.teams.release(conn, case["team_id"], now, by, f"case #{case['id']} reassigned to {team['name']}")
            minutes = req.get("eta_min")
            if minutes is None:
                if None in (case["lat"], team["lat"]):
                    raise ValueError("no position to work out the ETA; send eta_min")
                minutes = travel_minutes(team["lat"], team["lng"], case["lat"], case["lng"], team["speed_kmh"],
                                         self.constants["teams"]["detour"])
            eta = now + timedelta(minutes=minutes)
            place = None
            if req.get("place"):
                row = conn.execute("SELECT * FROM shelters WHERE id = ?", (req["place"],)).fetchone()
                if row is None:
                    raise NotFound(f"unknown place {req['place']}")
                place = {"id": row["id"], "name": row["name"], "lat": row["lat"], "lng": row["lng"]}
                if row["lat"] is None:
                    raise ValueError(f"place {row['id']} has no position")
            missing = set(json.loads(case["needs"] or "[]")) - set(json.loads(team["capabilities"] or "[]"))
            if missing:
                warnings.append(f"{team['name']} cannot do {', '.join(sorted(missing))}")
            if team["fuel"] == "low":
                warnings.append(f"{team['name']} is low on fuel")
            job_id = self._next_job_id(conn)
            payload = {
                "job_id": job_id, "case_id": case["id"], "team_id": team["id"], "hazard": case["hazard"],
                "summary": job_summary(case), "lat": case["lat"], "lng": case["lng"], "people": case["people"],
                "conditions": json.loads(case["conditions"]), "needs": json.loads(case["needs"] or "[]"),
                "first_aid": self.profiles.get(case["hazard"]).get("first_aid", {}).get("en", [])[:3],
                "eta": timeutil.iso(eta), "place": place,
            }
            if case["landmark"]:
                payload["landmark"] = case["landmark"][:200]
            self.schemas.check("payloads/job", payload)
            queued = None
            if team["device_id"]:
                area = geohash(case["lat"], case["lng"], 5) if case["lat"] is not None else "0"
                queued = outbound.enqueue(conn, self.keys, self.constants, "job", payload, area=area,
                                          to_device=team["device_id"], created=now)
            else:
                warnings.append(f"{team['name']} has no phone: tell them by radio")
            conn.execute("INSERT INTO jobs(id, case_id, team_id, created_at, eta, status, packet_id, travel_min, "
                         "place_id) VALUES(?, ?, ?, ?, ?, 'assigned', ?, ?, ?)",
                         (job_id, case["id"], team["id"], timeutil.iso(now), timeutil.iso(eta),
                          queued["packet_id"] if queued else None, minutes, place["id"] if place else None))
            self.teams.start_job(conn, team, job_id, case["id"], timeutil.iso(eta), now, by)
            conn.execute("UPDATE cases SET status = 'assigned', team_id = ?, shelter_id = ? WHERE id = ?",
                         (team["id"], place["id"] if place else None, case["id"]))
            self.cases.audit(conn, now, by, "assign", f"case:{case['id']}",
                             f"{team['name']} ({job_id}), about {round(minutes)} min"
                             + (f", then {place['name']}" if place else ""))
        return {"job_id": job_id, "eta": timeutil.iso(eta), "travel_min": round(minutes),
                "outbound_seq": queued["seq"] if queued else None, "to_device": team["device_id"],
                "warnings": warnings}

    # ---- helpers ----------------------------------------------------------------------------------------------
    def _world(self, conn: sqlite3.Connection, now: datetime) -> dict:
        """Everything a suggestion looks at, read once."""
        rows = {r["id"]: r for r in _rows(conn, f"SELECT * FROM cases WHERE {OPEN_SQL}", OPEN_STATUSES)}
        ranked = sorted((case_view(r, now) for r in rows.values()), key=rank_key)
        teams = _rows(conn, "SELECT * FROM teams")
        for t in teams:
            t["capabilities"] = json.loads(t["capabilities"] or "[]")
        stock = {}
        for r in _rows(conn, "SELECT item, place, qty FROM supplies"):
            stock.setdefault(r["item"], {})[r["place"]] = r["qty"] or 0
        return {"rows": rows, "ranked": ranked, "teams": teams, "stock": stock}

    def _items(self, case: dict) -> list[str]:
        return self.profiles.supplies_needed(case["hazard"], json.loads(case["details"] or "{}"),
                                             json.loads(case["conditions"] or "[]"))

    def _options(self, case: dict, world: dict) -> tuple[list[dict], str | None]:
        """Teams that can go, fastest first, and why there are none."""
        if case["lat"] is None:
            return [], "the case has no position yet; choose a team by hand"
        needs = set(json.loads(case["needs"] or "[]"))
        items = self._items(case)
        free = [t for t in world["teams"] if t["status"] == "available" and t["fuel"] != "low" and t["lat"] is not None]
        if not free:
            return [], "no team is free"
        able = [t for t in free if needs <= set(t["capabilities"])]
        if not able:
            return [], f"no free team can do {' + '.join(sorted(needs))}"
        out = []
        for t in able:
            fetch, ok = [], True
            for item in items:
                where = world["stock"].get(item)
                if where is None or where.get(f"team:{t['id']}", 0) > 0:
                    continue                                        # not tracked, or carried
                if where.get(COMMAND_POST, 0) > 0:
                    fetch.append(item)
                else:
                    ok = False
            if not ok:
                continue
            minutes = travel_minutes(t["lat"], t["lng"], case["lat"], case["lng"], t["speed_kmh"],
                                     self.constants["teams"]["detour"])
            out.append({"team_id": t["id"], "name": t["name"], "type": t["type"], "_minutes": minutes,
                        "travel_min": round(minutes),
                        "distance_km": round(distance_m(t["lat"], t["lng"], case["lat"], case["lng"]) / 1000, 2),
                        "fetch": fetch})
        out.sort(key=lambda o: (o["_minutes"], o["team_id"]))
        return out, None if out else f"no free team has {', '.join(items)} and the command post has none"

    def _soon_free(self, case: dict, world: dict, now: datetime) -> list[dict]:
        """Capable teams on scene elsewhere that should be free within suggest.soon_free_minutes."""
        needs = set(json.loads(case["needs"] or "[]"))
        out = []
        for t in world["teams"]:
            if t["status"] != "on_scene" or not needs <= set(t["capabilities"]) or not t["status_since"]:
                continue
            free_in = (timeutil.parse(t["status_since"]) + timedelta(minutes=self.rules["on_scene_minutes"])
                       - now).total_seconds() / 60
            if free_in > self.rules["soon_free_minutes"]:
                continue
            travel = None
            if None not in (t["lat"], case["lat"]):
                travel = round(travel_minutes(t["lat"], t["lng"], case["lat"], case["lng"], t["speed_kmh"],
                                              self.constants["teams"]["detour"]))
            out.append({"team_id": t["id"], "name": t["name"], "free_in_min": max(0, round(free_in)), "travel_min": travel})
        return sorted(out, key=lambda o: o["free_in_min"])

    @staticmethod
    def _next_job_id(conn: sqlite3.Connection) -> str:
        return f"J-{next_number(conn, 'job_number', 'jobs', 'J'):03d}"


def _public(option: dict | None) -> dict | None:
    return None if option is None else {k: v for k, v in option.items() if not k.startswith("_")}

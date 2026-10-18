"""Build the scenario packs for the Karachi demo city (Team Brief 4.10 D2 and 5.2).

    python scenario/generate.py                  # flood, heat and earthquake
    python scenario/generate.py --pack flood --seed 7

Reads scenario/zones.geojson and scenario/templates/<hazard>.json and writes
scenario/packs/<hazard>/: pack.json, registry.csv, teams.json, shelters.json, supplies.json,
windows.json, messages.json (the timed story the replay streams in) and people.json (the hidden
truth: who really needs help and by when, used only by simulate.py).

Everything is made up: names, phone numbers (+000 ...), messages and populations. A fixed seed
gives the same pack every time, so a rehearsal and the demo match.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import re
from pathlib import Path

SCENARIO = Path(__file__).resolve().parent
PACKS = ("flood", "heat", "earthquake")

# Landmarks people would name in each zone (made up, local-sounding).
SPOTS = {
    "Lyari": ["Chakiwara chowk", "Kalri lane", "Baghdadi football ground", "Agra Taj colony", "Rexer lane",
              "Lea market", "Moosa lane", "the river bank near Kalri"],
    "Saddar": ["Empress market", "Regal chowk", "the bus stop near Preedy street", "Zaibunnisa street",
               "the underpass near Tower", "Bohri bazaar"],
    "Clifton": ["block 2 market", "Do Talwar", "the park in block 5", "Teen Talwar", "block 9 mosque"],
    "Korangi": ["sector 2 near the nullah", "sector 5 school", "Korangi crossing", "sector 4 market",
                "the madrasa near the crossing", "sector 1 green gate", "Korangi causeway"],
    "Shah Faisal": ["block 3", "colony gate", "Natha Khan bridge", "block 5 mosque", "the railway crossing"],
    "Malir": ["Malir halt", "Model colony", "Malir city market", "the river side of Malir"],
    "Orangi Town": ["sector 11", "Banaras chowk", "the nullah in sector 5", "Qasba colony", "sector 8 hill"],
    "North Nazimabad": ["block H", "Hyderi market", "block L park", "the hospital road", "block B flats"],
}

CONDITION_SETS = [  # registry: made-up vulnerable people (weights favour the common ones)
    ("elderly;alone", 5), ("elderly;cannot_walk", 4), ("oxygen;elderly", 3), ("dialysis", 2),
    ("disabled;cannot_walk", 3), ("power_dependent", 2), ("insulin;elderly", 2), ("pregnant", 2),
    ("infant", 2), ("elderly;alone;cannot_walk", 3), ("oxygen;power_dependent", 1), ("disabled", 2),
]

STORIES = {
    "flood": {
        "start": "14:00", "speed": 60, "end": 150, "hard_hit": ["Lyari", "Korangi"],
        "alert_zones": ["Lyari", "Korangi", "Shah Faisal"], "alert_at": 10,
        "reply_share": {"Lyari": 0.8, "Korangi": 0.8, "Shah Faisal": 0.12},
        "waves": [(0, 30, 25), (30, 60, 110), (60, 150, 35)],
        "zone_factor": {"Lyari": 1.0, "Korangi": 1.0, "Shah Faisal": 0.25},
        "other_factor": 0.07, "dup_share": 0.27,
        "towers_down": {"Shah Faisal": 60},
        "events": [
            (0, "cue", {"text": "River rising: Lyari and Korangi are hard-hit. The map fills, the list ranks."}),
            (8, "cue", {"text": "Issue a flood warning for Lyari, Korangi and Shah Faisal (New alert). Replies start."}),
            (60, "hard_hit", {"zones": ["Shah Faisal"]}),
            (60, "cue", {"text": "Phone towers fail in Shah Faisal: no messages or replies from there."}),
            (75, "window", {"zone": "Korangi", "closes_in_min": 105, "text": "Korangi causeway floods"}),
            (90, "chaos", {"what": "fake"}),
            (105, "chaos", {"what": "wrong_location"}),
            (110, "team_stop", {"team": "boat_3"}),
            (120, "ai_down", {}),
            (130, "cue", {"text": "Live: Phone A in Shah Faisal sends a report through the mesh to Phone C."}),
            (140, "cue", {"text": "Assign Boat 2 to the top case: its icon moves, 'on scene' within 100 m, then done."}),
            (145, "supply", {"item": "oxygen_cylinder", "qty": 5, "move": "used"}),
        ],
    },
    "heat": {
        "start": "07:00", "speed": 90, "end": 300, "hard_hit": [],
        "alert_zones": ["Lyari", "Saddar", "Korangi", "Orangi Town"], "alert_at": 2,
        "reply_share": {"Lyari": 0.85, "Saddar": 0.85, "Korangi": 0.8, "Orangi Town": 0.15},
        "waves": [(0, 120, 12), (120, 300, 24)],
        "zone_factor": {"Lyari": 1.0, "Saddar": 1.0, "Korangi": 1.0, "Orangi Town": 0.4},
        "other_factor": 0.15, "dup_share": 0.12,
        "towers_down": {},
        "events": [
            (0, "cue", {"text": "Issue a heat warning for Lyari, Saddar, Korangi and Orangi Town, 12:00-17:00, "
                                "with the cooling centres. Generate the announcement."}),
            (135, "cue", {"text": "Registered people who never answered become welfare-check cases. "
                                  "Orangi Town's coverage stays under 25%: a Silent Zone."}),
            (195, "volunteer", {}),
            (240, "window", {"zone": "Lyari", "closes_in_min": 60, "text": "Hottest hours start"}),
            (240, "window", {"zone": "Korangi", "closes_in_min": 60, "text": "Hottest hours start"}),
            (240, "window", {"zone": "Orangi Town", "closes_in_min": 60, "text": "Hottest hours start"}),
            (270, "place", {"id": "c_korangi", "occupancy": 93}),
            (271, "cue", {"text": "Cooling centre in Korangi nearly full: update the alert with the next centre."}),
        ],
    },
    "earthquake": {
        "start": "03:10", "speed": 60, "end": 120, "hard_hit": ["Saddar", "Lyari", "North Nazimabad"],
        "alert_zones": ["Saddar", "Lyari", "North Nazimabad"], "alert_at": 15,
        "reply_share": {"Saddar": 0.7, "Lyari": 0.7, "North Nazimabad": 0.0},
        "waves": [(0, 30, 35), (30, 90, 30), (90, 120, 8)],
        "zone_factor": {"Saddar": 1.0, "Lyari": 1.0, "North Nazimabad": 0.0},
        "other_factor": 0.08, "dup_share": 0.25,
        "towers_down": {"North Nazimabad": 0},
        "events": [
            (0, "cue", {"text": "Strong shaking across Saddar, Lyari and North Nazimabad. "
                                "Towers are down in North Nazimabad: it stays quiet."}),
            (15, "cue", {"text": "Issue an earthquake warning (aftershocks, gas) for the three zones."}),
            (30, "window", {"zone": "Saddar", "closes_in_min": 180, "text": "Rain arrives"}),
            (30, "window", {"zone": "Lyari", "closes_in_min": 180, "text": "Rain arrives"}),
            (45, "chaos", {"what": "fake"}),
            (60, "cue", {"text": "Rescue teams are the scarce resource: open Suggest on a trapped case "
                                 "to see the trade-off."}),
        ],
    },
}

TEAMS = {
    "flood": [("boat_1", "Boat 1", "boat", "Lyari", "full"), ("boat_2", "Boat 2", "boat", "Saddar", "half"),
              ("boat_3", "Boat 3", "boat", "Korangi", "full"), ("truck_1", "Truck 1", "truck", "Saddar", "full"),
              ("truck_2", "Truck 2", "truck", "Malir", "low"), ("medic_1", "Medic 1", "medic", "Saddar", None),
              ("medic_2", "Medic 2", "medic", "North Nazimabad", None),
              ("rescue_1", "Rescue 1", "rescue", "Shah Faisal", None),
              ("welfare_1", "Welfare 1", "welfare", "North Nazimabad", None),
              ("welfare_2", "Welfare 2", "welfare", "Clifton", None)],
    "heat": [("welfare_1", "Welfare 1", "welfare", "Lyari", None), ("welfare_2", "Welfare 2", "welfare", "Korangi", None),
             ("welfare_3", "Welfare 3", "welfare", "Orangi Town", None), ("medic_1", "Medic 1", "medic", "Saddar", None),
             ("medic_2", "Medic 2", "medic", "North Nazimabad", None), ("truck_1", "Truck 1", "truck", "Saddar", "full"),
             ("truck_2", "Truck 2", "truck", "Malir", "half"),
             ("volunteer_1", "Volunteer 1", "volunteer", "Saddar", None)],
    "earthquake": [("rescue_1", "Rescue 1", "rescue", "Saddar", None), ("rescue_2", "Rescue 2", "rescue", "Clifton", None),
                   ("rescue_3", "Rescue 3", "rescue", "Malir", None), ("fire_1", "Fire 1", "fire", "Saddar", "full"),
                   ("medic_1", "Medic 1", "medic", "Saddar", None), ("medic_2", "Medic 2", "medic", "Clifton", None),
                   ("truck_1", "Truck 1", "truck", "Korangi", "full"), ("truck_2", "Truck 2", "truck", "Malir", "half"),
                   ("welfare_1", "Welfare 1", "welfare", "Clifton", None),
                   ("welfare_2", "Welfare 2", "welfare", "Orangi Town", None)],
}

PLACES = {
    "flood": [("s_kashmir_road", "Sports complex, Kashmir Road", "shelter", 24.8775, 67.0605, 400, 120),
              ("s_nazimabad", "Govt school, North Nazimabad", "shelter", 24.9405, 67.0455, 250, 40),
              ("s_malir_hall", "Community hall, Malir", "shelter", 24.9010, 67.1950, 200, 185),
              ("h_central", "Central hospital, Saddar", "hospital", 24.8525, 67.0440, None, 0)],
    "heat": [("c_saddar", "Cooling centre, Saddar", "cooling_centre", 24.8560, 67.0300, 150, 20),
             ("c_orangi", "Cooling centre, Orangi Town", "cooling_centre", 24.9480, 66.9950, 120, 10),
             ("c_korangi", "Cooling centre, Korangi", "cooling_centre", 24.8350, 67.1250, 100, 30),
             ("s_kashmir_road", "Sports complex, Kashmir Road", "shelter", 24.8775, 67.0605, 400, 0),
             ("h_central", "Central hospital, Saddar", "hospital", 24.8525, 67.0440, None, 0)],
    "earthquake": [("s_kashmir_road", "Sports complex, Kashmir Road", "shelter", 24.8775, 67.0605, 400, 60),
                   ("s_clifton", "Community centre, Clifton", "shelter", 24.8150, 67.0260, 150, 20),
                   ("s_park_camp", "Tent camp, block 5 park", "shelter", 24.8200, 67.0320, 300, 0),
                   ("h_central", "Central hospital, Saddar", "hospital", 24.8525, 67.0440, None, 0)],
}

SUPPLIES = {  # item, quantity, warn at, unit
    "flood": [("drinking_water", 2000, 400, "L"), ("food_pack", 600, 100, None), ("first_aid_kit", 60, 15, None),
              ("oxygen_cylinder", 8, 5, None), ("insulin", 40, 10, None), ("blanket", 500, 100, None),
              ("life_jacket", 60, 15, None), ("fuel", 400, 80, "L")],
    "heat": [("drinking_water", 3000, 600, "L"), ("oral_rehydration_salts", 400, 80, None),
             ("cooling_pack", 150, 30, None), ("first_aid_kit", 60, 15, None), ("oxygen_cylinder", 8, 5, None),
             ("insulin", 40, 10, None), ("fuel", 300, 80, "L")],
    "earthquake": [("drinking_water", 2000, 400, "L"), ("food_pack", 500, 100, None), ("first_aid_kit", 80, 20, None),
                   ("oxygen_cylinder", 8, 5, None), ("blanket", 800, 150, None), ("tarpaulin", 200, 40, None),
                   ("torch", 100, 20, None), ("fuel", 300, 80, "L")],
}

REGISTRY_SIZE = 200
SHORT = [(r"\bplease\b", "pls"), (r"\byou\b", "u"), (r"\bare\b", "r"), (r"\bpeople\b", "ppl"),
         (r"\bthe\b", ""), (r"\bwith\b", "w"), (r"\bhelp\b", "help!!")]
FILLERS = ["jaldi", "bhai", "plz", "Allah ke liye", "urgent", "", "", ""]


# ---- the town ---------------------------------------------------------------------------------------------
def load_zones() -> list[dict]:
    doc = json.loads((SCENARIO / "zones.geojson").read_text(encoding="utf-8"))
    return [{"name": f["properties"]["name"], "population": f["properties"]["population"],
             "ring": f["geometry"]["coordinates"][0]} for f in doc["features"]]


def inside(ring: list, lng: float, lat: float) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def point_in(rng: random.Random, zone: dict, shrink: float = 0.8) -> tuple[float, float]:
    """A random (lat, lng) inside the zone, away from its edge."""
    xs = [p[0] for p in zone["ring"]]
    ys = [p[1] for p in zone["ring"]]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    while True:
        lng = cx + (rng.uniform(min(xs), max(xs)) - cx) * shrink
        lat = cy + (rng.uniform(min(ys), max(ys)) - cy) * shrink
        if inside(zone["ring"], lng, lat):
            return round(lat, 6), round(lng, 6)


def centre(zone: dict) -> tuple[float, float]:
    xs = [p[0] for p in zone["ring"]]
    ys = [p[1] for p in zone["ring"]]
    return round(sum(ys) / len(ys), 5), round(sum(xs) / len(xs), 5)


def nudge(rng: random.Random, lat: float, lng: float, lo_m: float, hi_m: float) -> tuple[float, float]:
    d, a = rng.uniform(lo_m, hi_m), rng.uniform(0, 2 * math.pi)
    return (round(lat + d * math.sin(a) / 111_320, 6),
            round(lng + d * math.cos(a) / (111_320 * math.cos(math.radians(lat))), 6))


# ---- messages ------------------------------------------------------------------------------------------
def noisy(rng: random.Random, text: str) -> str:
    """The way people text in a panic: short forms, no capitals, the odd Urdu word."""
    out = text
    for pattern, short in SHORT:
        if rng.random() < 0.5:
            out = re.sub(pattern, short, out)
    if rng.random() < 0.6:
        out = out.lower()
    if rng.random() < 0.4:
        out = out.replace(",", "")
    filler = rng.choice(FILLERS)
    if filler:
        out = f"{out} {filler}" if rng.random() < 0.7 else f"{filler} {out}"
    return " ".join(out.split())


def fill(rng: random.Random, template: dict, place: str) -> tuple[str, int]:
    people = template["people"]
    n = rng.randint(*people) if isinstance(people, list) else people
    text = template["text"].format(place=place, n=n, age=rng.randint(68, 88))
    return text, n


def pick_template(rng: random.Random, templates: list[dict]) -> dict:
    weight = {"critical": 1.0, "serious": 1.4, "minor": 1.1, "none": 0.5}
    return rng.choices(templates, [weight[t["truth"]["severity"]] for t in templates])[0]


def arrival_times(rng: random.Random, waves: list[tuple]) -> list[float]:
    times = []
    for start, end, count in waves:
        times += [round(rng.uniform(start, end), 2) for _ in range(count)]
    return sorted(times)


# ---- the pack ------------------------------------------------------------------------------------------
def build_pack(hazard: str, seed: int = 7) -> dict:
    rng = random.Random(f"{hazard}:{seed}")
    story = STORIES[hazard]
    zones = load_zones()
    by_name = {z["name"]: z for z in zones}
    templates = json.loads((SCENARIO / "templates" / f"{hazard}.json").read_text(encoding="utf-8"))["templates"]

    registry = make_registry(rng, zones, story)
    events, people = [], []
    n_sender = 0

    def zone_weights(t: float) -> list[float]:
        out = []
        for z in zones:
            down_at = story["towers_down"].get(z["name"])
            if down_at is not None and t >= down_at:
                out.append(0.0)
                continue
            factor = story["zone_factor"].get(z["name"], story["other_factor"])
            out.append(z["population"] * factor)
        return out

    for t in arrival_times(rng, story["waves"]):
        zone = rng.choices(zones, zone_weights(t))[0]
        template = pick_template(rng, templates)
        place = rng.choice(SPOTS.get(zone["name"], ["the main road"]))
        text, n = fill(rng, template, place)
        lat, lng = point_in(rng, zone)
        truth = template["truth"]
        sid = f"S-{len(people) + 1:03d}"
        deadline = None if truth["deadline_min"] is None else round(truth["deadline_min"] * rng.uniform(0.8, 1.2))
        if truth["severity"] != "none":
            people.append({"id": sid, "zone": zone["name"], "lat": lat, "lng": lng, "people": n,
                           "severity": truth["severity"], "deadline_min": deadline, "starts_at": t,
                           "conditions": template["conditions"], "details": template["details"],
                           "registry_id": None, "reported": True})
        copies = [(t, lat, lng)]
        if rng.random() < story["dup_share"] and truth["severity"] != "none":
            later = round(t + rng.uniform(3, 50), 2)
            if later < story["end"] and zone_weights(later)[zones.index(zone)] > 0:
                copies.append((later, *nudge(rng, lat, lng, 20, 120)))
        for k, (at, la, lo) in enumerate(copies):
            n_sender += 1
            message = noisy(rng, text) if k else text
            event = make_message(rng, hazard, template, message, n, place, la, lo, at, n_sender)
            event["truth"] = {"situation": sid if truth["severity"] != "none" else None, **truth,
                              "deadline_min": deadline}
            events.append(event)

    # Replies to the warning from registered people (held by the replay until an alert is active).
    alert_at = story["alert_at"]
    for person in registry:
        share = story["reply_share"].get(person["zone"])
        if share is None:
            continue
        if rng.random() < share:
            status = rng.choices(["safe", "need_help", "helping"], [85, 8, 7])[0]
            events.append({"t": round(alert_at + rng.uniform(2, 45), 2), "kind": "reply",
                           "device": f"dev_REG{person['id'][2:]}", "registry_id": person["id"], "status": status,
                           "lat": person["lat"], "lng": person["lng"]})
            if status == "need_help":
                people.append(registry_truth(rng, person, hazard, alert_at, reported=True))
        elif person["zone"] in story["alert_zones"]:
            people.append(registry_truth(rng, person, hazard, alert_at, reported=False))

    for t, kind, extra in story["events"]:
        if kind == "volunteer":
            events.append(volunteer_report(rng, by_name, t))
            continue
        events.append({"t": t, "kind": kind, **extra})
    events.sort(key=lambda e: (e["t"], e["kind"] != "cue"))

    teams = []
    for tid, name, ttype, zone_name, fuel in TEAMS[hazard]:
        lat, lng = nudge(rng, *centre(by_name[zone_name]), 100, 600)
        team = {"id": tid, "name": name, "type": ttype, "lat": lat, "lng": lng,
                "device_id": f"dev_{tid.upper().replace('_', '')}"}
        if fuel:
            team["fuel"] = fuel
        teams.append(team)
    places = [{"id": pid, "name": name, "type": kind, "lat": lat, "lng": lng, "capacity": cap, "occupancy": occ}
              for pid, name, kind, lat, lng, cap, occ in PLACES[hazard]]
    for p in places:
        if p["capacity"] is None:
            del p["capacity"]
    supplies = []
    for item, qty, warn, unit in SUPPLIES[hazard]:
        row = {"item": item, "qty": qty, "warn_at": warn}
        if unit:
            row["unit"] = unit
        supplies.append(row)
    windows = [{"t": e["t"], "zone": e["zone"], "closes_in_min": e["closes_in_min"], "text": e["text"]}
               for e in events if e["kind"] == "window"]
    return {
        "pack": {"_note": f"Karachi {hazard} demo pack, made by scenario/generate.py (seed {seed}). All data is made up.",
                 "hazard": hazard, "hard_hit": story["hard_hit"], "start": story["start"], "speed": story["speed"],
                 "alert_zones": story["alert_zones"], "seed": seed},
        "registry": registry, "teams": teams, "shelters": places, "supplies": supplies, "windows": windows,
        "messages": {"start": story["start"], "speed": story["speed"], "events": events},
        "people": people,
    }


def make_message(rng, hazard, template, text, n, place, lat, lng, t, k) -> dict:
    """An app report (with the form filled in) or a plain text message (SMS or a mesh text)."""
    if not template.get("text_only") and rng.random() < 0.55:
        payload = {"hazard": hazard, "for_whom": template["for_whom"], "people": n,
                   "conditions": template["conditions"], "details": template["details"], "note": text[:500],
                   "lat": lat, "lng": lng, "gps_accuracy_m": rng.choice([8, 12, 15, 25, 40]),
                   "landmark": place, "reporter_role": "helper", "contact": ""}
        urgency = 3 if template["truth"]["severity"] == "critical" else 2
        return {"t": t, "kind": "report", "device": f"dev_P{k:04d}", "urgency": urgency, "payload": payload}
    located = rng.random() < 0.5
    return {"t": t, "kind": "text", "sender": f"+000 555 {k:04d}", "text": text,
            "lat": lat if located else None, "lng": lng if located else None, "hazard": None}


def volunteer_report(rng, by_name, t) -> dict:
    lat, lng = point_in(rng, by_name["Lyari"])
    payload = {"hazard": "heat", "for_whom": "other", "people": 1, "conditions": ["elderly", "alone"],
               "details": {"cooling": False, "hot_inside": True, "signs": ["confused", "hot_dry_skin"]},
               "note": "Elderly woman alone, hot dry skin, confused, no fan", "lat": lat, "lng": lng,
               "gps_accuracy_m": 10, "landmark": "Agra Taj colony", "reporter_role": "volunteer", "contact": ""}
    return {"t": t, "kind": "report", "device": "dev_VOLUNTEER1", "urgency": 3, "payload": payload,
            "truth": {"situation": None, "severity": "critical", "deadline_min": 60}}


def make_registry(rng, zones, story) -> list[dict]:
    weights = [z["population"] * (3 if z["name"] in story["alert_zones"] else 1) for z in zones]
    sets, set_weights = zip(*CONDITION_SETS)
    out = []
    for i in range(1, REGISTRY_SIZE + 1):
        zone = rng.choices(zones, weights)[0]
        lat, lng = point_in(rng, zone)
        out.append({"id": f"R-{i:04d}", "name": f"Demo Resident {i}", "zone": zone["name"], "lat": lat, "lng": lng,
                    "conditions": rng.choices(sets, set_weights)[0],
                    "phone": f"+000 555 {9000 + i}" if rng.random() < 0.7 else "",
                    "consent_at": "2026-06-15T10:00:00Z"})
    return out


def registry_truth(rng, person, hazard, alert_at, reported) -> dict:
    """A registered person who may need help: the hidden truth for the simulation."""
    conds = person["conditions"].split(";")
    risky = any(c in conds for c in ("oxygen", "power_dependent", "cannot_walk", "dialysis"))
    if hazard == "heat":
        severity = "critical" if ("elderly" in conds and "alone" in conds) or risky else "serious"
        deadline = 240 if severity == "critical" else 420
    else:
        severity = "serious" if risky else "minor"
        deadline = 300 if risky else 720
    return {"id": f"S-{person['id']}", "zone": person["zone"], "lat": person["lat"], "lng": person["lng"],
            "people": 1, "severity": severity, "deadline_min": round(deadline * rng.uniform(0.8, 1.2)),
            "starts_at": alert_at, "conditions": conds, "details": {}, "registry_id": person["id"],
            "reported": reported}


def write_pack(hazard: str, data: dict) -> Path:
    folder = SCENARIO / "packs" / hazard
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("pack", "teams", "shelters", "supplies", "windows", "messages", "people"):
        (folder / f"{name}.json").write_text(json.dumps(data[name], indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "name", "zone", "lat", "lng", "conditions", "phone", "consent_at"])
    for p in data["registry"]:
        w.writerow([p["id"], p["name"], "", p["lat"], p["lng"], p["conditions"], p["phone"], p["consent_at"]])
    (folder / "registry.csv").write_text(buf.getvalue(), encoding="utf-8")
    return folder


def summary(hazard: str, data: dict) -> str:
    events = data["messages"]["events"]
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    critical = sum(1 for p in data["people"] if p["severity"] == "critical")
    return (f"{hazard}: {len(events)} events ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))}); "
            f"{len(data['registry'])} registered; {len(data['people'])} situations ({critical} critical)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Karachi scenario packs.")
    parser.add_argument("--pack", choices=PACKS + ("all",), default="all")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    for hazard in PACKS if args.pack == "all" else (args.pack,):
        data = build_pack(hazard, args.seed)
        folder = write_pack(hazard, data)
        print(summary(hazard, data), "->", folder.relative_to(SCENARIO.parent))


if __name__ == "__main__":
    main()

"""Suggest, trade-off and assign (System Design 9.6; Team Brief 3.9 i)."""
import copy
from datetime import timedelta

from conftest import Phone

from app import timeutil
from app.config import SHARED_DIR
from app.devtools import load_example

M = 1 / 111_195
HOUSE = (0.0123, 0.0456)


def add_team(client, tid, kind="boat", south_m=1500, **extra) -> None:
    body = {"id": tid, "name": tid.replace("_", " ").title(), "type": kind, "lat": HOUSE[0] - south_m * M,
            "lng": HOUSE[1], **extra}
    assert client.post("/api/teams", json=body).status_code == 200


def fleet(client) -> None:
    """Boat 2 (with a nurse) 1.5 km away, Boat 4 (with a nurse) 4 km, Boat 3 (no medic) 0.5 km, Truck 1 0.3 km."""
    add_team(client, "boat_2", skills=["nurse_doctor"], device_id="dev_BOAT2")
    add_team(client, "boat_4", south_m=4000, skills=["nurse_doctor"])
    add_team(client, "boat_3", south_m=500)
    add_team(client, "truck_1", kind="truck", south_m=300)


def house_14(client, phone) -> int:
    phone.send(phone.wire("report"))
    return next(c["id"] for c in client.get("/api/snapshot").json()["cases"] if "house 14" in (c["landmark"] or ""))


def roof(client, south_m=1400) -> int:
    """Six people on a roof, near Boat 2: ranked first and best served by Boat 2."""
    p = copy.deepcopy(load_example(SHARED_DIR, "report")["payload"])
    p.update(lat=HOUSE[0] - south_m * M, details={"water": "roof", "rising": True}, people=6,
             conditions=["infant", "cannot_walk", "elderly", "alone"], landmark="Riverside roof")
    p.pop("note", None)
    other = Phone(client, "dev_ROOF")
    other.send(other.wire("report", payload=p))
    return next(c["id"] for c in client.get("/api/snapshot").json()["cases"] if c["landmark"] == "Riverside roof")


def suggest(client, case_id) -> dict:
    resp = client.get(f"/api/suggest?case_id={case_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_fastest_free_team_that_can_help(client, phone, schemas):
    fleet(client)
    out = suggest(client, house_14(client, phone))
    assert schemas.errors("suggestion", out) == []
    assert set(out["needs"]) == {"boat", "medic"} and out["supplies"] == ["oxygen_cylinder"] and out["rank"] == 1
    assert (out["best"]["team_id"], out["best"]["travel_min"], out["best"]["distance_km"]) == ("boat_2", 13, 1.5)
    assert [a["team_id"] for a in out["alternatives"]] == ["boat_4"]
    assert out["tradeoff"] is None and out["why_none"] is None


def test_the_tradeoff_names_the_case_that_would_wait(client, phone):
    fleet(client)
    house, top = house_14(client, phone), roof(client)
    assert client.get("/api/snapshot").json()["cases"][0]["id"] == top
    out = suggest(client, house)
    assert out["rank"] == 2 and out["tradeoff_case_id"] == top
    assert out["tradeoff"] == "Boat 2 is also best for case #1. If it goes here, #1 waits about 7 more min (next best: Boat 3)"


def test_low_fuel_busy_and_broken_teams_are_not_suggested(client, phone):
    fleet(client)
    case_id = house_14(client, phone)
    client.post("/api/teams", json={"id": "boat_2", "fuel": "low"})
    assert suggest(client, case_id)["best"]["team_id"] == "boat_4"
    client.post("/api/teams/boat_4/status", json={"status": "out_of_service", "reason": "engine fault"})
    out = suggest(client, case_id)
    assert out["best"] is None and out["why_none"] == "no free team can do boat + medic"


def test_a_team_must_carry_or_be_able_to_fetch_the_supplies(client, phone):
    fleet(client)
    case_id = house_14(client, phone)
    client.post("/api/supplies/move", json={"kind": "restock", "item": "oxygen_cylinder", "qty": 1})
    client.post("/api/supplies/move", json={"kind": "load", "item": "oxygen_cylinder", "qty": 1, "to": "team:boat_4"})
    out = suggest(client, case_id)                               # none at the command post: only Boat 4 has one
    assert out["best"]["team_id"] == "boat_4" and out["best"]["fetch"] == [] and out["alternatives"] == []
    client.post("/api/supplies/move", json={"kind": "restock", "item": "oxygen_cylinder", "qty": 2})
    out = suggest(client, case_id)
    assert out["best"]["team_id"] == "boat_2" and out["best"]["fetch"] == ["oxygen_cylinder"]


def test_teams_about_to_be_free(client, phone):
    fleet(client)
    top = roof(client)
    client.post("/api/assign", json={"case_id": top, "team_id": "boat_4"})
    ctx = client.app.state.ctx
    ctx.teams.set_status("boat_4", "on_scene", None, "test", now=timeutil.now() - timedelta(minutes=15))
    out = suggest(client, house_14(client, phone))
    assert [(t["team_id"], t["free_in_min"]) for t in out["soon_free"]] == [("boat_4", 5)]


def test_nearest_place_with_space(client, phone):
    fleet(client)
    for sid, kind, south, cap, occ in (("church", "shelter", 500, 50, 50), ("school", "shelter", 2000, 200, 64),
                                        ("hall", "cooling_centre", 100, 120, 0)):
        client.post("/api/shelters", json={"id": sid, "name": sid.title(), "type": kind, "lat": HOUSE[0] - south * M,
                                           "lng": HOUSE[1], "capacity": cap, "occupancy": occ})
    place = suggest(client, house_14(client, phone))["place"]
    assert (place["id"], place["space_left"], place["distance_km"]) == ("school", 136, 2.0)   # church is full
    vol = Phone(client, "dev_VOL07")
    vol.send(vol.wire("report_heat"))
    heat = next(c["id"] for c in client.get("/api/snapshot").json()["cases"] if c["hazard"] == "heat")
    assert suggest(client, heat)["place"]["id"] == "hall"


def test_why_there_is_no_suggestion(client, phone):
    case_id = house_14(client, phone)
    assert suggest(client, case_id)["why_none"] == "no team is free"
    p = copy.deepcopy(load_example(SHARED_DIR, "report")["payload"])
    p.update(lat=None, lng=None, gps_accuracy_m=None, landmark="Old mill by the canal")
    phone.send(phone.wire("report", payload=p))
    blind = next(c["id"] for c in client.get("/api/snapshot").json()["cases"] if c["lat"] is None)
    assert suggest(client, blind)["why_none"] == "the case has no position yet; choose a team by hand"
    assert client.get("/api/suggest?case_id=999").status_code == 404


def test_suggest_all_gives_each_team_once_down_the_list(client, phone):
    fleet(client)
    house, top = house_14(client, phone), roof(client)
    plans = client.get("/api/suggest/all").json()["plans"]
    assert [(p["case_id"], p["team"]["team_id"]) for p in plans] == [(top, "boat_2"), (house, "boat_4")]


def test_assign_rules(client, phone):
    fleet(client)
    case_id = house_14(client, phone)

    def post(body, status=200):
        resp = client.post("/api/assign", json=body)
        assert resp.status_code == status, resp.text
        return resp.json()

    assert "Boat 3 cannot do medic" in post({"case_id": case_id, "team_id": "boat_3"})["warnings"]
    assert "already has team boat_3" in post({"case_id": case_id, "team_id": "boat_2"}, 400)["detail"]
    out = post({"case_id": case_id, "team_id": "boat_2", "reassign": True})
    assert out["job_id"] == "J-002" and out["outbound_seq"] == 1
    teams = {t["id"]: t for t in client.get("/api/teams").json()["teams"]}
    assert teams["boat_3"]["status"] == "available" and teams["boat_2"]["status"] == "assigned"
    assert "Boat 2 is assigned, not available" in post({"case_id": case_id, "team_id": "boat_2", "reassign": True},
                                                       400)["detail"]
    other = roof(client)
    post({"case_id": other, "team_id": "boat_4", "place": "nowhere"}, 404)
    assert client.post("/api/assign", json={"case_id": 999, "team_id": "boat_4"}).status_code == 404

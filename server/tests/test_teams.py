"""Team tracker: setup, pings, acks, arrival, outcome, overdue (System Design 9.7 and 13.1; Team Brief 3.7)."""
import copy
import json
from datetime import timedelta

import pytest
from conftest import Phone

from app import timeutil
from app.config import SHARED_DIR
from app.crypto import verify
from app.devtools import load_example
from app.teams import capabilities, travel_minutes

M = 1 / 111_195                       # degrees of latitude per metre
HOUSE = (0.0123, 0.0456)              # house 14 in the example report


def add_team(client, tid, kind="boat", south_m=1500, device=None, **extra) -> dict:
    body = {"id": tid, "name": tid.replace("_", " ").title(), "type": kind, "lat": HOUSE[0] - south_m * M,
            "lng": HOUSE[1], "device_id": device, **extra}
    resp = client.post("/api/teams", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def team(client, tid) -> dict:
    return next(t for t in client.get("/api/teams").json()["teams"] if t["id"] == tid)


def house_14(client, phone) -> int:
    phone.send(phone.wire("report"))
    return client.get("/api/snapshot").json()["cases"][0]["id"]


def assign(client, case_id, team_id="boat_2", **extra) -> dict:
    resp = client.post("/api/assign", json={"case_id": case_id, "team_id": team_id, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def ack(boat, status, job_id=None, team_id="boat_2", **extra) -> None:
    out = boat.send(boat.wire("ack", payload={"team_id": team_id, "job_id": job_id, "status": status, **extra}))
    assert out["accepted"], out


def ping(boat, lat, lng, at=None, team_id="boat_2", **extra) -> None:
    payload = {"team_id": team_id, "lat": lat, "lng": lng, "gps_accuracy_m": 10,
               "at": timeutil.iso(at or timeutil.now()), "status": "en_route", "battery": 64, "fuel": "half", **extra}
    assert boat.send(boat.wire("team_ping", payload=payload))["accepted"]


def case(client, case_id) -> dict:
    return client.get(f"/api/cases/{case_id}").json()


# ---- pure ---------------------------------------------------------------------------------------------
def test_capabilities_come_from_type_and_skills(constants):
    assert capabilities("boat", ["nurse_doctor", "first_aid"], constants) == ["boat", "medic", "welfare"]
    assert capabilities("volunteer", [], constants) == ["welfare"]
    assert capabilities("truck", ["4x4"], constants) == ["truck", "evac", "welfare"]


def test_a_boat_1_5_km_away_takes_about_13_minutes():
    assert round(travel_minutes(HOUSE[0] - 1500 * M, HOUSE[1], *HOUSE, 10, 1.4)) == 13


# ---- setup -------------------------------------------------------------------------------------------
def test_volunteer_packets_make_or_claim_teams(client, schemas):
    add_team(client, "boat_3")                                      # made by the dispatcher, no phone yet
    b3 = Phone(client, "dev_B3")
    b3.send(b3.wire("volunteer", payload={"name": "Boat 3", "role": "rescue_team", "team_type": "boat",
                                          "skills": ["boat"]}))
    assert team(client, "boat_3")["device_id"] == "dev_B3"
    boat = Phone(client, "dev_BOAT2")
    boat.send(boat.wire("volunteer"), boat.wire("volunteer"))     # the example: Boat 2, nurse on board
    b2 = team(client, "boat_2")
    assert (b2["device_id"], b2["capabilities"], b2["status"]) == ("dev_BOAT2", ["boat", "medic", "welfare"], "available")
    assert (b2["lat"], b2["lng"], b2["speed_kmh"]) == (0.005, 0.03, 10)
    other = Phone(client, "dev_OTHER")
    other.send(other.wire("volunteer"))
    teams = client.get("/api/teams").json()["teams"]
    assert sorted(t["id"] for t in teams) == ["boat_2", "boat_2_2", "boat_3"]
    assert all(schemas.errors("team", t) == [] for t in teams)
    resp = client.post("/api/teams", json={"id": "boat_9", "name": "Boat 9", "type": "boat", "device_id": "dev_BOAT2"})
    assert resp.status_code == 400 and "already belongs to team boat_2" in resp.json()["detail"]
    assert client.post("/api/teams", json={"name": "Raft", "type": "raft"}).status_code == 400


# ---- a job from start to finish --------------------------------------------------------------------------
def test_a_job_from_assign_to_back_at_base(client, phone, schemas):
    client.post("/api/shelters", json={"id": "school", "name": "School shelter", "type": "shelter",
                                       "lat": 0.009, "lng": 0.035, "capacity": 200, "occupancy": 64})
    add_team(client, "boat_2", device="dev_BOAT2", skills=["nurse_doctor"])
    client.post("/api/supplies/move", json={"kind": "restock", "item": "oxygen_cylinder", "qty": 5})
    client.post("/api/supplies/move", json={"kind": "load", "item": "oxygen_cylinder", "qty": 2, "to": "team:boat_2"})
    case_id = house_14(client, phone)
    out = assign(client, case_id, place="school")
    assert (out["job_id"], out["travel_min"], out["to_device"], out["warnings"]) == ("J-001", 13, "dev_BOAT2", [])

    [wire] = client.get("/api/outbound?since=0").json()["packets"]
    body = json.loads(wire["body"])
    assert verify(client.app.state.ctx.keys.sign_pk, wire["body"], wire["sig"])
    assert (body["kind"], body["to_device"], body["urgency"]) == ("job", "dev_BOAT2", 3)
    job = body["public"]
    assert schemas.errors("payloads/job", job) == [] and job["eta"] == out["eta"]
    assert job["summary"] == "1 person, elderly, cannot walk, needs oxygen, alone; water at waist and rising"
    assert job["place"] == {"id": "school", "name": "School shelter", "lat": 0.009, "lng": 0.035}
    assert case(client, case_id)["case"]["status"] == "assigned" and team(client, "boat_2")["status"] == "assigned"

    boat = Phone(client, "dev_BOAT2")
    ack(boat, "en_route", "J-001")
    assert team(client, "boat_2")["status"] == "en_route" and case(client, case_id)["case"]["status"] == "en_route"
    ping(boat, HOUSE[0] - 80 * M, HOUSE[1])                        # 80 m from the case: on scene
    b2 = team(client, "boat_2")
    assert b2["status"] == "on_scene" and b2["arrived_at"] is not None and b2["battery"] == 64
    ack(boat, "arrived", "J-001")                                   # the team taps Arrived as well
    ack(boat, "en_route", "J-001")                                  # a late copy from the mesh: ignored
    assert team(client, "boat_2")["status"] == "on_scene"
    actions = [h["action"] for h in case(client, case_id)["history"]]
    assert actions[-3:] == ["en_route", "on_scene", "arrival_confirmed"]

    ack(boat, "done", "J-001", outcome={"people_helped": 1, "taken_to": "school",
                                        "supplies_used": {"oxygen_cylinder": 1}})
    assert case(client, case_id)["case"]["status"] == "done"
    assert client.get("/api/snapshot").json()["cases"] == []
    b2 = team(client, "boat_2")
    assert b2["status"] == "returning" and b2["job_id"] is None and b2["load"] == {"oxygen_cylinder": 1}
    assert client.get("/api/shelters").json()["shelters"][0]["occupancy"] == 65
    oxygen = client.get("/api/supplies").json()["supplies"][0]
    assert (oxygen["left"], oxygen["used_today"], oxygen["teams"]) == (4, 1, 1)
    ping(boat, HOUSE[0] - 1490 * M, HOUSE[1])                       # back at base
    assert team(client, "boat_2")["status"] == "available"
    snap = client.get("/api/snapshot").json()
    assert schemas.errors("snapshot", snap) == []


def test_acks_from_strangers_or_for_old_jobs_change_nothing(client, phone):
    add_team(client, "boat_2", device="dev_BOAT2", skills=["nurse_doctor"])
    case_id = house_14(client, phone)
    assign(client, case_id)
    stranger = Phone(client, "dev_NOBODY")
    ack(stranger, "done", "J-001")
    ack(Phone(client, "dev_BOAT2"), "en_route", "J-999")
    assert team(client, "boat_2")["status"] == "assigned"
    with client.app.state.ctx.db.read() as conn:
        ignored = [r[0] for r in conn.execute("SELECT target FROM audit_log WHERE action = 'ack_ignored'")]
    assert ignored == ["device:dev_NOBODY", "team:boat_2"]


def test_cant_reach_puts_the_case_back_in_the_queue(client, phone):
    add_team(client, "boat_2", device="dev_BOAT2", skills=["nurse_doctor"])
    case_id = house_14(client, phone)
    assign(client, case_id)
    ack(Phone(client, "dev_BOAT2"), "cant_reach", "J-001", reason="Bridge flooded")
    c = case(client, case_id)
    assert c["case"]["status"] == "new" and c["case"]["team_id"] is None
    assert c["history"][-1]["detail"] == "Boat 2: Bridge flooded"
    assert team(client, "boat_2")["status"] == "available"


def test_out_of_service_until_ready(client, phone):
    add_team(client, "boat_2", device="dev_BOAT2", skills=["nurse_doctor"])
    case_id = house_14(client, phone)
    assign(client, case_id)
    boat = Phone(client, "dev_BOAT2")
    ack(boat, "out_of_service", reason="Engine fault")
    assert team(client, "boat_2")["status"] == "out_of_service"
    assert case(client, case_id)["case"]["status"] == "new"
    assert client.get(f"/api/suggest?case_id={case_id}").json()["best"] is None
    ack(boat, "ready")
    assert team(client, "boat_2")["status"] == "available"


def test_overdue_and_not_heard_from(client, phone):
    add_team(client, "boat_2", device="dev_BOAT2", skills=["nurse_doctor"])
    case_id = house_14(client, phone)
    out = assign(client, case_id, eta_min=30)
    ctx = client.app.state.ctx
    start = timeutil.parse(out["eta"]) - timedelta(minutes=30)
    assert ctx.teams.checks(start + timedelta(minutes=42)) == 0                 # ETA + 40%
    assert ctx.teams.checks(start + timedelta(minutes=48)) == 1                 # ETA + 60%
    assert team(client, "boat_2")["flags"] == ["overdue"]
    warnings = client.get("/api/snapshot").json()["summary"]["warnings"]
    assert any(w.startswith("Boat 2 overdue: ETA ") and w.endswith("1.5 km away") for w in warnings)

    boat = Phone(client, "dev_BOAT2")
    ack(boat, "en_route", "J-001")
    ping(boat, HOUSE[0] - 1000 * M, HOUSE[1])
    ctx.teams.checks(start + timedelta(minutes=48))                             # and no ping for 48 min
    assert team(client, "boat_2")["flags"] == ["not_heard_from", "overdue"]
    ping(boat, HOUSE[0] - 900 * M, HOUSE[1])
    assert team(client, "boat_2")["flags"] == ["overdue"]


def test_dispatcher_sets_a_status_by_hand(client, phone):
    add_team(client, "boat_2", skills=["nurse_doctor"])               # reached by radio: no phone
    case_id = house_14(client, phone)
    out = assign(client, case_id)
    assert out["warnings"] == ["Boat 2 has no phone: tell them by radio"] and out["outbound_seq"] is None

    def status(body):
        return client.post("/api/teams/boat_2/status", json=body)

    assert status({"status": "out_of_service"}).status_code == 400            # needs a reason
    assert status({"status": "assigned"}).status_code == 400
    assert status({"status": "on_scene"}).json()["status"] == "on_scene"
    assert status({"status": "returning"}).json()["status"] == "returning"
    assert case(client, case_id)["case"]["status"] == "done"
    assert status({"status": "en_route"}).status_code == 400                  # no job any more
    assert client.post("/api/teams/boat_9/status", json={"status": "available"}).status_code == 404


def test_only_the_newest_position_counts_and_a_trail_is_kept(client):
    add_team(client, "boat_2", device="dev_BOAT2")
    boat = Phone(client, "dev_BOAT2")
    now = timeutil.now()
    for i in range(7):
        ping(boat, 0.001 * i, 0.03, at=now - timedelta(minutes=20 - i))
    ping(boat, 0.5, 0.5, at=now - timedelta(minutes=30))                     # old, relayed late
    b2 = team(client, "boat_2")
    assert (b2["lat"], b2["ping_at"]) == (0.006, timeutil.iso(now - timedelta(minutes=14)))
    assert [p["lat"] for p in b2["trail"]] == [0.006, 0.005, 0.004, 0.003, 0.002]
    assert b2["stale"] and b2["last_contact"] is not None
    ping(boat, 0.007, 0.03)
    assert not team(client, "boat_2")["stale"]

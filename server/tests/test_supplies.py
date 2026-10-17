"""Supplies, burn rate and shelters (System Design 9.8; Team Brief 3.7)."""
from datetime import timedelta

import pytest

from app import timeutil


def move(client, status=200, **body) -> dict:
    resp = client.post("/api/supplies/move", json=body)
    assert resp.status_code == status, resp.text
    return resp.json()


def add_places(client) -> None:
    client.post("/api/teams", json={"id": "boat_2", "name": "Boat 2", "type": "boat", "lat": 0.0, "lng": 0.0})
    client.post("/api/shelters", json={"id": "school", "name": "School", "type": "shelter", "lat": 0.01,
                                       "lng": 0.03, "capacity": 200, "occupancy": 64})


def test_every_movement_is_logged_and_stock_follows(client, schemas):
    add_places(client)
    water = move(client, kind="restock", item="drinking_water", qty=100)
    assert (water["unit"], water["command_post"], water["left"]) == ("L", 100, 100)
    move(client, kind="load", item="drinking_water", qty=30, to="team:boat_2")
    move(client, kind="deliver", item="drinking_water", qty=40, to="shelter:school")
    move(client, kind="used", item="drinking_water", qty=10, **{"from": "shelter:school"})
    move(client, kind="unload", item="drinking_water", qty=5, **{"from": "team:boat_2"})
    water = move(client, kind="transfer", item="drinking_water", qty=5, **{"from": "shelter:school", "to": "team:boat_2"})
    assert schemas.errors("supply", water) == []
    assert water["places"] == {"command_post": 35, "shelter:school": 25, "team:boat_2": 30}
    assert (water["left"], water["used_today"], water["per_hour"]) == (90, 10, round(10 / 3, 2))
    assert client.get("/api/teams").json()["teams"][0]["load"] == {"drinking_water": 30}
    with client.app.state.ctx.db.read() as conn:
        kinds = [r[0] for r in conn.execute("SELECT reason FROM supply_moves ORDER BY id")]
    assert kinds == ["restock", "load", "deliver", "used", "unload", "transfer"]


@pytest.mark.parametrize("body, status, message", [
    ({"kind": "load", "item": "fuel", "qty": 1, "to": "team:boat_2"}, 400, "only 0 fuel at command_post"),
    ({"kind": "load", "item": "fuel", "qty": 1, "to": "shelter:school"}, 400, "goes to a team"),
    ({"kind": "deliver", "item": "fuel", "qty": 1, "to": "team:boat_9"}, 400, "goes to a shelter"),
    ({"kind": "restock", "item": "fuel", "qty": 1, "to": "team:boat_9"}, 404, "unknown team boat_9"),
    ({"kind": "restock", "item": "fuel", "qty": 1, "to": "garage"}, 400, "place must be"),
    ({"kind": "restock", "item": "fuel", "qty": 1, "from": "command_post"}, 400, "has no 'from' place"),
    ({"kind": "transfer", "item": "fuel", "qty": 1, "to": "command_post"}, 400, "needs a 'from' place"),
])
def test_bad_moves_are_refused(client, body, status, message):
    add_places(client)
    assert message in move(client, status, **body)["detail"]


def test_burn_rate_and_low_stock(client):
    ctx = client.app.state.ctx
    now = timeutil.now()
    ctx.supplies.move({"kind": "restock", "item": "oxygen_cylinder", "qty": 10}, "test", now - timedelta(hours=5))
    ctx.supplies.move({"kind": "used", "item": "oxygen_cylinder", "qty": 1}, "test", now - timedelta(hours=4))
    for hours in (2.5, 1.5, 0.5):
        ctx.supplies.move({"kind": "used", "item": "oxygen_cylinder", "qty": 2}, "test", now - timedelta(hours=hours))
    oxygen = client.post("/api/supplies", json={"item": "oxygen_cylinder", "warn_at": 5}).json()
    assert (oxygen["left"], oxygen["per_hour"], oxygen["runs_out_in_hours"], oxygen["low"]) == (3, 2, 1.5, True)
    warnings = client.get("/api/snapshot").json()["summary"]["warnings"]
    assert "Oxygen cylinder: 3 left (warn at 5), runs out in about 1.5 h" in warnings
    assert client.get("/api/resources/summary").json()["warnings"] == warnings


def test_shelters_count_people_and_name_the_next_place(client, schemas):
    add_places(client)
    client.post("/api/shelters", json={"id": "church", "name": "Church", "type": "shelter", "lat": 0.012,
                                       "lng": 0.031, "capacity": 80, "occupancy": 10})
    school = client.post("/api/shelters", json={"id": "school", "occupancy": 185}).json()
    assert schemas.errors("shelter", school) == []
    assert (school["name"], school["space_left"], school["nearly_full"], school["next"]) == (
        "School", 15, True, {"id": "church", "name": "Church"})
    assert "School nearly full (185/200); next: Church" in client.get("/api/snapshot").json()["summary"]["warnings"]
    assert client.post("/api/shelters", json={"id": "tent"}).status_code == 400            # a new place needs a name
    assert client.post("/api/shelters", json={"id": "tent", "name": "Tent", "type": "tent"}).status_code == 422

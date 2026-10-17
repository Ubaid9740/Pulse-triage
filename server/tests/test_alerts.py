"""Alerts: create, update, cancel, expire and announce (System Design 8.3; Team Brief 3.2)."""
import copy
import json
from datetime import timedelta

import pytest
from conftest import Phone, load_registry, load_zones

from app import timeutil
from app.config import SHARED_DIR
from app.crypto import verify
from app.devtools import load_example

FLOOD_WARNING = {"hazard": "flood", "severity": "warning", "zones": ["Ward 4", "Riverside"]}
HEAT_WARNING = {"hazard": "heat", "severity": "warning", "zones": ["Ward 4", "Old Market"],
                "fill": {"start": "12:00", "end": "17:00"}}


def post(client, body, status=200) -> dict:
    resp = client.post("/api/alerts", json=body)
    assert resp.status_code == status, resp.text
    return resp.json()


def add_shelter(client, sid, kind, lat, lng, capacity, occupancy=0, name=None):
    with client.app.state.ctx.db.write() as conn:
        conn.execute("INSERT INTO shelters(id, name, type, lat, lng, capacity, occupancy) VALUES(?, ?, ?, ?, ?, ?, ?)",
                     (sid, name or sid.replace("_", " ").title(), kind, lat, lng, capacity, occupancy))


def outbound_bodies(client) -> list[dict]:
    return [json.loads(w["body"]) for w in client.get("/api/outbound?since=0").json()["packets"]]


# ---- a new alert ----------------------------------------------------------------------------------------
def test_new_alert_is_filled_from_the_template_signed_and_queued(client, schemas):
    load_zones(client)
    out = post(client, FLOOD_WARNING)
    assert out["alert_id"] == "A-0001" and out["outbound_seq"] == 1
    alert = out["alert"]
    assert schemas.errors("alert_summary", alert) == []
    assert alert["headline"] == {"en": "Flood warning for Ward 4 and Riverside"}
    assert alert["do_now"]["en"][2] == "Do not walk or drive through floodwater"
    assert alert["status"] == "active" and alert["places"] == []

    [wire] = client.get("/api/outbound?since=0").json()["packets"]
    body = json.loads(wire["body"])
    assert schemas.errors("wire", wire) == [] and schemas.errors("body", body) == []
    assert verify(client.app.state.ctx.keys.sign_pk, wire["body"], wire["sig"])
    assert (body["kind"], body["urgency"], body["replace_key"]) == ("alert", 4, "alert:A-0001")
    assert body["public"]["alert_id"] == "A-0001" and body["expires_at"] == alert["valid_until"]
    assert body["area"] != "0" and len(body["area"]) == 5
    assert schemas.errors("payloads/alert", body["public"]) == []
    issued = timeutil.parse(alert["issued_at"])
    assert timeutil.parse(alert["valid_until"]) - issued == timedelta(hours=12)


def test_heat_template_needs_its_hours(client):
    load_zones(client)
    body = dict(HEAT_WARNING, fill={})
    assert "{start}" in post(client, body, 400)["detail"]
    alert = post(client, HEAT_WARNING)["alert"]
    assert alert["headline"]["en"] == "Extreme heat in Ward 4 and Old Market, 12:00-17:00"


def test_the_dispatcher_can_write_their_own_text(client):
    load_zones(client)
    assert "no earthquake watch template" in post(client, {"hazard": "earthquake", "severity": "watch",
                                                           "zones": ["Ward 4"]}, 400)["detail"]
    alert = post(client, {"hazard": "earthquake", "severity": "watch", "zones": ["Ward 4"],
                          "headline": {"en": "Tremors felt; be ready", "ur": "Zalzala"},
                          "do_now": {"en": ["Keep shoes and a torch by the bed"], "ur": ["..."]}})["alert"]
    assert alert["headline"]["ur"] == "Zalzala" and alert["do_now"]["en"] == ["Keep shoes and a torch by the bed"]
    detail = post(client, dict(FLOOD_WARNING, languages=["en", "ur"]), 400)["detail"]
    assert "no flood warning template in ur" in detail


def test_places_default_to_the_nearest_with_space(client):
    load_zones(client)
    add_shelter(client, "school", "shelter", 0.016, 0.041, 200, 64)
    add_shelter(client, "far_school", "shelter", 0.090, 0.090, 100)
    add_shelter(client, "full_church", "shelter", 0.015, 0.040, 10, 10)
    add_shelter(client, "cool_hall", "cooling_centre", 0.015, 0.041, 120, name="Community hall")
    flood = post(client, FLOOD_WARNING)["alert"]
    assert [(p["id"], p["space_left"]) for p in flood["places"]] == [("school", 136), ("far_school", 100)]
    heat = post(client, HEAT_WARNING)["alert"]
    assert [p["id"] for p in heat["places"]] == ["cool_hall", "school"]
    chosen = post(client, dict(FLOOD_WARNING, places=["cool_hall"]))["alert"]
    assert chosen["places"] == [{"id": "cool_hall", "name": "Community hall", "type": "cooling_centre",
                                 "lat": 0.015, "lng": 0.041, "space_left": 120}]
    assert "unknown places: nowhere" in post(client, dict(FLOOD_WARNING, places=["nowhere"]), 400)["detail"]


@pytest.mark.parametrize("change, message", [
    ({"zones": ["Atlantis"]}, "unknown zones: Atlantis"),
    ({"valid_until": "2020-01-01T00:00:00Z"}, "must be in the future"),
    ({"valid_until": "2099-01-01T00:00:00Z"}, "at most 72 hours"),
    ({"hazard": None}, "needs hazard, severity and zones"),
])
def test_bad_alerts_are_refused(client, change, message):
    load_zones(client)
    assert message in post(client, dict(FLOOD_WARNING, **change), 400)["detail"]
    assert client.get("/api/outbound?since=0").json()["packets"] == []


def test_zones_must_be_loaded_first(client):
    assert "POST /api/zones/import" in post(client, FLOOD_WARNING, 400)["detail"]


def test_preview_queues_nothing(client, schemas):
    load_zones(client)
    preview = client.post("/api/alerts/preview", json=FLOOD_WARNING).json()
    assert schemas.errors("payloads/alert", preview) == [] and preview["alert_id"] == "A-0001"
    assert client.get("/api/outbound?since=0").json()["packets"] == [] and client.get("/api/alerts").json() == {"alerts": []}


# ---- updates and the all-clear --------------------------------------------------------------------------
def test_update_keeps_what_it_does_not_change(client):
    load_zones(client)
    first = post(client, FLOOD_WARNING)["alert"]
    later = timeutil.iso(timeutil.now() + timedelta(hours=20))
    second = post(client, {"replaces": "A-0001", "valid_until": later})["alert"]
    assert second["id"] == "A-0002" and second["headline"] == first["headline"] and second["zones"] == first["zones"]
    assert second["valid_until"] == later and second["replaces"] == "A-0001"
    third = post(client, {"replaces": "A-0002", "severity": "emergency"})["alert"]
    assert third["headline"]["en"] == "Flood emergency: Ward 4 and Riverside. Act now."
    assert [a["status"] for a in client.get("/api/alerts").json()["alerts"]] == ["active", "replaced", "replaced"]
    assert {b["replace_key"] for b in outbound_bodies(client)} == {"alert:A-0001"}    # relays keep the newest
    assert "A-0001 is replaced" in post(client, {"replaces": "A-0001", "severity": "watch"}, 400)["detail"]
    assert client.post("/api/alerts", json={"replaces": "A-0999"}).status_code == 404


def test_all_clear_ends_the_alert(client, schemas):
    load_zones(client)
    client.post("/api/settings/hazard", json={"hazard": "heat"})
    post(client, HEAT_WARNING)
    zones = {z["name"]: z for z in client.get("/api/zones").json()["zones"]}
    assert zones["Ward 4"]["hard_hit"]
    assert "needs 'replaces'" in post(client, {"cancel": True}, 400)["detail"]
    clear = post(client, {"replaces": "A-0001", "cancel": True})["alert"]
    assert clear["headline"] == {"en": "All clear for Ward 4 and Old Market"} and clear["cancel"]
    assert clear["status"] == "all_clear" and clear["severity"] == "warning"
    snap = client.get("/api/snapshot").json()
    assert [a["id"] for a in snap["alerts"]] == ["A-0002"] and schemas.errors("snapshot", snap) == []
    assert not any(z["hard_hit"] for z in snap["zones"])
    assert client.get("/api/alerts/A-0001").json()["status"] == "cancelled"
    assert "only an active alert" in post(client, {"replaces": "A-0002", "cancel": True}, 400)["detail"]


def test_alerts_expire(client):
    load_zones(client)
    post(client, dict(FLOOD_WARNING, valid_until=timeutil.iso(timeutil.now() + timedelta(hours=1))))
    ctx = client.app.state.ctx
    later = timeutil.now() + timedelta(hours=2)
    assert ctx.alerts.expire(later) == 1 and ctx.alerts.expire(later) == 0
    assert client.get("/api/alerts/A-0001").json()["status"] == "expired"
    assert client.get("/api/snapshot").json()["alerts"] == []
    assert client.get("/api/alerts/A-0404").status_code == 404


# ---- replies, coverage and timeouts ------------------------------------------------------------------------
def test_alert_view_counts_replies_and_coverage(client, phone, schemas):
    load_zones(client)
    load_registry(client)
    post(client, FLOOD_WARNING)
    reply = copy.deepcopy(load_example(SHARED_DIR, "alert_reply")["payload"])
    phone.send(phone.wire("alert_reply", payload=dict(reply, alert_id="A-0001", registry_id="R-0007")),
               phone.wire("alert_reply", payload=dict(reply, alert_id="A-0001", status="need_help")),
               phone.wire("alert_reply", payload=dict(reply, alert_id="A-0001", status="helping")))
    post(client, {"replaces": "A-0001", "severity": "emergency"})
    phone.send(phone.wire("alert_reply", payload=dict(reply, alert_id="A-0002")))
    alert = client.get("/api/alerts/A-0002").json()
    assert schemas.errors("alert_summary", alert) == []
    assert alert["replies"] == {"safe": 2, "need_help": 1, "helping": 1, "total": 4}    # both versions
    assert alert["coverage"] == {"registered": 2, "confirmed": 1, "coverage": 0.5}
    first = client.get("/api/alerts/A-0001").json()
    assert alert["timeout_at"] == timeutil.iso(timeutil.parse(first["issued_at"]) + timedelta(minutes=30))


def test_an_update_keeps_the_coverage_clock_of_the_first_alert(client, phone):
    load_zones(client)
    load_registry(client)
    ctx = client.app.state.ctx
    start = timeutil.now() - timedelta(hours=2, minutes=1)
    ctx.alerts.issue(dict(FLOOD_WARNING), "dispatcher", now=start)
    reply = copy.deepcopy(load_example(SHARED_DIR, "alert_reply")["payload"])
    phone.send(phone.wire("alert_reply", payload=dict(reply, registry_id="R-0193"),
                          created=start + timedelta(minutes=10)))          # before the update
    ctx.alerts.issue({"replaces": "A-0001", "zones": ["Ward 4", "Riverside", "Old Market"]}, "dispatcher",
                     now=timeutil.now() - timedelta(minutes=30))
    assert ctx.coverage.timeouts() == 1                                       # R-0007; not R-0193 or Old Market
    [case] = client.get("/api/snapshot").json()["cases"]
    assert "oxygen" in case["conditions"] and case["note"] == "Registered, not confirmed 2 h after alert A-0002"


# ---- the announcement -----------------------------------------------------------------------------------------
def test_announcement_script(client, schemas):
    load_zones(client)
    post(client, {"hazard": "flood", "severity": "warning", "zones": ["Ward 4"]})
    out = client.post("/api/announcement", json={"alert_id": "A-0001"}).json()
    assert schemas.errors("announcement", out) == []
    [script] = out["scripts"]
    assert script["text"] == (
        "Attention Ward 4: an official message from the command post. Flood warning for Ward 4. "
        "Move people and valuables upstairs. Check on elderly or ill neighbours. "
        "Do not walk or drive through floodwater. Please pass this on and check on your neighbours. "
        "Again: Flood warning for Ward 4.")
    assert script["seconds"] <= out["target_seconds"]


def test_a_long_announcement_drops_the_repeat(client):
    load_zones(client)
    add_shelter(client, "cool_hall", "cooling_centre", 0.015, 0.041, 120, name="Community hall")
    post(client, HEAT_WARNING)
    [script] = client.post("/api/announcement", json={"alert_id": "A-0001"}).json()["scripts"]
    assert "If you need to leave, go to Community hall." in script["text"]
    assert "Again:" not in script["text"] and script["seconds"] > 20
    resp = client.post("/api/announcement", json={"alert_id": "A-0001", "languages": ["fr"]})
    assert resp.status_code == 400 and "no text in 'fr'" in resp.json()["detail"]


def test_phones_still_cannot_send_alerts(client, phone):
    load_zones(client)
    wire = Phone(client, "dev_FAKE").wire("alert")
    assert phone.send(wire)["rejected"][0]["reason"] in ("not_allowed", "invalid_body")

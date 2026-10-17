"""The chaos panel (System Design 13.4): each problem shows the right badge or banner at once."""
from conftest import Phone, load_zones

HOUSE_14 = {"hazard": "flood", "for_whom": "neighbour", "people": 1,
            "conditions": ["elderly", "cannot_walk", "oxygen", "alone"], "details": {"water": "waist", "rising": True},
            "note": "Old man alone, 2nd floor, oxygen tank half empty", "lat": 0.0123, "lng": 0.0456,
            "gps_accuracy_m": 15, "landmark": "behind the green mosque, house 14", "reporter_role": "helper",
            "contact": ""}


def top_case(client):
    load_zones(client)
    phone = Phone(client)
    phone.send(phone.wire("report", payload=HOUSE_14))
    [case] = client.get("/api/snapshot").json()["cases"]
    return case


def case_of(client, case_id):
    return next(c for c in client.get("/api/snapshot").json()["cases"] if c["id"] == case_id)


def test_a_duplicate_merges_into_the_top_case(client):
    case = top_case(client)
    out = client.post("/api/chaos/duplicate").json()
    assert out["merged"] is True and out["case_id"] == out["top_case"] == case["id"]
    after = case_of(client, case["id"])
    assert after["report_count"] == 2 and "2 reports" in after["badges"]
    assert len(client.get("/api/snapshot").json()["cases"]) == 1


def test_a_fake_report_gets_low_trust_and_a_verify_badge(client):
    top_case(client)
    out = client.post("/api/chaos/fake").json()
    fake = case_of(client, out["case_id"])
    assert out["merged"] is False and fake["people"] == 50
    assert fake["confidence"] <= 0.3 and "verify" in fake["badges"]


def test_a_wrong_location_stays_apart_and_asks_to_check(client):
    case = top_case(client)
    out = client.post("/api/chaos/wrong_location").json()
    assert out["merged"] is False                     # same landmark, but 2 km apart: two places
    twin = case_of(client, out["case_id"])
    assert "check location" in twin["badges"]
    trust = next(r for r in twin["reasons"] if r["kind"] == "trust")["text"]
    assert f"same landmark as case #{case['id']}, 2.0 km away" in trust
    assert twin["confidence"] < case["confidence"]
    assert "check location" not in case_of(client, case["id"])["badges"]      # the earlier case keeps its trust


def test_the_ai_outage_raises_the_banner_until_turned_off(client):
    reader = client.app.state.ctx.ai
    reader.enabled = reader.online = True
    assert client.get("/api/snapshot").json()["status"]["banner"] is None
    out = client.post("/api/chaos/ai_down").json()
    assert out["ai"]["simulated_outage"] is True and out["ai"]["online"] is False
    assert reader.read("anything") is None
    assert client.get("/api/snapshot").json()["status"]["banner"]           # at once, not next minute
    assert client.post("/api/chaos/ai_down", json={"on": False}).json()["ai"]["simulated_outage"] is False


def test_nothing_to_copy_and_unknown_kinds(client):
    assert client.post("/api/chaos/duplicate").status_code == 404
    assert client.post("/api/chaos/meteor").status_code == 422


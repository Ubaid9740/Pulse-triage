"""Zone windows (System Design 9.1) and simulated text messages for the scenario replay."""
from conftest import Phone, load_zones

HOUSE_14 = {"hazard": "flood", "for_whom": "neighbour", "people": 1, "conditions": ["elderly", "alone"],
            "details": {"water": "knee"}, "note": "Old man alone", "lat": 0.0123, "lng": 0.0456,
            "gps_accuracy_m": 15, "landmark": "house 14", "reporter_role": "helper", "contact": ""}


def only_case(client):
    [case] = client.get("/api/snapshot").json()["cases"]
    return case


def test_a_window_adds_points_to_cases_in_its_zone_until_cleared(client):
    load_zones(client)
    phone = Phone(client)
    phone.send(phone.wire("report", payload=HOUSE_14))
    before = only_case(client)
    assert before["window_closes_at"] is None and not any(r["kind"] == "window" for r in before["reasons"])

    out = client.post("/api/windows", json={"zone": "Ward 4", "closes_in_min": 90, "text": "Bridge Rd floods"})
    assert out.status_code == 200, out.text
    assert client.get("/api/windows").json()["windows"]["Ward 4"]["text"] == "Bridge Rd floods"
    after = only_case(client)
    window = next(r for r in after["reasons"] if r["kind"] == "window")
    assert window["text"] == "Bridge Rd floods in about 1.5 h" and window["points"] == 20
    assert after["window_closes_at"] and after["points"] > before["points"]

    client.post("/api/windows", json={"zone": "Ward 4", "clear": True})
    cleared = only_case(client)
    assert cleared["window_closes_at"] is None and cleared["points"] == before["points"]


def test_a_window_needs_a_known_zone_and_a_time(client):
    load_zones(client)
    assert client.post("/api/windows", json={"zone": "Atlantis", "closes_in_min": 30}).status_code == 404
    assert client.post("/api/windows", json={"zone": "Ward 4"}).status_code == 400


def test_heat_windows_only_count_without_cooling(client):
    load_zones(client)
    phone = Phone(client)
    hot = dict(HOUSE_14, hazard="heat", details={"cooling": True}, note="Old man, fan works")
    phone.send(phone.wire("report", payload=hot))
    client.post("/api/windows", json={"zone": "Ward 4", "closes_in_min": 60})
    assert only_case(client)["window_closes_at"] is None


def test_simulated_texts_are_read_located_and_merged_per_sender(client):
    load_zones(client)
    text = "pls help water till waist my father 78 alone cant walk near house 14"
    out = client.post("/api/reports/simulate", json={"hazard": "flood", "messages": [
        {"text": text, "sender": "+000 555 0001", "lat": 0.0123, "lng": 0.0456},
        {"text": "water at waist, old man alone, house 14", "sender": "+000 555 0002", "lat": 0.0124, "lng": 0.0457},
        {"text": "is the shop open today", "sender": "+000 555 0003"},
    ]}).json()["messages"]
    assert [m["status"] for m in out] == ["accepted", "accepted", "skipped"]
    assert out[0]["case_id"] == out[1]["case_id"]
    case = only_case(client)
    assert case["report_count"] == 2 and case["zone"] == "Ward 4" and "elderly" in case["conditions"]
    again = client.post("/api/reports/simulate", json={"messages": [
        {"text": text, "sender": "+000 555 0001", "lat": 0.0123, "lng": 0.0456}]}).json()["messages"]
    assert again[0]["status"] == "duplicate" and again[0]["case_id"] == case["id"]

"""Reports in, cases out: merging, scoring, verify, split and trust through the real API."""
import copy
import json
from datetime import timedelta

from conftest import Phone

from app import timeutil
from app.config import SHARED_DIR
from app.devtools import load_example


def payload(name="report", **changes) -> dict:
    p = copy.deepcopy(load_example(SHARED_DIR, name)["payload"])
    p.update(changes)
    return p


def neighbour_report(**changes) -> dict:
    """A second phone reporting house 14: 40 m away, slightly different words."""
    return payload(lat=0.0123 + 40 / 111_195, gps_accuracy_m=30, landmark="house 14 near mosque",
                   note="Old neighbour with oxygen, water rising", **changes)


def cases(client) -> list[dict]:
    return client.get("/api/snapshot").json()["cases"]


def test_house_14_from_two_phones_is_one_case_with_69_points(client, phone, schemas):
    jo = Phone(client, "dev_JO02")
    phone.send(phone.wire("report"))
    jo.send(jo.wire("report", payload=neighbour_report()))
    [case] = cases(client)
    assert case["report_count"] == 2 and case["confidence"] == 0.75 and case["points"] == 69
    assert case["badges"] == ["2 reports"] and case["accuracy_m"] == 15     # best GPS wins
    assert len([r for r in case["reasons"] if r["kind"] != "trust"]) == 5
    detail = client.get(f"/api/cases/{case['id']}").json()
    assert schemas.errors("case_detail", detail) == []
    assert [h["action"] for h in detail["history"]] == ["new_case", "merge"]
    assert {r["device_id"] for r in detail["reports"]} == {phone.device_id, "dev_JO02"}


def test_same_phone_twice_merges_without_extra_trust(client, phone):
    phone.send(phone.wire("report"), phone.wire("report"))
    [case] = cases(client)
    assert case["report_count"] == 2 and case["confidence"] == 0.6 and case["points"] == 65


def test_different_places_or_households_stay_apart(client, phone):
    far = payload(lat=0.0123 + 500 / 111_195, landmark="Market road, shop 3")
    family = payload(people=9)
    phone.send(phone.wire("report"), phone.wire("report", payload=far), phone.wire("report", payload=family))
    assert len(cases(client)) == 3


def test_newer_more_urgent_report_updates_the_case(client, phone):
    phone.send(phone.wire("report"))
    jo = Phone(client, "dev_JO02")
    jo.send(jo.wire("report", payload=neighbour_report(details={"water": "chest", "rising": True})))
    [case] = cases(client)
    assert case["details"]["water"] == "chest" and 0.9 <= case["hours_left"] <= 1.0
    assert case["reasons"][0]["text"].startswith("Water at chest or roof level")


def test_trusting_the_volunteer_moves_heatstroke_to_the_top(client, phone):
    vol = Phone(client, "dev_VOL07")
    phone.send(phone.wire("report"))
    vol.send(vol.wire("report_heat"))
    assert [(c["hazard"], c["points"]) for c in cases(client)] == [("flood", 65), ("heat", 60)]
    resp = client.post("/api/devices/dev_VOL07/trust", json={"trusted": True, "by": "dispatcher"})
    assert resp.json()["cases_rescored"] == 1
    assert [(c["hazard"], c["points"]) for c in cases(client)] == [("heat", 66), ("flood", 65)]


def test_verify_gives_full_trust(client, phone):
    phone.send(phone.wire("report"))
    case_id = cases(client)[0]["id"]
    detail = client.post(f"/api/cases/{case_id}/verify", json={"by": "maria"}).json()
    assert detail["case"]["confidence"] == 1.0 and detail["case"]["status"] == "verified"
    assert detail["case"]["points"] == 77 and "verified" in detail["case"]["badges"]
    assert detail["history"][-1]["actor"] == "maria"


def test_split_undoes_a_wrong_merge(client, phone):
    jo = Phone(client, "dev_JO02")
    phone.send(phone.wire("report"))
    wire = jo.wire("report", payload=neighbour_report())
    jo.send(wire)
    case_id = cases(client)[0]["id"]
    report_id = json.loads(wire["body"])["id"]
    out = client.post(f"/api/cases/{case_id}/split", json={"report_id": report_id}).json()
    assert {c["report_count"] for c in cases(client)} == {1}
    assert client.get(f"/api/cases/{out['new_case_id']}").json()["reports"][0]["id"] == report_id
    assert client.post(f"/api/cases/{case_id}/split", json={"report_id": report_id}).status_code == 404
    lone = client.get(f"/api/cases/{case_id}").json()["reports"][0]["id"]
    assert client.post(f"/api/cases/{case_id}/split", json={"report_id": lone}).status_code == 400


def test_unknown_case_and_device_are_404(client):
    assert client.get("/api/cases/999").status_code == 404
    assert client.post("/api/cases/999/verify").status_code == 404
    assert client.post("/api/devices/dev_NOPE/trust", json={}).status_code == 404


def test_scheduler_rescores_as_time_passes(client, phone):
    phone.send(phone.wire("report"))
    ctx = client.app.state.ctx
    later = timeutil.now() + timedelta(hours=2)
    assert ctx.cases.rescore_all(later) == 1
    case = ctx.cases.detail(cases(client)[0]["id"], later)["case"]
    assert case["hours_left"] == 0 and case["reasons"][0]["points"] == 50
    assert case["confidence"] == 0.5 and case["points"] == 70            # 87 x 0.8 = 69.6
    assert client.get("/api/status").json()["scheduler_last_run"] == timeutil.iso(later)


def test_report_carried_for_hours_by_the_mesh_counts_from_when_it_was_made(client, phone):
    phone.send(phone.wire("report", created=timeutil.now() - timedelta(hours=3)))
    [case] = cases(client)
    assert case["hours_left"] == 0 and "re-check" in case["badges"] and case["confidence"] == 0.5


def test_unknown_phone_claiming_50_people_needs_verifying(client, phone):
    phone.send(phone.wire("report", payload=payload(people=50)))
    [case] = cases(client)
    assert "verify" in case["badges"] and case["confidence"] == 0.4


def test_closed_cases_do_not_absorb_new_reports(client, phone):
    phone.send(phone.wire("report"))
    ctx = client.app.state.ctx
    with ctx.db.write() as conn:
        conn.execute("UPDATE cases SET status = 'done'")
    phone.send(phone.wire("report"))
    assert [c["report_count"] for c in cases(client)] == [1]

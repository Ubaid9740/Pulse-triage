"""Warning coverage, the registry and coverage timeouts (System Design 9.5 and 13.1; Team Brief 3.2)."""
import copy
from datetime import timedelta

import pytest
from conftest import Phone, add_alert, load_registry, load_zones, registry_csv

from app import timeutil
from app.config import SHARED_DIR
from app.devtools import load_example


def example(name, **changes) -> dict:
    p = copy.deepcopy(load_example(SHARED_DIR, name)["payload"])
    p.update(changes)
    return p


def person(client, pid) -> dict:
    return client.app.state.ctx.db.one("SELECT * FROM registry WHERE id = ?", (pid,))


def open_cases(client) -> list[dict]:
    return client.get("/api/snapshot").json()["cases"]


def two_hours_ago(minutes=1):
    return timeutil.now() - timedelta(hours=2, minutes=minutes)


# ---- the registry -------------------------------------------------------------------------------------
def test_registry_import_places_people_and_keeps_confirmations(client, phone):
    load_zones(client)
    assert load_registry(client) == {"added": 3, "updated": 0, "skipped": [], "total": 3}
    assert [person(client, p)["zone"] for p in ("R-0007", "R-0193", "R-0310")] == ["Ward 4", "Ward 4", "Old Market"]
    phone.send(phone.wire("alert_reply", payload=example("alert_reply", registry_id="R-0007")))
    assert person(client, "R-0007")["confirmed_at"] is not None
    assert load_registry(client)["updated"] == 3
    assert person(client, "R-0007")["confirmed_by"] == f"alert_reply from {phone.device_id}"


def test_bad_registry_rows_are_skipped_with_reasons(client):
    text = registry_csv([("R-1", "Ward 4", "elderly;flying", None, None), ("R-2", "", "alone", "north", "0.1"),
                         ("R-3", "Ward 4", "oxygen", None, None)])
    text += "R-4,Demo R-4,Ward 4,,,alone,,\nR-3,Again,Ward 4,,,,,2026-01-01T00:00:00Z\n"
    out = load_registry(client, text)
    assert out["added"] == 1 and [s["line"] for s in out["skipped"]] == [2, 3, 5, 6]
    reasons = [s["reason"] for s in out["skipped"]]
    assert reasons == ["unknown condition 'flying'", "lat and lng must both be numbers",
                       "no consent_at: the registry is opt-in", "the same id appears twice"]
    resp = client.post("/api/registry/import", content=b"id,name\nR-1,x\n")
    assert resp.status_code == 400 and "consent_at" in resp.json()["detail"]


# ---- confirmations --------------------------------------------------------------------------------------
def test_alert_reply_without_a_registry_id_is_kept_but_confirms_nobody(client, phone):
    load_zones(client)
    load_registry(client)
    phone.send(phone.wire("alert_reply"))
    assert client.app.state.ctx.db.scalar("SELECT COUNT(*) FROM alert_replies") == 1
    assert client.get("/api/coverage").json()["overall"] == {"registered": 3, "confirmed": 0, "coverage": 0}


def test_coverage_counts_confirmations_since_the_alert(client, phone, schemas):
    load_zones(client)
    load_registry(client)
    phone.send(phone.wire("alert_reply", payload=example("alert_reply", registry_id="R-0007"),
                          created=timeutil.now() - timedelta(hours=3)))
    summary = client.get("/api/coverage").json()
    assert schemas.errors("coverage", summary) == []
    assert summary["zones"][1] == {"name": "Ward 4", "registered": 2, "confirmed": 1, "coverage": 0.5}
    issued = two_hours_ago(0)
    add_alert(client, issued_at=issued)               # the reply came before this warning
    summary = client.get("/api/coverage").json()
    assert summary["zones"][1]["confirmed"] == 0
    assert summary["alerts"][0]["timeout_at"] == timeutil.iso(issued + timedelta(hours=2))
    assert [p["id"] for p in summary["unconfirmed"]] == ["R-0007", "R-0310", "R-0193"]    # medical first


# ---- coverage timeouts ---------------------------------------------------------------------------------
@pytest.mark.parametrize("severity, minutes, made", [
    ("warning", 119, 0), ("warning", 121, 2), ("emergency", 29, 0), ("emergency", 31, 2), ("watch", 600, 0)])
def test_unconfirmed_people_become_cases_after_the_wait(client, severity, minutes, made):
    load_zones(client)
    load_registry(client)
    add_alert(client, severity=severity, issued_at=timeutil.now() - timedelta(minutes=minutes), valid_hours=24)
    assert client.app.state.ctx.coverage.timeouts() == made
    assert len(open_cases(client)) == made


def test_coverage_timeout_makes_an_unconfirmed_case_at_0_3(client, phone, schemas):
    load_zones(client)
    load_registry(client)
    phone.send(phone.wire("alert_reply", payload=example("alert_reply", registry_id="R-0193")))
    add_alert(client, issued_at=two_hours_ago())
    ctx = client.app.state.ctx
    assert ctx.coverage.timeouts() == 1 and ctx.coverage.timeouts() == 0     # once per person and alert
    [case] = open_cases(client)
    assert (case["source"], case["reader"], case["confidence"], case["zone"]) == ("silence", "system", 0.3, "Ward 4")
    assert case["note"] == "Registered, not confirmed 2 h after alert A-0007"
    assert case["points"] == 55                     # oxygen 40 + cannot walk 15 + elderly 10 + alone 10 + 2, x 0.72
    detail = client.get(f"/api/cases/{case['id']}").json()
    assert schemas.errors("case_detail", detail) == [] and detail["reports"][0]["registry_id"] == "R-0007"
    assert [h["action"] for h in detail["history"]] == ["new_case", "unconfirmed"]
    assert client.get("/api/zones/Ward 4").json()["zone"]["actual"] == 0   # the server's own case is no report


def test_a_late_safe_reply_closes_the_unconfirmed_case(client, phone):
    load_zones(client)
    load_registry(client)
    add_alert(client, issued_at=two_hours_ago())
    client.app.state.ctx.coverage.timeouts()
    case_id = next(c["id"] for c in open_cases(client) if c["people"] == 1 and "oxygen" in c["conditions"])
    phone.send(phone.wire("alert_reply", payload=example("alert_reply", registry_id="R-0007")))
    assert case_id not in [c["id"] for c in open_cases(client)]
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["case"]["status"] == "closed" and detail["history"][-1]["detail"] == "alert reply: safe (A-0007)"


def test_a_report_naming_the_person_joins_their_case_and_takes_over_trust(client, phone):
    load_zones(client)
    load_registry(client)
    add_alert(client, issued_at=two_hours_ago())
    client.app.state.ctx.coverage.timeouts()
    phone.send(phone.wire("report", payload=example("report", registry_id="R-0007")))
    case = next(c for c in open_cases(client) if c["report_count"] == 1 and c["source"] == "app")
    assert len(open_cases(client)) == 2                           # R-0193's case and this one
    assert case["confidence"] == 0.6 and case["points"] == 65 and case["badges"] == []
    assert person(client, "R-0007")["confirmed_by"] == f"report from {phone.device_id}"
    history = client.get(f"/api/cases/{case['id']}").json()["history"]
    assert history[-1]["detail"].endswith("same registered person R-0007")


# ---- welfare checks ------------------------------------------------------------------------------------
def test_welfare_check_safe_confirms_and_closes(client):
    load_zones(client)
    load_registry(client)
    add_alert(client, issued_at=two_hours_ago())
    client.app.state.ctx.coverage.timeouts()
    vol = Phone(client, "dev_VOL07")
    vol.send(vol.wire("welfare_check", payload=example("welfare_check", result="safe", note="Fine, has a fan")))
    assert [c["conditions"] for c in open_cases(client)] == [["elderly", "cannot_walk", "oxygen", "alone"]]
    assert person(client, "R-0193")["confirmed_by"] == "welfare_check from dev_VOL07"


def test_welfare_check_not_found_leaves_the_case_open(client):
    load_zones(client)
    load_registry(client)
    add_alert(client, issued_at=two_hours_ago())
    client.app.state.ctx.coverage.timeouts()
    vol = Phone(client, "dev_VOL07")
    vol.send(vol.wire("welfare_check", payload=example("welfare_check", result="not_found", note="No answer")))
    assert len(open_cases(client)) == 2 and person(client, "R-0193")["confirmed_at"] is None
    case = next(c for c in open_cases(client) if c["conditions"] == ["elderly", "alone"])
    history = client.get(f"/api/cases/{case['id']}").json()["history"]
    assert history[-1] == {"at": history[-1]["at"], "actor": "dev_VOL07", "action": "welfare_check",
                           "detail": "not_found: No answer"}


def test_welfare_check_needs_help_without_registry_becomes_a_report(client):
    vol = Phone(client, "dev_VOL07")
    payload = example("welfare_check", note="Man on the stairs, can't stand")
    payload.pop("registry_id")
    vol.send(vol.wire("welfare_check", payload=payload))
    [case] = open_cases(client)
    assert case["source"] == "welfare_check" and case["conditions"] == [] and case["hazard"] == "flood"


def test_heat_journey_unconfirmed_woman_ends_at_66_points(client, schemas):
    """Team Brief journey 2: a heat warning, 2 hours of silence, a knock, then the volunteer's report."""
    load_zones(client)
    load_registry(client)
    client.post("/api/settings/hazard", json={"hazard": "heat"})
    add_alert(client, hazard="heat", zones=("Ward 4", "Old Market"), issued_at=two_hours_ago())
    ctx = client.app.state.ctx
    assert ctx.coverage.timeouts() == 3
    woman = next(c for c in open_cases(client) if c["conditions"] == ["elderly", "alone"])
    assert woman["hazard"] == "heat" and woman["confidence"] == 0.3

    vol = Phone(client, "dev_VOL07")
    vol.send(vol.wire("welfare_check"))                           # needs_help for R-0193
    client.post("/api/devices/dev_VOL07/trust", json={"trusted": True})
    vol.send(vol.wire("report_heat"))                             # the full report, also naming R-0193
    detail = client.get(f"/api/cases/{woman['id']}").json()
    case = detail["case"]
    assert schemas.errors("case_detail", detail) == []
    assert (case["points"], case["confidence"], case["source"]) == (66, 0.8, "welfare_check")
    assert case["reasons"][0]["text"] == "Signs of heatstroke, about 30 min left"
    assert [r["source"] for r in detail["reports"]] == ["silence", "welfare_check", "app"]
    assert case["report_count"] == 2 and len(open_cases(client)) == 3
    assert open_cases(client)[0]["id"] == woman["id"]            # the heatstroke case ranks first
    assert "R-0193" not in [p["id"] for p in client.get("/api/coverage").json()["unconfirmed"]]


def test_zone_card_outreach_list_is_highest_risk_first(client, schemas):
    load_zones(client)
    load_registry(client, registry_csv([("R-1", "Ward 4", "elderly", None, None), ("R-2", "Ward 4", "alone", None, None),
                                        ("R-3", "Ward 4", "dialysis;alone", None, None),
                                        ("R-4", "Ward 4", "elderly;alone", None, None)]))
    card = client.get("/api/zones/Ward 4").json()
    assert schemas.errors("zone_card", card) == []
    assert [(p["id"], p["priority"]) for p in card["unconfirmed"]] == [
        ("R-3", "medical"), ("R-4", "alone"), ("R-2", "alone"), ("R-1", "other")]
    assert "1 of the unconfirmed need oxygen, dialysis, insulin or power for a device" in card["lines"]

"""Keyword reader, intake form, paste box, overrides and weights (Team Brief 3.3, 3.6, 3.9 a)."""
import pytest

from app.intake import split_messages
from app.profiles import Profiles
from app.reader import KeywordReader
from app.config import SHARED_DIR

HOUSE_14 = ("Old man alone behind the green mosque, house 14. Water up to his waist and rising, "
            "he needs oxygen and cannot walk")


@pytest.fixture(scope="module")
def reader(schemas) -> KeywordReader:
    return KeywordReader(Profiles(SHARED_DIR, schemas))


# ---- the keyword reader ---------------------------------------------------------------------------
def test_reads_house_14(reader):
    r = reader.read(HOUSE_14)
    assert (r.hazard, r.hazard_from) == ("flood", "text")
    assert r.details == {"water": "waist", "rising": True}
    assert r.conditions == ["elderly", "cannot_walk", "oxygen", "alone"]
    assert (r.people, r.landmark) == (1, "behind the green mosque, house 14")


def test_reads_heat_and_earthquake(reader):
    heat = reader.read("My grandmother is confused and very hot, no fan, family of 5")
    assert heat.hazard == "heat" and heat.people == 5
    assert heat.details == {"hot_inside": True, "cooling": False, "signs": ["confused"]}
    quake = reader.read("Building collapsed, 2 adults and 3 kids trapped under rubble, smell of gas")
    assert quake.hazard == "earthquake" and quake.people == 5 and quake.conditions == ["child"]
    assert quake.details == {"trapped": True, "building": "collapsed", "gas_or_fire": True}


def test_the_more_severe_choice_and_the_cautious_answer_win(reader):
    assert reader.read("water at the knee, now on the roof").details["water"] == "roof"
    assert reader.read("very hot inside, fan broken, fan on in the other room").details["cooling"] is False


def test_unclear_disaster_falls_back_to_hint_alert_then_active(reader):
    text = "please help, we are trapped"                          # 'trapped' is in flood and earthquake
    assert reader.read(text, hint="earthquake").hazard == "earthquake"
    assert reader.read(text, alert_hazard="earthquake", active="flood").hazard_from == "alert"
    assert (reader.read(text, active="flood").hazard, reader.read("ok thanks").found_anything) == ("flood", False)


def test_messages_are_split_on_chat_headers_blank_lines_or_lines():
    chat = "[12/10, 14:03] Ana: first one\nstill first\n[12/10, 14:05] Bo: second\n12/10/26, 14:07 - Cy: third"
    assert split_messages(chat) == ["first one still first", "second", "third"]
    assert split_messages("one\nline\n\ntwo") == ["one line", "two"]
    assert split_messages("one\ntwo\n") == ["one", "two"]


# ---- intake ---------------------------------------------------------------------------------------------
def test_a_call_from_the_note_alone(client, schemas):
    out = client.post("/api/intake", json={"note": HOUSE_14, "lat": 0.0123, "lng": 0.0456, "gps_accuracy_m": 15,
                                           "by": "maria"}).json()
    case = out["case"]
    assert schemas.errors("case", case) == []
    assert (case["source"], case["reader"], case["confidence"], case["points"]) == ("call", "keywords", 0.9, 74)
    assert case["landmark"] == "behind the green mosque, house 14" and out["read"]["hazard"] == "flood"
    report = client.get(f"/api/cases/{case['id']}").json()["reports"][0]
    assert (report["device_id"], report["reporter_role"]) == ("call:maria", "call_taker")


def test_what_the_call_taker_types_wins_and_a_call_merges_with_the_app_report(client, phone):
    phone.send(phone.wire("report"))
    out = client.post("/api/intake", json={"hazard": "flood", "people": 1, "conditions": ["elderly"],
                                           "details": {"water": "chest"}, "note": HOUSE_14, "lat": 0.0124,
                                           "lng": 0.0456}).json()
    case = out["case"]
    assert case["report_count"] == 2 and case["details"]["water"] == "chest" and case["details"]["rising"] is True
    assert client.get(f"/api/cases/{case['id']}").json()["reports"][1]["reader"] == "form"
    assert client.post("/api/intake", json={"details": {"water": "deep"}}).status_code == 400


# ---- paste ------------------------------------------------------------------------------------------------
def test_paste_reads_each_message_and_skips_chatter(client, schemas):
    text = (f"[12/10, 14:03] Ana: {HOUSE_14}\n"
            "[12/10, 14:05] Bo: ok thanks, praying for everyone\n"
            "[12/10, 14:06] Cy: my grandmother is confused and very hot, no fan")
    out = client.post("/api/paste", json={"text": text, "by": "vol desk"}).json()
    assert out["messages"] == 3 and [s["text"][:6] for s in out["skipped"]] == ["ok tha"]
    assert [r["read"]["hazard"] for r in out["reports"]] == ["flood", "heat"]
    cases = client.get("/api/snapshot").json()["cases"]
    assert {(c["source"], c["reader"], c["confidence"]) for c in cases} == {("paste", "keywords", 0.3)}
    assert all(schemas.errors("case", c) == [] for c in cases)
    again = client.post("/api/paste", json={"text": text}).json()
    assert [r["duplicate"] for r in again["reports"]] == [True, True]
    assert [r["case_id"] for r in again["reports"]] == [r["case_id"] for r in out["reports"]]
    assert len(client.get("/api/snapshot").json()["cases"]) == 2


def test_paste_uses_the_dispatchers_disaster_when_unclear(client):
    out = client.post("/api/paste", json={"text": "family of 6 trapped", "hazard": "earthquake"}).json()
    assert out["reports"][0]["read"] == {"hazard": "earthquake", "hazard_from": "hint", "details": {"trapped": True},
                                         "conditions": [], "people": 6, "landmark": None}


# ---- overrides and weights -----------------------------------------------------------------------------------
def test_override_points_and_status_with_a_reason(client, phone):
    phone.send(phone.wire("report"))
    case_id = client.get("/api/snapshot").json()["cases"][0]["id"]
    assert client.post(f"/api/cases/{case_id}/override", json={"points": 90}).status_code == 422   # no reason
    detail = client.post(f"/api/cases/{case_id}/override", json={"points": 90, "reason": "Neighbour called again",
                                                                  "by": "maria"}).json()
    case = detail["case"]
    assert case["points"] == 90 and "override" in case["badges"]
    assert case["reasons"][-1] == {"text": "Changed by dispatcher: Neighbour called again (rules gave 65)",
                                   "points": 90, "kind": "override"}
    client.app.state.ctx.cases.rescore_all()
    assert client.get("/api/snapshot").json()["cases"][0]["points"] == 90
    history = detail["history"][-1]
    assert history["action"] == "override" and '"before": {"points": 65' in history["detail"]
    cleared = client.post(f"/api/cases/{case_id}/override", json={"reason": "Back to the rules"}).json()["case"]
    assert cleared["points"] == 65 and "override" not in cleared["badges"]
    client.post(f"/api/cases/{case_id}/override", json={"status": "closed", "reason": "Duplicate of a call"})
    assert client.get("/api/snapshot").json()["cases"] == []
    assert client.post(f"/api/cases/{case_id}/override", json={"status": "assigned", "reason": "x"}).status_code == 422


def test_override_cannot_close_a_case_a_team_is_on(client, phone):
    phone.send(phone.wire("report"))
    case_id = client.get("/api/snapshot").json()["cases"][0]["id"]
    client.post("/api/teams", json={"id": "boat_2", "name": "Boat 2", "type": "boat", "lat": 0.0, "lng": 0.045})
    client.post("/api/assign", json={"case_id": case_id, "team_id": "boat_2"})
    resp = client.post(f"/api/cases/{case_id}/override", json={"status": "closed", "reason": "False alarm"})
    assert resp.status_code == 400 and "team boat_2 is on this case" in resp.json()["detail"]


def test_weights_rerank_at_once(client, phone, constants):
    phone.send(phone.wire("report"))
    got = client.get("/api/settings/weights").json()
    assert got["weights"] == got["defaults"] == constants["points"]["weights"]
    out = client.post("/api/settings/weights", json={"weights": {"alone": 30}, "by": "council"}).json()
    assert out["weights"]["alone"] == 30 and out["cases_rescored"] == 1
    case = client.get("/api/snapshot").json()["cases"][0]
    assert case["points"] == 81 and {"text": "Lives alone", "points": 30, "kind": "vulnerability"} in case["reasons"]
    assert client.post("/api/settings/weights", json={"weights": {"bravery": 5}}).status_code == 400
    assert client.post("/api/settings/weights", json={"weights": {"alone": 500}}).status_code == 400
    client.post("/api/settings/weights", json={"reset": True})
    assert client.get("/api/snapshot").json()["cases"][0]["points"] == 65


def test_a_call_and_a_pasted_message_about_house_14_are_one_case(client):
    client.post("/api/paste", json={"text": HOUSE_14})
    out = client.post("/api/intake", json={"note": "grandmother at house 14 cannot walk, water rising"}).json()
    assert out["case"]["report_count"] == 2 and len(client.get("/api/snapshot").json()["cases"]) == 1

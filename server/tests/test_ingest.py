import json
from datetime import timedelta

import pytest
from conftest import PHONE_KINDS, Phone

from app import outbound, timeutil
from app.config import SHARED_DIR
from app.crypto import verify
from app.devtools import load_example
from app.packets import make_body, make_wire


def test_signed_and_sealed_report_becomes_a_case(client, phone):
    result = phone.send(phone.wire("report"))
    assert len(result["accepted"]) == 1 and not result["rejected"]
    cases = client.get("/api/snapshot").json()["cases"]
    assert len(cases) == 1
    case = cases[0]
    assert case["hazard"] == "flood"
    assert set(case["needs"]) == {"boat", "medic"}
    assert 1.9 <= case["hours_left"] <= 2.0
    assert case["status"] == "new" and case["report_count"] == 1


@pytest.mark.parametrize("name", ["report", "report_heat", "alert_reply", "welfare_check", "volunteer", "ack", "team_ping"])
def test_every_phone_example_is_accepted(phone, name):
    result = phone.send(phone.wire(name))
    assert result["rejected"] == [] and len(result["accepted"]) == 1


def test_duplicates_are_harmless(client, phone):
    wire = phone.wire("report")
    assert len(phone.send(wire)["accepted"]) == 1
    second = phone.send(wire, dict(wire, hops=5))
    assert len(second["duplicate"]) == 2
    assert len(client.get("/api/snapshot").json()["cases"]) == 1


def test_tampered_body_is_rejected(phone):
    wire = phone.wire("report")
    body = json.loads(wire["body"])
    body["urgency"] = 3
    tampered = dict(wire, body=json.dumps(body))
    assert phone.send(tampered)["rejected"][0]["reason"] == "bad_signature"


def test_unsigned_allowed_only_in_development(make_client):
    dev = Phone(make_client())
    assert len(dev.send(dev.wire("report", signed=False))["accepted"]) == 1
    strict = Phone(make_client(require_signatures=True))
    assert strict.send(strict.wire("report", signed=False))["rejected"][0]["reason"] == "unsigned"


def test_plain_payload_allowed_only_in_development(make_client):
    dev = Phone(make_client())
    assert len(dev.send(dev.wire("report", sealed=False))["accepted"]) == 1
    strict = Phone(make_client(require_sealing=True))
    assert strict.send(strict.wire("report", sealed=False))["rejected"][0]["reason"] == "cannot_unseal"


def test_expired_packets_are_rejected(phone):
    old = timeutil.now() - timedelta(hours=30)
    assert phone.send(phone.wire("report", created=old))["rejected"][0]["reason"] == "expired"


def test_phone_clock_ahead_uses_server_time(client, phone):
    phone.send(phone.wire("report", created=timeutil.now() + timedelta(hours=5)))
    case = client.get("/api/snapshot").json()["cases"][0]
    reported = timeutil.parse(case["reported_at"])
    assert abs((reported - timeutil.now()).total_seconds()) < 60


def test_device_key_is_pinned(client, phone):
    phone.send(phone.wire("report"))
    impostor = Phone(client, device_id=phone.device_id)
    assert impostor.send(impostor.wire("report"))["rejected"][0]["reason"] == "pubkey_mismatch"


def test_rate_limit(phone, constants):
    limit = constants["rate_limit_reports_per_hour"]
    accepted = phone.send(*[phone.wire("report") for _ in range(limit)])["accepted"]
    assert len(accepted) == limit
    assert phone.send(phone.wire("report"))["rejected"][0]["reason"] == "rate_limited"


def test_invalid_payload_is_rejected(phone):
    wire = phone.wire("report", payload={"hazard": "flood", "people": 0})
    rejected = phone.send(wire)["rejected"][0]
    assert rejected["reason"] == "invalid_payload"


def test_garbage_is_rejected_not_crashing(phone):
    result = phone.send({"body": "not json", "sig": "", "hops": 0}, {"nope": 1})
    assert [r["reason"] for r in result["rejected"]] == ["invalid_body", "invalid_wire"]


def test_phones_cannot_send_alerts(phone):
    ex = load_example(SHARED_DIR, "alert")
    body = make_body("alert", phone.device_id, "", urgency=4, public=ex["payload"])
    assert phone.send(make_wire(body, None))["rejected"][0]["reason"] == "not_allowed"


def test_outbound_queue_and_cursor(client, phone):
    ctx = client.app.state.ctx
    alert = load_example(SHARED_DIR, "alert")["payload"]
    queued = outbound.queue(ctx.db, ctx.keys, ctx.constants, "alert", alert)
    out = client.get("/api/outbound", params={"since": 0, "device": phone.device_id}).json()
    assert out["cursor"] == queued["seq"] and len(out["packets"]) == 1
    wire = out["packets"][0]
    sign_pk = client.get("/api/setup-qr").json()["sign_pk"]
    assert verify(sign_pk, wire["body"], wire["sig"])
    assert json.loads(wire["body"])["public"]["alert_id"] == "A-0007"
    assert client.get("/api/outbound", params={"since": out["cursor"]}).json()["packets"] == []
    # A phone uploading the alert it relayed is a harmless duplicate.
    assert phone.send(wire)["duplicate"] == [json.loads(wire["body"])["id"]]


def test_snapshot_and_setup_qr_match_the_shared_schemas(client, phone, schemas):
    phone.send(phone.wire("report"), phone.wire("report_heat"))
    assert schemas.errors("snapshot", client.get("/api/snapshot").json()) == []
    assert schemas.errors("setup_qr", client.get("/api/setup-qr").json()) == []
    png = client.get("/api/setup-qr.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_heatstroke_ranks_above_flood_until_scoring_exists(client, phone):
    phone.send(phone.wire("report"), phone.wire("report_heat"))
    cases = client.get("/api/snapshot").json()["cases"]
    assert [c["hazard"] for c in cases] == ["heat", "flood"]


def test_status_and_profiles(client):
    status = client.get("/api/status").json()
    assert status["ok"] is True and status["require_signatures"] is False
    profiles = client.get("/api/profiles").json()
    assert {"flood", "heat", "earthquake"} <= set(profiles["profiles"])


def test_upload_limit(client, phone):
    wires = [phone.wire("report") for _ in range(101)]
    assert client.post("/api/packets", json={"packets": wires}).status_code == 422


def test_phone_kinds_listed_in_conftest_match_server():
    from app.packets import PHONE_KINDS as SERVER_PHONE_KINDS
    assert set(PHONE_KINDS) == SERVER_PHONE_KINDS

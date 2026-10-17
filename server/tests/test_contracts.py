"""The shared formats agree with each other. The Flutter app runs the same checks on shared/examples."""
import json

import pytest
from jsonschema import Draft202012Validator

from app.config import SHARED_DIR
from app.profiles import Profiles

EXAMPLES = sorted(p.stem for p in (SHARED_DIR / "examples").glob("*.json") if p.stem not in ("snapshot", "setup_qr"))


def test_every_schema_is_a_valid_json_schema():
    for path in (SHARED_DIR / "schemas").rglob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", EXAMPLES)
def test_packet_examples_match_their_schemas(schemas, name):
    ex = json.loads((SHARED_DIR / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    body = dict(ex["body"])
    kind = body["kind"]
    if kind in ("alert", "job", "revoke"):
        body["public"] = ex["payload"]
    else:
        body["sealed"] = "c2VhbGVk"
    assert schemas.errors("body", body) == []
    assert schemas.errors(f"payloads/{kind}", ex["payload"]) == []


def test_snapshot_and_setup_qr_examples(schemas):
    for name in ("snapshot", "setup_qr"):
        doc = json.loads((SHARED_DIR / "examples" / f"{name}.json").read_text(encoding="utf-8"))
        assert schemas.errors(name, doc) == [], name


def test_profiles_load_and_their_tokens_point_at_real_questions(schemas):
    profiles = Profiles(SHARED_DIR, schemas)
    assert {"flood", "heat", "earthquake"} <= set(profiles.hazards)


def test_condition_lists_agree(schemas):
    common = json.loads((SHARED_DIR / "profiles" / "common.json").read_text(encoding="utf-8"))
    report = json.loads((SHARED_DIR / "schemas" / "payloads" / "report.schema.json").read_text(encoding="utf-8"))
    assert common["conditions"] == report["properties"]["conditions"]["items"]["enum"]


def test_team_vocabularies_agree(constants):
    profile = json.loads((SHARED_DIR / "schemas" / "profile.schema.json").read_text(encoding="utf-8"))
    needs_enum = profile["properties"]["needs_rules"]["items"]["properties"]["need"]["enum"]
    assert sorted(constants["teams"]["needs"]) == sorted(needs_enum)
    ping = json.loads((SHARED_DIR / "schemas" / "payloads" / "team_ping.schema.json").read_text(encoding="utf-8"))
    assert constants["teams"]["statuses"] == ping["properties"]["status"]["enum"]
    assert set(constants["teams"]["speed_kmh"]) == set(constants["teams"]["types"])

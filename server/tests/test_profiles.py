import json
import shutil

import pytest

from app.config import SHARED_DIR
from app.profiles import ProfileError, Profiles, Token, parse_token, rule_matches


@pytest.fixture(scope="module")
def profiles(schemas):
    return Profiles(SHARED_DIR, schemas)


def test_parse_token():
    assert parse_token("rising") == Token("yes", "rising")
    assert parse_token("!cooling") == Token("no", "cooling")
    assert parse_token("water:waist|chest") == Token("in", "water", ("waist", "chest"))
    assert parse_token("cond:oxygen") == Token("cond", "cond", ("oxygen",))


def test_rule_matching():
    details = {"water": "waist", "rising": True, "signs": ["confused"]}
    assert rule_matches(["water:waist", "rising"], details, set())
    assert not rule_matches(["water:knee", "rising"], details, set())
    assert rule_matches(["signs:fainted|confused"], details, set())
    assert rule_matches(["!trapped"], details, set())
    assert rule_matches(["cond:oxygen"], {}, {"oxygen", "alone"})
    assert rule_matches([], {}, set())


def test_flood_house_14(profiles):
    details = {"water": "waist", "rising": True, "trapped": False}
    conditions = ["elderly", "cannot_walk", "oxygen", "alone"]
    assert profiles.hours_to_critical("flood", details, conditions) == (2.0, "Water at waist and rising")
    assert set(profiles.needs("flood", details, conditions)) == {"boat", "medic"}


def test_flood_default_need_only_when_nothing_specific(profiles):
    assert profiles.needs("flood", {"water": "ankle"}, []) == ["truck"]
    assert profiles.hours_to_critical("flood", {"water": "ankle"}, []) == (24.0, None)


def test_heat_heatstroke(profiles):
    details = {"hot_inside": True, "cooling": False, "signs": ["confused", "hot_dry_skin"]}
    assert profiles.hours_to_critical("heat", details, ["elderly", "alone"]) == (0.5, "Signs of heatstroke")
    assert profiles.needs("heat", details, ["elderly", "alone"]) == ["medic"]


def test_heat_no_cooling_high_risk(profiles):
    details = {"hot_inside": True, "cooling": False}
    assert profiles.hours_to_critical("heat", details, ["elderly"])[0] == 6
    assert profiles.hours_to_critical("heat", details, [])[0] == 12
    assert profiles.needs("heat", details, []) == ["welfare"]


def test_earthquake_trapped(profiles):
    assert profiles.hours_to_critical("earthquake", {"trapped": True}, []) == (1.0, "Trapped under rubble")
    assert profiles.needs("earthquake", {"trapped": True}, []) == ["rescue"]


def test_common_rules_apply_to_unknown_hazards(profiles):
    assert profiles.hours_to_critical("other", {}, ["unconscious"]) == (0.5, "Unconscious or heavy bleeding")
    assert profiles.needs("other", {}, ["bleeding"]) == ["medic"]


def test_bad_token_is_caught(tmp_path, schemas):
    shutil.copytree(SHARED_DIR, tmp_path / "shared")
    flood = tmp_path / "shared" / "profiles" / "flood.json"
    doc = json.loads(flood.read_text(encoding="utf-8"))
    doc["hours_rules"].append({"all": ["water:lake"], "hours": 1, "text": "oops"})
    flood.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProfileError, match="unknown option"):
        Profiles(tmp_path / "shared", schemas)

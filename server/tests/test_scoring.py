"""Priority points, confidence and badges (System Design 9.2, 9.3 and 13.1)."""
from datetime import timedelta

import pytest

from app import scoring, timeutil
from app.scoring import CaseState, ReportInfo

NOW = timeutil.parse("2026-10-18T15:30:00Z")
HOUSE_14 = ["elderly", "cannot_walk", "oxygen", "alone"]


def report(device="dev_A", *, minutes_ago=0, accuracy=15, role="helper", trusted=False, source="app",
           reader="form", located=True) -> ReportInfo:
    return ReportInfo(device, role, reader, source, NOW - timedelta(minutes=minutes_ago),
                      0.0123 if located else None, 0.0456 if located else None, accuracy if located else None,
                      trusted)


def state(reports, *, hours=2.0, text="Water at waist and rising", conditions=HOUSE_14, people=1,
          verified=False, window=None, last_update=None) -> CaseState:
    return CaseState(people=people, conditions=list(conditions), hours_at_ref=hours, hours_ref_at=NOW,
                     hours_text=text, last_update=last_update or max(r.created_at for r in reports),
                     reports=reports, verified=verified, has_location=reports[0].lat is not None,
                     window_closes_at=window)


@pytest.mark.parametrize("hours, points", [
    (0.2, 50), (1, 50), (1.01, 40), (3, 40), (3.5, 25), (6, 25), (6.5, 10), (12, 10), (12.5, 0), (None, 0)])
def test_time_bands_edges_count_in_the_more_urgent_band(constants, hours, points):
    assert scoring.time_points(hours, constants) == points


def test_house_14_two_phones_scores_69(constants):
    s = scoring.score(state([report("dev_SAM01", minutes_ago=25), report("dev_JO02")]), NOW, constants)
    assert s.confidence == 0.75
    assert s.points == 69                                  # 77 x (0.6 + 0.4 x 0.75) = 69.3
    parts = [r for r in s.reasons if r["kind"] != "trust"]
    assert [(r["text"], r["points"]) for r in parts] == [
        ("Water at waist and rising, about 2 h left", 40), ("Cannot walk", 15), ("Elderly", 10),
        ("Lives alone", 10), ("1 person", 2)]
    assert s.reasons[-1] == {"text": "Trust 0.75: 2 reports from 2 phones, GPS 15 m", "points": 0.9, "kind": "trust"}
    assert s.badges == ["2 reports"]


def test_heat_case_from_trusted_volunteer_scores_66(constants):
    r = report("dev_VOL07", accuracy=12, role="volunteer", trusted=True)
    s = scoring.score(state([r], hours=0.5, text="Signs of heatstroke", conditions=["elderly", "alone"]), NOW,
                      constants)
    assert (s.confidence, s.points) == (0.8, 66)          # 72 x 0.92 = 66.2
    assert s.reasons[0]["text"] == "Signs of heatstroke, about 30 min left"


def test_same_phone_twice_does_not_raise_confidence(constants):
    s = scoring.score(state([report(minutes_ago=10), report()]), NOW, constants)
    assert s.confidence == 0.6 and s.points == 65 and s.badges == ["2 reports"]


@pytest.mark.parametrize("role, trusted, source, reader, start", [
    ("helper", False, "app", "form", 0.5), ("helper", True, "app", "form", 0.7),
    ("rescue_team", True, "app", "form", 0.9), ("rescue_team", False, "app", "form", 0.5),
    ("call_taker", False, "call", "form", 0.8), ("helper", False, "paste", "ai", 0.6),
    ("helper", False, "paste", "keywords", 0.4), ("helper", False, "silence", "system", 0.3)])
def test_starting_confidence_by_source(constants, role, trusted, source, reader, start):
    r = report(role=role, trusted=trusted, source=source, reader=reader, accuracy=500)
    assert scoring.confidence(state([r]), NOW, constants)[0] == start


def test_landmark_only_loses_confidence(constants):
    conf, text, _ = scoring.confidence(state([report(located=False)]), NOW, constants)
    assert conf == 0.4 and "landmark only" in text


def test_confidence_decays_every_2_hours_down_to_the_floor(constants):
    r = report(minutes_ago=0)
    assert scoring.confidence(state([r]), NOW + timedelta(hours=1.9), constants)[0] == 0.6
    assert scoring.confidence(state([r]), NOW + timedelta(hours=4), constants)[0] == 0.4
    assert scoring.confidence(state([r]), NOW + timedelta(hours=20), constants)[0] == 0.2


def test_verified_case_has_full_trust(constants):
    s = scoring.score(state([report()], verified=True), NOW + timedelta(hours=5), constants)
    assert s.confidence == 1.0 and "verified" in s.badges and "re-check" not in s.badges


def test_unknown_phone_claiming_many_people_needs_verifying(constants):
    s = scoring.score(state([report(located=False)], people=50), NOW, constants)
    assert s.confidence == 0.2 and "verify" in s.badges    # 0.3 start, -0.1 landmark only, floor 0.2
    s = scoring.score(state([report(), report("dev_B")], people=50), NOW, constants)
    assert s.confidence == 0.55 and "verify" not in s.badges   # a second phone backs it up


def test_people_points_are_capped(constants):
    s = scoring.score(state([report(), report("dev_B")], people=8, conditions=[]), NOW, constants)
    assert next(r for r in s.reasons if r["kind"] == "people") == {"text": "8 people", "points": 10, "kind": "people"}


def test_little_time_and_low_trust_asks_to_verify_fast(constants):
    s = scoring.score(state([report(located=False)], hours=0.5, conditions=[]), NOW, constants)
    assert s.confidence == 0.4 and "verify fast" in s.badges


def test_no_news_for_3_hours_asks_to_recheck(constants):
    s = scoring.score(state([report()]), NOW + timedelta(hours=3), constants)
    assert "re-check" in s.badges


def test_window_points_only_when_it_closes_soon(constants):
    soon = scoring.score(state([report()], window=NOW + timedelta(hours=2)), NOW, constants)
    later = scoring.score(state([report()], window=NOW + timedelta(hours=5)), NOW, constants)
    assert {"text": "Window closes in about 2 h", "points": 20, "kind": "window"} in soon.reasons
    assert all(r["kind"] != "window" for r in later.reasons)


def test_time_passing_raises_urgency(constants):
    later = scoring.score(state([report()]), NOW + timedelta(hours=1.5), constants)
    assert later.hours_left == 0.5 and later.reasons[0]["points"] == 50


def test_nothing_urgent_reported(constants):
    s = scoring.score(state([report()], hours=24, text=None, conditions=[]), NOW, constants)
    assert s.reasons[0] == {"text": "No urgent signs reported", "points": 0, "kind": "time"}
    assert s.points == round(2 * 0.84)


def test_server_made_reports_count_only_while_alone(constants):
    silence = report("command_post", minutes_ago=30, accuracy=None, role="system", source="silence", reader="system")
    alone = scoring.score(state([silence]), NOW, constants)
    assert alone.confidence == 0.3 and alone.badges == []
    joined = scoring.score(state([silence, report("dev_VOL07", trusted=True, accuracy=12)]), NOW, constants)
    assert joined.confidence == 0.8 and joined.badges == []      # trust from the real report, no "2 reports"

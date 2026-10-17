"""Duplicate merging rules (System Design 9.4 and 13.1)."""
from datetime import timedelta

from app import merge, timeutil
from app.merge import Place

NOW = timeutil.parse("2026-10-18T15:30:00Z")
METRE = 1 / 111_195            # degrees of latitude per metre


def place(*, north_m=0.0, minutes=0, people=1, hazard="flood", located=True, landmark=None,
          conditions=("elderly", "oxygen"), note=None) -> Place:
    return Place(hazard=hazard, people=people, at=NOW + timedelta(minutes=minutes),
                 lat=0.0123 + north_m * METRE if located else None, lng=0.0456 if located else None,
                 landmarks=[landmark] if landmark else [], conditions=set(conditions),
                 words=merge.key_words(note, landmark))


def test_two_reports_80_m_apart_30_min_apart_merge(constants):
    metres = merge.match_distance(place(), place(north_m=80, minutes=30), constants["merge"])
    assert metres is not None and 79 < metres < 81


def test_people_2_vs_9_do_not_merge(constants):
    assert merge.match_distance(place(people=2), place(people=9), constants["merge"]) is None


def test_too_far_or_too_late_do_not_merge(constants):
    assert merge.match_distance(place(), place(north_m=200), constants["merge"]) is None
    assert merge.match_distance(place(), place(minutes=4 * 60), constants["merge"]) is None


def test_same_landmark_merges_without_gps(constants):
    a = place(located=False, landmark="Behind the green mosque, house 14")
    b = place(located=False, landmark="behind the green mosque house 14")
    assert merge.match_distance(a, b, constants["merge"]) == 0.0


def test_same_landmark_far_apart_on_gps_is_a_different_place(constants):
    a = place(landmark="house 14")
    b = place(north_m=1000, landmark="house 14")
    assert merge.match_distance(a, b, constants["merge"]) is None


def test_hazard_must_match_unless_one_is_other(constants):
    assert merge.match_distance(place(), place(hazard="heat"), constants["merge"]) is None
    assert merge.match_distance(place(), place(hazard="other"), constants["merge"]) is not None


def test_needs_a_shared_condition_or_word_unless_one_side_says_nothing(constants):
    rules = constants["merge"]
    assert merge.match_distance(place(conditions=["infant"]), place(conditions=["elderly"]), rules) is None
    assert merge.match_distance(place(conditions=["infant"], note="baby and grandmother"),
                                place(conditions=["elderly"], note="grandmother on the roof"), rules) == 0.0
    assert merge.match_distance(place(conditions=["infant"]), place(conditions=[]), rules) == 0.0


def test_key_words_keep_numbers_and_skip_filler():
    assert merge.key_words("behind the green mosque, house 14") == {"green", "mosque", "14"}
    assert merge.norm_landmark("  House 14,  Behind-the Mosque ") == "house 14 behind the mosque"


def test_a_shorter_landmark_inside_a_longer_one_is_the_same_place(constants):
    a = place(located=False, landmark="behind the green mosque, house 14")
    b = place(located=False, landmark="House 14")
    assert merge.match_distance(a, b, constants["merge"]) == 0.0
    assert merge.match_distance(a, place(located=False, landmark="house 140"), constants["merge"]) is None

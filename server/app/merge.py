"""Duplicate merging (System Design 9.4). Pure functions, no database.

A report joins an open case when all of these hold:
  place     within merge.distance_m (both have GPS) or the same landmark text
  time      within merge.window_hours of the case's latest report
  hazard    the same, or one side is "other"
  people    counts differ by at most merge.people_diff
  overlap   a shared condition or key word, or one side gave no detail at all
Several matching cases: the closest wins. No match: the report starts a new case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .packets import distance_m
from .timeutil import hours_between

STOPWORDS = {
    "the", "and", "with", "from", "near", "behind", "next", "opposite", "front", "back", "side",
    "this", "that", "there", "here", "they", "them", "their", "please", "help", "need", "needs",
    "very", "still", "have", "has", "had", "been", "is", "are", "was", "were", "not", "can",
    "cant", "cannot", "our", "your", "his", "her", "him", "she", "who", "what", "where", "floor",
    "house", "home", "flat", "block", "street", "road", "lane", "area", "water", "now", "inside",
}
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Place:
    """What merging needs to know about a report or a case."""
    hazard: str
    people: int
    at: datetime                      # report time, or the case's latest report time
    lat: float | None = None
    lng: float | None = None
    landmarks: list[str] = field(default_factory=list)
    conditions: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)


def norm_landmark(text: str | None) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def key_words(*texts: str | None) -> set[str]:
    """Words that can tie two reports together: house numbers and longer non-filler words."""
    out = set()
    for text in texts:
        for word in _WORD.findall((text or "").lower()):
            if word.isdigit() or (len(word) >= 4 and word not in STOPWORDS):
                out.add(word)
    return out


def has_info(p: Place) -> bool:
    return bool(p.conditions or p.words)


def same_landmark(a: Place, b: Place, min_chars: int) -> bool:
    left = {norm_landmark(x) for x in a.landmarks}
    right = {norm_landmark(x) for x in b.landmarks}
    return any(len(x) >= min_chars for x in left & right)


def match_distance(case: Place, report: Place, rules: dict) -> float | None:
    """Metres between the two (0 for a landmark-only match) if the report belongs to the case,
    otherwise None."""
    if abs(hours_between(case.at, report.at)) > rules["window_hours"]:
        return None
    if case.hazard != report.hazard and "other" not in (case.hazard, report.hazard):
        return None
    if abs(case.people - report.people) > rules["people_diff"]:
        return None

    metres = None
    if None not in (case.lat, case.lng, report.lat, report.lng):
        metres = distance_m(case.lat, case.lng, report.lat, report.lng)
    if metres is not None and metres <= rules["distance_m"]:
        place = metres
    elif same_landmark(case, report, rules["min_landmark_chars"]) and (
            metres is None or metres <= 2 * rules["distance_m"]):
        place = metres or 0.0         # same words but GPS far apart would be a different "house 14"
    else:
        return None

    if has_info(case) and has_info(report):
        if not (case.conditions & report.conditions or case.words & report.words):
            return None
    return place

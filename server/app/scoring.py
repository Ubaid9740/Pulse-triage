"""Priority points, confidence and badges (System Design 9.1 to 9.3). Pure functions, no database.

Points = time points + "can't save themselves" points + window points + people points,
then multiplied by trust = trust_base + trust_slope * confidence. Every part that scores
becomes one line of the explanation card, so the dispatcher sees the real maths.

Reports the server makes itself (an unconfirmed registered person, a zone task) only count
while a case has nothing else: once a real report joins, trust and the report count come
from the real reports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .timeutil import hours_between

SYSTEM_SOURCES = ("silence", "zone_task")
SYSTEM_SQL = f"({', '.join(repr(s) for s in SYSTEM_SOURCES)})"


@dataclass
class ReportInfo:
    device_id: str
    reporter_role: str
    reader: str                 # form | ai | keywords | system
    source: str                 # app | alert_reply | call | paste | welfare_check | silence | ...
    created_at: datetime
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    trusted: bool = False       # device marked trusted by the dispatcher (e.g. a rescue team)


@dataclass
class CaseState:
    people: int
    conditions: list[str]
    hours_at_ref: float | None      # hours to critical at hours_ref_at
    hours_ref_at: datetime
    hours_text: str | None
    last_update: datetime
    reports: list[ReportInfo]
    verified: bool = False
    has_location: bool = True
    window_closes_at: datetime | None = None


@dataclass
class Score:
    points: int
    reasons: list[dict]
    confidence: float
    badges: list[str]
    hours_left: float | None
    extra: dict = field(default_factory=dict)


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def hours_left(case: CaseState, now: datetime) -> float | None:
    if case.hours_at_ref is None:
        return None
    return max(0.0, case.hours_at_ref - hours_between(case.hours_ref_at, now))


def time_points(hours: float | None, constants: dict) -> int:
    """A value exactly on a band edge counts in the more urgent band."""
    if hours is None:
        return 0
    for limit, points in constants["points"]["time_bands_hours"]:
        if limit is None or hours <= limit:
            return points
    return 0


def format_hours(h: float) -> str:
    if h < 1:
        return f"{max(1, round(h * 60))} min"
    text = f"{h:.1f}".rstrip("0").rstrip(".")
    return f"{text} h"


def vulnerability_reasons(conditions: list[str] | set[str], constants: dict) -> list[dict]:
    w = constants["points"]["weights"]
    has = set(conditions)
    out = []
    mobility = [label for key, label in (("cannot_walk", "Cannot walk"), ("disabled", "Disabled")) if key in has]
    if mobility:
        out.append({"text": ", ".join([mobility[0]] + [m.lower() for m in mobility[1:]]),
                    "points": w["cannot_walk"], "kind": "vulnerability"})
    if "elderly" in has:
        out.append({"text": "Elderly", "points": w["elderly"], "kind": "vulnerability"})
    young = [k for k in ("infant", "child", "pregnant") if k in has]
    if young:
        text = ", ".join(young)
        out.append({"text": text[0].upper() + text[1:], "points": w["child"], "kind": "vulnerability"})
    if "alone" in has:
        out.append({"text": "Lives alone", "points": w["alone"], "kind": "vulnerability"})
    return out


def counted(reports: list[ReportInfo]) -> list[ReportInfo]:
    """The reports that count for trust: the real ones, or the system ones if that is all there is."""
    return [r for r in reports if r.source not in SYSTEM_SOURCES] or reports


def source_type(report: ReportInfo) -> str:
    """Which starting confidence a report earns (constants.confidence.start)."""
    if report.source == "silence":
        return "silence"
    if report.source == "call":
        return "call_taker"
    if report.reader == "ai":
        return "ai"
    if report.reader == "keywords":
        return "keywords"
    if report.trusted:
        # A role is only believed once the dispatcher has marked the device trusted.
        if report.reporter_role in ("rescue_team", "call_taker"):
            return report.reporter_role
        return "registered_helper"
    return "unknown_phone"


def confidence(case: CaseState, now: datetime, constants: dict) -> tuple[float, str, bool]:
    """Returns (confidence 0..1, plain explanation, fake_guard_applied)."""
    c = constants["confidence"]
    if not case.reports:
        return c["floor"], "no reports", False
    reports = sorted(counted(case.reports), key=lambda r: r.created_at)
    first = reports[0]
    kind = source_type(first)
    value = c["start"][kind]
    fake = kind == "unknown_phone" and case.people > c["fake_people"]
    if fake:
        value = min(value, c["fake_start"])
    sources = len({r.device_id for r in reports})
    value += c["match_bonus"] * (sources - 1)

    parts = [f"{len(reports)} report{'s' if len(reports) != 1 else ''} from "
             f"{sources} phone{'s' if sources != 1 else ''}"]
    accuracies = [r.accuracy_m for r in reports if r.lat is not None and r.accuracy_m is not None]
    best = min(accuracies) if accuracies else None
    if best is not None and best < c["gps_good_m"]:
        value += c["gps_bonus"]
        parts.append(f"GPS {best:.0f} m")
    elif not case.has_location:
        value -= c["landmark_penalty"]
        parts.append("landmark only")
    if fake:
        parts.append(f"unknown phone claims {case.people} people")

    if case.verified:
        return 1.0, "verified by dispatcher", fake
    steps = math.floor(max(0.0, hours_between(case.last_update, now)) / 2)
    if steps:
        value -= c["decay_per_2h"] * steps
        parts.append(f"no update for {format_hours(hours_between(case.last_update, now))}")
    value = min(1.0, max(c["floor"], value))
    return round(value, 2), ", ".join(parts), fake


def score(case: CaseState, now: datetime, constants: dict) -> Score:
    p = constants["points"]
    w = p["weights"]
    left = hours_left(case, now)
    reasons: list[dict] = []

    tp = time_points(left, constants)
    if case.hours_text and left is not None:
        reasons.append({"text": f"{case.hours_text}, about {format_hours(left)} left", "points": tp, "kind": "time"})
    else:
        reasons.append({"text": "No urgent signs reported", "points": tp, "kind": "time"})

    reasons += vulnerability_reasons(case.conditions, constants)

    if case.window_closes_at is not None:
        until = hours_between(now, case.window_closes_at)
        if 0 <= until <= p["window_hours"]:
            reasons.append({"text": f"Window closes in about {format_hours(until)}", "points": w["window"],
                            "kind": "window"})

    people_points = min(w["person"] * case.people, w["people_max"])
    reasons.append({"text": f"{case.people} {'person' if case.people == 1 else 'people'}",
                    "points": people_points, "kind": "people"})

    raw = sum(r["points"] for r in reasons)
    conf, conf_text, fake = confidence(case, now, constants)
    multiplier = p["trust_base"] + p["trust_slope"] * conf
    reasons.append({"text": f"Trust {conf:.2f}: {conf_text}", "points": round(multiplier, 2), "kind": "trust"})
    points = round_half_up(raw * multiplier)

    c = constants["confidence"]
    badges = []
    n = len(counted(case.reports))
    if n >= 2:
        badges.append(f"{n} reports")
    if case.verified:
        badges.append("verified")
    elif fake and len({r.device_id for r in case.reports}) == 1:
        badges.append("verify")
    if (not case.verified and left is not None and left <= c["verify_fast_hours"]
            and conf < c["verify_fast_below"]):
        badges.append("verify fast")
    if not case.verified and hours_between(case.last_update, now) >= c["recheck_hours"]:
        badges.append("re-check")
    return Score(points, reasons, conf, badges, None if left is None else round(left, 2), {"raw": raw})


def zone_task_score(zone: str, registered: int, rules: dict) -> tuple[int, list[dict]]:
    """'Send welfare-check team' (Team Brief 4.4 h): base points, plus some per registered
    vulnerable person in the zone, capped. A dispatcher created it, so there is no trust factor."""
    base, per, cap = rules["zone_task_base"], rules["zone_task_per_person"], rules["zone_task_max"]
    extra = min(per * registered, cap - base)
    people = f"{registered} registered vulnerable {'person' if registered == 1 else 'people'}"
    return base + extra, [
        {"text": f"Silent Zone welfare check: {zone}", "points": base, "kind": "zone"},
        {"text": f"{people} (+{per} each, up to {cap})", "points": extra, "kind": "zone"},
    ]

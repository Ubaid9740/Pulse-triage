"""First come, first served vs PulseTriage's order, in our simulation (Team Brief 4.10 D3 and 5.4).

    python scenario/simulate.py                    # 20 seeds, every pack; writes scenario/out/simulation.png
    python scenario/simulate.py --seeds 5 --packs flood

For each pack and seed, generate.py builds the same story both ways get: the same situations,
the same teams and the same travel times (distance x detour / speed, as the server's suggestions).
  First come first served: a free team takes the oldest request it knows about. People who never
    report are never reached.
  PulseTriage: a free team takes the case with the most points (server/app/scoring.py, today's
    weights), including welfare checks for registered people who did not answer the warning
    (they become cases when the alert's timeout passes).
Both are judged by the hidden truth in people.json, never by PulseTriage's own points: was a team
at each situation before its deadline? Simplifications: any team can serve any case; a team stays
20 minutes on scene, then leaves from there; merged duplicates are one case.

Always say "in our simulation". This is not a real-world result.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scenario"))

import generate  # noqa: E402
from app import scoring  # noqa: E402
from app.config import SHARED_DIR, load_constants  # noqa: E402
from app.profiles import Profiles  # noqa: E402
from app.schemas import Schemas  # noqa: E402
from app.teams import travel_minutes  # noqa: E402

ON_SCENE_MIN = 20
AFTER_STORY_MIN = 6 * 60
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONSTANTS = load_constants(SHARED_DIR)
PROFILES = Profiles(SHARED_DIR, Schemas(SHARED_DIR))


def cases_for(hazard: str, data: dict) -> list[dict]:
    """Every situation as a case: when the command post learns of it, and how (for trust)."""
    first: dict[str, tuple[float, str]] = {}
    for e in data["messages"]["events"]:
        sid = (e.get("truth") or {}).get("situation")
        if sid and (sid not in first or e["t"] < first[sid][0]):
            first[sid] = (e["t"], e["kind"])
    timeout = CONSTANTS["coverage_timeout_minutes"]["warning"]
    alert_at = generate.STORIES[hazard]["alert_at"]
    out = []
    for p in data["people"]:
        if p["registry_id"] and not p["reported"]:
            known, how = alert_at + timeout, "silence"        # PulseTriage only: a welfare check
        elif p["registry_id"]:
            known, how = p["starts_at"] + 20, "alert_reply"    # "I need help" on the alert
        elif p["id"] in first:
            known, how = first[p["id"]]
        else:
            continue
        out.append(dict(p, known_at=known, how=how))
    return out


def points(case: dict, now_min: float, hazard: str) -> int:
    known = T0 + timedelta(minutes=case["known_at"])
    hours, text = PROFILES.hours_to_critical(hazard, case["details"], case["conditions"])
    source, reader = {"report": ("app", "form"), "text": ("sms", "keywords"),
                      "alert_reply": ("alert_reply", "form"), "silence": ("silence", "system")}[case["how"]]
    state = scoring.CaseState(people=case["people"], conditions=list(case["conditions"]), hours_at_ref=hours,
                              hours_ref_at=known, hours_text=text, last_update=known,
                              reports=[scoring.ReportInfo(case["id"], "helper", reader, source, known,
                                                          case["lat"], case["lng"], 20)])
    return scoring.score(state, T0 + timedelta(minutes=now_min), CONSTANTS).points


def run(hazard: str, data: dict, way: str) -> dict:
    cases = [c for c in cases_for(hazard, data) if way == "pulsetriage" or c["how"] != "silence"]
    all_situations = data["people"]
    speeds, detour = CONSTANTS["teams"]["speed_kmh"], CONSTANTS["teams"]["detour"]
    teams = [{"lat": t["lat"], "lng": t["lng"], "speed": speeds[t["type"]], "free": 0.0} for t in data["teams"]]
    end = generate.STORIES[hazard]["end"] + AFTER_STORY_MIN
    waiting = sorted(cases, key=lambda c: c["known_at"])
    reached: dict[str, float] = {}
    while waiting:
        team = min(teams, key=lambda t: t["free"])
        now = max(team["free"], min(c["known_at"] for c in waiting))
        if now > end:
            break
        known = [c for c in waiting if c["known_at"] <= now]
        if way == "fcfs":
            case = min(known, key=lambda c: c["known_at"])
        else:
            case = max(known, key=lambda c: (points(c, now, hazard), -c["known_at"]))
        arrive = now + travel_minutes(team["lat"], team["lng"], case["lat"], case["lng"], team["speed"], detour)
        reached[case["id"]] = arrive
        team.update(lat=case["lat"], lng=case["lng"], free=arrive + ON_SCENE_MIN)
        waiting.remove(case)

    def in_time(p):
        return p["id"] in reached and reached[p["id"]] <= p["starts_at"] + p["deadline_min"]
    critical = [p for p in all_situations if p["severity"] == "critical"]
    vulnerable = sorted(all_situations, key=lambda p: p["deadline_min"])[:max(1, len(all_situations) // 10)]
    waits = [(reached.get(p["id"], end) - p["starts_at"]) for p in vulnerable]
    return {"critical_in_time": sum(map(in_time, critical)) / len(critical) if critical else 0,
            "all_in_time": sum(map(in_time, all_situations)) / len(all_situations),
            "vulnerable_wait_min": statistics.mean(waits)}


def main() -> None:
    parser = argparse.ArgumentParser(description="FCFS vs PulseTriage, in our simulation.")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--packs", nargs="+", default=list(generate.PACKS), choices=generate.PACKS)
    parser.add_argument("--out", default=str(ROOT / "scenario" / "out" / "simulation.png"))
    args = parser.parse_args()

    results: dict[str, dict[str, list[dict]]] = {}
    for hazard in args.packs:
        results[hazard] = {"fcfs": [], "pulsetriage": []}
        for seed in range(1, args.seeds + 1):
            data = generate.build_pack(hazard, seed)
            for way in ("fcfs", "pulsetriage"):
                results[hazard][way].append(run(hazard, data, way))
        f, p = (results[hazard][w] for w in ("fcfs", "pulsetriage"))
        crit = lambda rs: [r["critical_in_time"] * 100 for r in rs]  # noqa: E731
        wait = lambda rs: [r["vulnerable_wait_min"] for r in rs]  # noqa: E731
        print(f"{hazard:11} critical reached in time: first come first served {statistics.mean(crit(f)):5.1f}% "
              f"({min(crit(f)):.0f}-{max(crit(f)):.0f}), PulseTriage {statistics.mean(crit(p)):5.1f}% "
              f"({min(crit(p)):.0f}-{max(crit(p)):.0f}); most vulnerable 10% wait "
              f"{statistics.mean(wait(f)):.0f} vs {statistics.mean(wait(p)):.0f} min")
    chart(results, args.seeds, Path(args.out))


def chart(results: dict, seeds: int, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    packs = list(results)
    ways = [("fcfs", "First come, first served", "#9aa3ad"), ("pulsetriage", "PulseTriage order", "#d64545")]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    width = 0.36
    for k, (way, name, colour) in enumerate(ways):
        values = [[r["critical_in_time"] * 100 for r in results[p][way]] for p in packs]
        means = [statistics.mean(v) for v in values]
        low = [m - min(v) for m, v in zip(means, values)]
        high = [max(v) - m for m, v in zip(means, values)]
        xs = [i + (k - 0.5) * width for i in range(len(packs))]
        bars = ax.bar(xs, means, width, label=name, color=colour, yerr=[low, high], capsize=4,
                      error_kw={"elinewidth": 1, "ecolor": "#1d2433"})
        for b, m in zip(bars, means):
            ax.text(b.get_x() + b.get_width() / 2, 2, f"{m:.0f}%", ha="center", va="bottom", color="white",
                    fontweight="bold", fontsize=10)
    ax.set_xticks(range(len(packs)), [p.capitalize() for p in packs])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Critical cases reached before their deadline (%)")
    ax.set_title(f"In our simulation: same messages, teams and travel times ({seeds} seeds; bars show the range)",
                 fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print("chart:", out.relative_to(ROOT) if out.is_relative_to(ROOT) else out)


if __name__ == "__main__":
    main()

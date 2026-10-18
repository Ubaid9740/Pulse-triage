"""Hazard profiles: load, check and evaluate the rules in shared/profiles.

Rule tokens (see profile.schema.json):
    x         yes/no answer x is yes
    !x        yes/no answer x is no or missing
    x:a|b     answer x is a or b; for a multi answer, it contains a or b
    cond:a|b  the person has condition a or b
A rule matches when all of its tokens match. An empty token list always matches.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import Schemas


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Token:
    kind: str            # "yes", "no", "in" or "cond"
    key: str             # question id ("cond" for conditions)
    values: tuple[str, ...] = ()


def parse_token(text: str) -> Token:
    if ":" in text:
        key, _, rest = text.partition(":")
        values = tuple(v for v in rest.split("|") if v)
        if not key or not values:
            raise ProfileError(f"bad token {text!r}")
        return Token("cond" if key == "cond" else "in", key, values)
    if text.startswith("!"):
        return Token("no", text[1:])
    return Token("yes", text)


def token_matches(token: Token, details: dict[str, Any], conditions: set[str]) -> bool:
    if token.kind == "cond":
        return any(v in conditions for v in token.values)
    value = details.get(token.key)
    if token.kind == "yes":
        return value is True
    if token.kind == "no":
        return value is not True
    if isinstance(value, list):
        return any(v in value for v in token.values)
    return value in token.values


def rule_matches(tokens: list[str], details: dict[str, Any], conditions: set[str]) -> bool:
    return all(token_matches(parse_token(t), details, conditions) for t in tokens)


class Profiles:
    def __init__(self, shared_dir: Path, schemas: Schemas):
        folder = shared_dir / "profiles"
        docs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))}
        if "common" not in docs:
            raise ProfileError("shared/profiles/common.json is missing")
        problems: list[str] = []
        for name, doc in docs.items():
            problems += [f"{name}.json {e}" for e in schemas.errors("profile", doc)]
            if doc.get("hazard") != name:
                problems.append(f"{name}.json: 'hazard' must be {name!r}")
        if problems:
            raise ProfileError("; ".join(problems))
        self.common: dict = docs.pop("common")
        self.by_hazard: dict[str, dict] = docs
        problems = []
        for name, doc in self.by_hazard.items():
            problems += self._check_tokens(name, doc)
        problems += self._check_tokens("common", self.common, common_only=True)
        if problems:
            raise ProfileError("; ".join(problems))

    @property
    def hazards(self) -> list[str]:
        return sorted(self.by_hazard)

    @property
    def conditions(self) -> list[str]:
        return list(self.common["conditions"])

    def get(self, hazard: str) -> dict:
        """The hazard's profile; 'other' or unknown hazards fall back to common rules only."""
        return self.by_hazard.get(hazard, {"hazard": hazard, "questions": [], "hours_rules": [], "needs_rules": []})

    def questions(self, hazard: str) -> list[dict]:
        return list(self.common.get("questions", [])) + list(self.get(hazard).get("questions", []))

    def hours_to_critical(self, hazard: str, details: dict, conditions: list[str] | set[str]) -> tuple[float, str | None]:
        """Smallest 'hours' among matching rules in common.json and the hazard profile; 24 if none."""
        conds = set(conditions)
        best: tuple[float, str | None] = (24.0, None)
        for rule in self.common["hours_rules"] + self.get(hazard).get("hours_rules", []):
            if rule["hours"] < best[0] and rule_matches(rule["all"], details, conds):
                best = (float(rule["hours"]), rule["text"])
        return best

    def window_text(self, hazard: str, details: dict, conditions: list[str] | set[str]) -> str | None:
        """The profile's window ("Road floods") if it applies to this case; None if it has none or
        its only_if tokens do not match (heat: only people without cooling)."""
        window = self.get(hazard).get("window")
        if not window or not rule_matches(window.get("only_if", []), details, set(conditions)):
            return None
        return window["text"]

    def needs(self, hazard: str, details: dict, conditions: list[str] | set[str]) -> list[str]:
        """Union of needs from matching rules. A profile's default rule (empty token list)
        applies only when no other rule in that profile matched."""
        conds = set(conditions)
        found: list[str] = []
        for rule in self.common.get("needs_rules", []):
            if rule["all"] and rule_matches(rule["all"], details, conds):
                found.append(rule["need"])
        profile_rules = self.get(hazard).get("needs_rules", [])
        specific = [r["need"] for r in profile_rules if r["all"] and rule_matches(r["all"], details, conds)]
        if specific:
            found += specific
        else:
            found += [r["need"] for r in profile_rules if not r["all"]]
        return list(dict.fromkeys(found))

    def check_details(self, hazard: str, details: dict) -> list[str]:
        """Answers that do not fit the hazard's questions (unknown question, option or type)."""
        questions = {q["id"]: q for q in self.questions(hazard)}
        problems = []
        for key, value in details.items():
            q = questions.get(key)
            if q is None:
                problems.append(f"{hazard} has no question {key!r}")
            elif q["type"] == "yesno" and not isinstance(value, bool):
                problems.append(f"{key} is a yes/no answer")
            elif q["type"] == "choice" and value not in q.get("options", []):
                problems.append(f"{key} must be one of {', '.join(q.get('options', []))}")
            elif q["type"] == "multi" and (not isinstance(value, list) or set(value) - set(q.get("options", []))):
                problems.append(f"{key} takes a list of {', '.join(q.get('options', []))}")
        return problems

    def supplies_needed(self, hazard: str, details: dict, conditions: list[str] | set[str]) -> list[str]:
        """Items from matching supply rules in common.json and the hazard profile."""
        conds = set(conditions)
        rules = self.common.get("supply_rules", []) + self.get(hazard).get("supply_rules", [])
        return list(dict.fromkeys(r["item"] for r in rules if rule_matches(r["all"], details, conds)))

    def as_dict(self) -> dict:
        return {"common": self.common, "profiles": self.by_hazard}

    # ---- checks -------------------------------------------------------------------------
    def _check_tokens(self, name: str, doc: dict, common_only: bool = False) -> list[str]:
        """Every token must point at a real question, option or condition."""
        questions = {q["id"]: q for q in self.common.get("questions", [])}
        if not common_only:
            for q in doc.get("questions", []):
                if q["id"] in questions:
                    return [f"{name}.json: question {q['id']!r} repeats a common question"]
                questions[q["id"]] = q
        conditions = set(self.common["conditions"])
        problems: list[str] = []

        def check(token_text: str, where: str) -> None:
            try:
                token = parse_token(token_text)
            except ProfileError as exc:
                problems.append(f"{name}.json {where}: {exc}")
                return
            if token.kind == "cond":
                bad = [v for v in token.values if v not in conditions]
                if bad:
                    problems.append(f"{name}.json {where}: unknown condition(s) {bad}")
                return
            q = questions.get(token.key)
            if q is None:
                problems.append(f"{name}.json {where}: unknown question {token.key!r}")
            elif token.kind in ("yes", "no") and q["type"] != "yesno":
                problems.append(f"{name}.json {where}: {token_text!r} needs a yes/no question")
            elif token.kind == "in":
                if q["type"] == "yesno":
                    problems.append(f"{name}.json {where}: {token_text!r} uses options on a yes/no question")
                else:
                    bad = [v for v in token.values if v not in q.get("options", [])]
                    if bad:
                        problems.append(f"{name}.json {where}: unknown option(s) {bad} for {token.key!r}")

        for section in ("hours_rules", "needs_rules", "supply_rules"):
            for i, rule in enumerate(doc.get(section, [])):
                for t in rule["all"]:
                    check(t, f"{section}[{i}]")
        for t in doc.get("window", {}).get("only_if", []):
            check(t, "window.only_if")
        for t in doc.get("keywords", {}):
            check(t, f"keywords[{t!r}]")
        return problems

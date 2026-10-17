"""The keyword reader: free text into a report's fields, offline and instant (Team Brief 3.9 a).

Each profile's "keywords" map a rule token to phrases. A phrase found in the text (whole words,
any case) sets that token: "x" answers yes, "!x" answers no, "x:a" picks option a (adds it, for
a multi-choice question), "cond:a" adds a condition. Common keywords (people, health) apply to
every disaster.

  disaster   the profile with the most matching tokens; when none match or it is a tie, the
             caller's hint (the dispatcher's choice), then the newest active alert, then the
             active hazard
  choice     several options found: the one listed last in the question (water: roof beats knee)
  yes/no     both found: no wins (for "cooling", "no fan" is the more cautious reading)
  people     "6 people", "family of 5", "we are 4"; else counted groups ("2 adults and 3 kids"); else 1
  landmark   "house 14", "behind the green mosque" and similar, if any

It does not understand negation ("not trapped") or spelling mistakes; the AI reader will.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .profiles import Profiles, parse_token

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "a couple": 2}
_NUM = r"(\d{1,3}|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
_PEOPLE = [re.compile(_NUM + r"\s+(?:people|persons|person|of us|family members|residents)\b"),
           re.compile(r"\bfamily of\s+" + _NUM + r"\b"),
           re.compile(r"\bwe are\s+" + _NUM + r"\b")]
_GROUPS = re.compile(_NUM + r"\s+(?:adults?|kids?|children|child|babies|baby|men|man|women|woman|elderly|old people)\b")
_PLACE_NUMBER = re.compile(r"\b(?:house|flat|apartment|block|building|plot|room)\s*(?:no\.?\s*|number\s*)?\d+[a-z]?\b")
_PLACE_NEAR = re.compile(r"\b(?:near|behind|opposite|next to|in front of|beside|across from)\s+(?:the\s+)?"
                         r"([a-z0-9' -]{3,40}?)(?=[,.;:!?\n]| and | but | where |$)")


def normalise(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").replace("‘", "'").split())


def _has(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(normalise(phrase)) + r"(?![a-z0-9])", text) is not None


def _number(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


@dataclass
class Reading:
    hazard: str
    hazard_from: str                    # "text", "hint", "alert" or "active"
    details: dict = field(default_factory=dict)
    conditions: list[str] = field(default_factory=list)
    people: int = 1
    landmark: str | None = None
    tokens: list[str] = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        return bool(self.tokens)


class KeywordReader:
    def __init__(self, profiles: Profiles):
        self.profiles = profiles

    def read(self, text: str, hint: str | None = None, alert_hazard: str | None = None,
             active: str = "flood") -> Reading:
        clean = normalise(text)
        common = self._matches(clean, self.profiles.common.get("keywords", {}))
        scores = {h: self._matches(clean, self.profiles.get(h).get("keywords", {})) for h in self.profiles.hazards}
        best = max((len(t) for t in scores.values()), default=0)
        leaders = [h for h, t in scores.items() if best and len(t) == best]
        if len(leaders) == 1:
            hazard, source = leaders[0], "text"
        else:
            fallbacks = [(hint, "hint"), (alert_hazard, "alert"), (active, "active")]
            hazard, source = next(((h, s) for h, s in fallbacks if h and (not leaders or h in leaders)),
                                  (leaders[0] if leaders else active, "text" if leaders else "active"))
        tokens = common + scores.get(hazard, [])
        details, conditions = self._fields(hazard, tokens)
        return Reading(hazard, source, details, conditions, self._people(clean), self._landmark(clean), tokens)

    @staticmethod
    def _matches(text: str, keywords: dict[str, list[str]]) -> list[str]:
        return [token for token, phrases in keywords.items() if any(_has(text, p) for p in phrases)]

    def _fields(self, hazard: str, tokens: list[str]) -> tuple[dict, list[str]]:
        questions = {q["id"]: q for q in self.profiles.questions(hazard)}
        details: dict = {}
        conditions: list[str] = []
        for text in tokens:
            token = parse_token(text)
            if token.kind == "cond":
                conditions += [c for c in token.values if c not in conditions]
                continue
            q = questions.get(token.key)
            if q is None:
                continue
            if token.kind in ("yes", "no"):
                details[q["id"]] = token.kind == "yes" and details.get(q["id"], True)   # no wins
            elif q["type"] == "multi":
                details[q["id"]] = list(dict.fromkeys(details.get(q["id"], []) + list(token.values)))
            else:
                options = q.get("options", [])
                picks = [v for v in token.values if v in options] + ([details[q["id"]]] if q["id"] in details else [])
                details[q["id"]] = max(picks, key=options.index)
        return details, [c for c in self.profiles.conditions if c in conditions]

    @staticmethod
    def _people(text: str) -> int:
        counts = [_number(m.group(1)) for p in _PEOPLE for m in p.finditer(text)]
        if counts:
            return max(1, min(max(counts), 500))
        groups = [_number(m.group(1)) for m in _GROUPS.finditer(text)]
        return max(1, min(sum(groups), 500)) if groups else 1

    @staticmethod
    def _landmark(text: str) -> str | None:
        parts = [m.group(0) for m in _PLACE_NEAR.finditer(text)] + [m.group(0) for m in _PLACE_NUMBER.finditer(text)]
        return ", ".join(dict.fromkeys(p.strip() for p in parts))[:200] or None

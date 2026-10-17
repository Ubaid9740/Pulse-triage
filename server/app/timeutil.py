"""UTC time helpers. Everything stored is ISO 8601 UTC with a trailing Z."""
from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse(text: str) -> datetime:
    """Parse ISO 8601; a missing timezone is treated as UTC. Raises ValueError."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600

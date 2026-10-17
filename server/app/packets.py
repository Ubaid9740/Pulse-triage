"""Building wire packets, plus the geohash and distance helpers they need."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from . import timeutil

PUBLIC_KINDS = {"alert", "job", "revoke"}
PHONE_KINDS = {"report", "alert_reply", "welfare_check", "volunteer", "ack", "team_ping"}

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lng: float, precision: int = 5) -> str:
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, bit_count, even = [], 0, 0, True
    while len(out) < precision:
        rng, value = (lng_range, lng) if even else (lat_range, lat)
        mid = (rng[0] + rng[1]) / 2
        bits <<= 1
        if value >= mid:
            bits |= 1
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(_BASE32[bits])
            bits, bit_count = 0, 0
    return "".join(out)


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def body_text(body: dict) -> str:
    """The exact text that gets signed. Compact, UTF-8, key order as given."""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def make_body(kind: str, from_device: str, pubkey: str, *, urgency: int, area: str = "s0000",
              sealed: str | None = None, public: dict | None = None,
              replace_key: str | None = None, to_device: str | None = None,
              created: datetime | None = None, expiry_hours: float = 24, max_hops: int = 12,
              packet_id: str | None = None) -> dict[str, Any]:
    created = created or timeutil.now()
    body: dict[str, Any] = {
        "v": 1,
        "id": packet_id or str(uuid.uuid4()),
        "kind": kind,
        "from_device": from_device,
        "pubkey": pubkey,
        "created_at": timeutil.iso(created),
        "expires_at": timeutil.iso(created + timedelta(hours=expiry_hours)),
        "max_hops": max_hops,
        "area": area,
        "urgency": urgency,
    }
    if replace_key:
        body["replace_key"] = replace_key
    if to_device:
        body["to_device"] = to_device
    if kind in PUBLIC_KINDS:
        body["public"] = public or {}
    else:
        body["sealed"] = sealed or ""
    return body


def make_wire(body: dict, sign: Callable[[str], str] | None) -> dict[str, Any]:
    text = body_text(body)
    return {"body": text, "sig": sign(text) if sign else "", "hops": 0}

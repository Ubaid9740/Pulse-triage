"""Builds packets exactly the way the phone app must. Used by tests and scripts/send_example.py,
and the reference for the Dart implementation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nacl.signing import SigningKey

from .crypto import b64e, seal
from .packets import make_body, make_wire


def phone_wire(kind: str, payload: dict, *, device_id: str, signing_key: SigningKey | None,
               box_pk: str | None, urgency: int, area: str = "s0000", created: datetime | None = None,
               expiry_hours: float = 24, replace_key: str | None = None, to_device: str | None = None,
               packet_id: str | None = None) -> dict:
    """signing_key None -> unsigned (development). box_pk None -> plain base64 payload (development)."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sealed = seal(box_pk, data) if box_pk else b64e(data)
    pubkey = b64e(bytes(signing_key.verify_key)) if signing_key else ""
    body = make_body(kind, device_id, pubkey, urgency=urgency, area=area, sealed=sealed,
                     replace_key=replace_key, to_device=to_device, created=created,
                     expiry_hours=expiry_hours, packet_id=packet_id)
    sign = (lambda text: b64e(signing_key.sign(text.encode("utf-8")).signature)) if signing_key else None
    return make_wire(body, sign)


def load_example(shared_dir: Path, name: str) -> dict:
    return json.loads((shared_dir / "examples" / f"{name}.json").read_text(encoding="utf-8"))

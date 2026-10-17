"""The outbound queue: packets the server sends into the mesh (alerts, jobs, revocations).

Online phones fetch everything after their cursor with GET /api/outbound and pass it on to
offline neighbours. Rows are never deleted during an incident, so a phone that comes online
late still gets every alert that is still valid.
"""
from __future__ import annotations

import json

from . import timeutil
from .crypto import CommandPostKeys
from .db import Database
from .packets import PUBLIC_KINDS, make_body, make_wire

COMMAND_POST = "command_post"


def queue(db: Database, keys: CommandPostKeys, constants: dict, kind: str, public: dict, *,
          area: str = "0", to_device: str | None = None, replace_key: str | None = None,
          expiry_hours: float | None = None) -> dict:
    if kind not in PUBLIC_KINDS:
        raise ValueError(f"the server only sends {sorted(PUBLIC_KINDS)}, not {kind!r}")
    mesh = constants["mesh"]
    body = make_body(kind, COMMAND_POST, keys.sign_pk, urgency=constants["urgency"][kind], area=area,
                     public=public, to_device=to_device, replace_key=replace_key,
                     expiry_hours=expiry_hours or mesh["expiry_hours"], max_hops=mesh["max_hops"])
    wire = make_wire(body, keys.sign)
    now = timeutil.iso(timeutil.now())
    with db.write() as conn:
        conn.execute(
            "INSERT INTO packets(id, kind, from_device, created_at, received_at, hops, body, sig, result) "
            "VALUES(?, ?, ?, ?, ?, 0, ?, ?, 'outbound')",
            (body["id"], kind, COMMAND_POST, body["created_at"], now, wire["body"], wire["sig"]))
        cur = conn.execute(
            "INSERT INTO outbound(packet_id, wire, to_device, created_at) VALUES(?, ?, ?, ?)",
            (body["id"], json.dumps(wire), to_device, now))
        seq = cur.lastrowid
    return {"packet_id": body["id"], "seq": seq, "wire": wire}


def since(db: Database, cursor: int, limit: int = 500) -> dict:
    rows = db.all("SELECT seq, wire FROM outbound WHERE seq > ? ORDER BY seq LIMIT ?", (cursor, limit))
    new_cursor = rows[-1]["seq"] if rows else cursor
    return {"cursor": new_cursor, "packets": [json.loads(r["wire"]) for r in rows]}

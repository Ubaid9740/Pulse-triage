"""Phones the server has heard from, and revoking one (System Design 10.3: a stolen team phone).

Revoking takes effect on the server at once: ingest rejects the device's packets ("revoked").
It also queues a signed revoke packet with the full list of revoked devices (replace_key
"revoke"), so phones keep only the newest list and stop relaying for those devices. Un-revoking
sends a new, shorter list.
"""
from __future__ import annotations

from datetime import datetime

from . import outbound, timeutil
from .cases import CaseBook, NotFound
from .crypto import CommandPostKeys
from .db import Database
from .schemas import Schemas


class DeviceBook:
    def __init__(self, db: Database, keys: CommandPostKeys, schemas: Schemas, cases: CaseBook, constants: dict):
        self.db = db
        self.keys = keys
        self.schemas = schemas
        self.cases = cases
        self.constants = constants

    def views(self) -> list[dict]:
        rows = self.db.all("SELECT d.*, t.id AS team_id FROM devices d LEFT JOIN teams t ON t.device_id = d.id "
                           "ORDER BY d.last_upload_at DESC, d.id")
        return [{"id": r["id"], "team_id": r["team_id"], "role": r["role"], "trusted": bool(r["trusted"]), "revoked": bool(r["revoked"]),
                 "first_seen": r["first_seen"], "last_upload_at": r["last_upload_at"]} for r in rows]

    def revoke(self, device_id: str, revoked: bool, reason: str, by: str, now: datetime | None = None) -> dict:
        """Revoke (or restore) a device and send phones the new list."""
        now = now or timeutil.now()
        with self.db.write() as conn:
            if not conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone():
                raise NotFound(f"unknown device {device_id}")
            conn.execute("UPDATE devices SET revoked = ? WHERE id = ?", (int(revoked), device_id))
            listed = [r[0] for r in conn.execute("SELECT id FROM devices WHERE revoked = 1 ORDER BY id")]
            payload = {"device_ids": listed, "reason": reason[:200]}
            self.schemas.check("payloads/revoke", payload)
            queued = outbound.enqueue(conn, self.keys, self.constants, "revoke", payload, replace_key="revoke",
                                      created=now)
            self.cases.audit(conn, now, by, "revoke" if revoked else "unrevoke", f"device:{device_id}", reason)
        return {"device_id": device_id, "revoked": revoked, "revoked_devices": listed,
                "packet_id": queued["packet_id"], "outbound_seq": queued["seq"]}

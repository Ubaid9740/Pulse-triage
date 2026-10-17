"""Ingest: every packet from every channel goes through Ingestor.ingest_wire.

Steps (System Design 5.2): validate wire -> parse and validate body -> drop duplicates ->
verify signature -> pin the device key -> check times and rate limit -> open the payload ->
validate the payload -> store and dispatch in one transaction.

A report is stored, placed in its zone and merged into a matching open case (or starts a new
one), and that case is rescored. Alert replies and welfare checks update warning coverage; a
welfare check that finds someone in need also becomes a report. Volunteer packets, acks and
location pings go to the team tracker.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import timeutil
from .cases import CaseBook
from .config import Settings
from .coverage import Coverage
from .crypto import CommandPostKeys, b64d, verify
from .db import Database
from .outbound import COMMAND_POST
from .packets import PUBLIC_KINDS
from .profiles import Profiles
from .schemas import Schemas
from .teams import TeamBook
from .zones import ZoneBook

log = logging.getLogger("pulsetriage.ingest")


class Rejected(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Result:
    status: str                      # accepted | duplicate | rejected
    id: str | None = None
    reason: str | None = None
    detail: str = ""
    case_id: int | None = None
    extra: dict = field(default_factory=dict)


class Ingestor:
    def __init__(self, db: Database, keys: CommandPostKeys, schemas: Schemas, profiles: Profiles,
                 settings: Settings, constants: dict, cases: CaseBook, coverage: Coverage, zones: ZoneBook,
                 teams: TeamBook):
        self.db = db
        self.cases = cases
        self.coverage = coverage
        self.zones = zones
        self.teams = teams
        self.keys = keys
        self.schemas = schemas
        self.profiles = profiles
        self.settings = settings
        self.constants = constants

    # ---- public ---------------------------------------------------------------------------
    def ingest_wire(self, wire: object, received_at: datetime | None = None) -> Result:
        received_at = received_at or timeutil.now()
        packet_id = None
        try:
            body = self._parse(wire)
            packet_id = body["id"]
            if self.db.scalar("SELECT 1 FROM packets WHERE id = ?", (packet_id,)):
                return Result("duplicate", packet_id)
            self._check_signature(wire, body)
            created = self._check_times(body, received_at)
            if body["kind"] in PUBLIC_KINDS:
                return self._store_command_post_packet(wire, body, received_at)
            self._check_device(body, received_at)
            self._check_rate_limit(body, received_at)
            payload = self._open_payload(body)
            errors = self.schemas.errors(f"payloads/{body['kind']}", payload)
            if errors:
                raise Rejected("invalid_payload", "; ".join(errors[:3]))
            return self._store_and_dispatch(wire, body, payload, created, received_at)
        except Rejected as rej:
            log.info("rejected packet %s: %s %s", packet_id, rej.reason, rej.detail)
            return Result("rejected", packet_id, rej.reason, rej.detail)

    # ---- steps ----------------------------------------------------------------------------
    def _parse(self, wire: object) -> dict:
        errors = self.schemas.errors("wire", wire)
        if errors:
            raise Rejected("invalid_wire", "; ".join(errors[:3]))
        text = wire["body"]
        if len(text.encode("utf-8")) > self.constants["server"]["max_body_bytes"]:
            raise Rejected("too_big")
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Rejected("invalid_body", f"not JSON: {exc.msg}") from exc
        errors = self.schemas.errors("body", body)
        if errors:
            raise Rejected("invalid_body", "; ".join(errors[:3]))
        return body

    def _check_signature(self, wire: dict, body: dict) -> None:
        sig = wire["sig"]
        if body["kind"] in PUBLIC_KINDS or body["from_device"] == COMMAND_POST:
            # Only the command post makes alerts, jobs and revocations.
            if body["from_device"] != COMMAND_POST or body["kind"] not in PUBLIC_KINDS:
                raise Rejected("not_allowed", "phones cannot send this kind")
            if not verify(self.keys.sign_pk, wire["body"], sig):
                raise Rejected("bad_signature", "not signed by this command post")
            return
        if not sig:
            if self.settings.require_signatures:
                raise Rejected("unsigned")
            return
        if not body["pubkey"] or not verify(body["pubkey"], wire["body"], sig):
            raise Rejected("bad_signature")

    def _check_times(self, body: dict, received_at: datetime) -> datetime:
        server = self.constants["server"]
        try:
            created = timeutil.parse(body["created_at"])
            expires = timeutil.parse(body["expires_at"])
        except ValueError as exc:
            raise Rejected("invalid_body", "bad timestamp") from exc
        if expires < received_at - timedelta(hours=server["clock_skew_hours"]):
            raise Rejected("expired")
        if created > received_at + timedelta(minutes=server["future_limit_minutes"]):
            created = received_at  # the phone clock is ahead; trust our clock instead
        return created

    def _check_device(self, body: dict, received_at: datetime) -> None:
        device_id, pubkey = body["from_device"], body["pubkey"]
        row = self.db.one("SELECT pubkey, revoked FROM devices WHERE id = ?", (device_id,))
        if row and row["revoked"]:
            raise Rejected("revoked")
        if row and row["pubkey"] and pubkey and row["pubkey"] != pubkey:
            raise Rejected("pubkey_mismatch", "this device ID is pinned to another key")

    def _check_rate_limit(self, body: dict, received_at: datetime) -> None:
        if body["kind"] != "report":
            return
        since = timeutil.iso(received_at - timedelta(hours=1))
        count = self.db.scalar(
            "SELECT COUNT(*) FROM packets WHERE from_device = ? AND kind = 'report' "
            "AND result = 'accepted' AND received_at >= ?", (body["from_device"], since))
        if count >= self.constants["rate_limit_reports_per_hour"]:
            raise Rejected("rate_limited")

    def _open_payload(self, body: dict) -> dict:
        sealed = body["sealed"]
        try:
            raw = self.keys.unseal(sealed)
        except ValueError:
            if self.settings.require_sealing:
                raise Rejected("cannot_unseal")
            try:
                raw = b64d(sealed)  # development: plain base64 JSON
            except ValueError as exc:
                raise Rejected("bad_payload", "neither sealed nor base64") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejected("bad_payload", "payload is not JSON") from exc
        if not isinstance(payload, dict):
            raise Rejected("bad_payload", "payload must be an object")
        return payload

    # ---- storage ------------------------------------------------------------------------
    def _insert_packet(self, conn, wire: dict, body: dict, received_at: datetime, result: str) -> None:
        conn.execute(
            "INSERT INTO packets(id, kind, from_device, created_at, received_at, hops, body, sig, result) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (body["id"], body["kind"], body["from_device"], body["created_at"], timeutil.iso(received_at),
             wire["hops"], wire["body"], wire["sig"], result))

    def _store_command_post_packet(self, wire: dict, body: dict, received_at: datetime) -> Result:
        """A valid command post packet we don't have (e.g. relayed back to us). Keep it; no effect."""
        with self.db.write() as conn:
            self._insert_packet(conn, wire, body, received_at, "stored")
        return Result("accepted", body["id"])

    def _store_and_dispatch(self, wire: dict, body: dict, payload: dict, created: datetime,
                            received_at: datetime) -> Result:
        now_iso = timeutil.iso(received_at)
        case_id = None
        with self.db.write() as conn:
            self._insert_packet(conn, wire, body, received_at, "accepted")
            conn.execute(
                "INSERT INTO devices(id, pubkey, first_seen, last_upload_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_upload_at = excluded.last_upload_at, "
                "pubkey = CASE WHEN devices.pubkey = '' OR devices.pubkey IS NULL THEN excluded.pubkey "
                "ELSE devices.pubkey END",
                (body["from_device"], body["pubkey"], now_iso, now_iso))
            kind = body["kind"]
            if kind == "report":
                case_id = self._add_report(conn, body, payload, created, received_at)
            elif kind == "alert_reply":
                self.coverage.record_reply(conn, body, payload, created, received_at)
            elif kind == "welfare_check":
                case_id = self.coverage.record_check(conn, body, payload, created, received_at)
            elif kind == "volunteer":
                self.teams.upsert_volunteer(conn, body, payload, created, received_at)
            elif kind == "ack":
                case_id = self.teams.on_ack(conn, body, payload, created, received_at)
            elif kind == "team_ping":
                case_id = self.teams.on_ping(conn, body, payload, created, received_at)
        self.zones.mark_dirty()
        return Result("accepted", body["id"], case_id=case_id)

    def _add_report(self, conn, body: dict, payload: dict, created: datetime, received_at: datetime) -> int:
        device, rid = body["from_device"], payload.get("registry_id")
        if rid:
            self.coverage.confirm(conn, rid, created, f"report from {device}")
        return self.cases.add_report(conn, {
            "id": body["id"], "packet_id": body["id"],
            "source": "alert_reply" if payload.get("alert_id") else "app",
            "hazard": payload["hazard"], "for_whom": payload["for_whom"], "people": payload["people"],
            "conditions": payload["conditions"], "details": payload["details"], "note": payload.get("note"),
            "lat": payload.get("lat"), "lng": payload.get("lng"), "accuracy_m": payload.get("gps_accuracy_m"),
            "landmark": payload.get("landmark"), "device_id": device, "reporter_role": payload["reporter_role"],
            "reader": "form", "reader_conf": 1.0, "created_at": timeutil.iso(created),
            "received_at": timeutil.iso(received_at), "registry_id": rid}, received_at)

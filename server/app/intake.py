"""The call-taker's intake form and the paste box (Team Brief 3.3 and 3.6).

Both make reports at the command post and send them through the same ingest as phone packets
(signature and seal skipped), so they merge, score and rank like any other report.

Intake (POST /api/intake): the call-taker fills in what they can; a free-text note is read by the
keyword reader to fill the rest (what the call-taker entered wins). Source "call": a call-taker
who spoke to the person starts at confidence 0.8. Several calls taken by the same call-taker
count as one source.

Paste (POST /api/paste): a batch of forwarded messages. Messages are split on chat headers
("[12/10, 14:03] Name: ..." or "12/10/26, 14:03 - Name: ..."), else on blank lines, else one per
line. Each is read by the keyword reader; a message with nothing to act on is skipped and listed.
Source "paste", read by keywords: confidence 0.4. The same message pasted twice is a duplicate.

Simulate (POST /api/reports/simulate, the scenario replay): text messages that came in by SMS or
through the mesh as plain text, each with its sender and, if known, a position. Read like the
paste box; each sender counts as its own source. The same sender and text twice is a duplicate.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from . import timeutil
from .ai_reader import AIReader
from .cases import CaseBook
from .coverage import Coverage
from .db import Database, setting
from .ingest import Ingestor
from .reader import KeywordReader, normalise
from .teams import slug

MAX_PASTE_CHARS = 50_000
MAX_MESSAGES = 100
_CHAT_HEADER = re.compile(r"^\[?\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?,?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?\]?"
                          r"\s*(?:-\s*)?[^:\n]{1,40}:\s*", re.IGNORECASE | re.MULTILINE)
_PASTE_NS = uuid.UUID("6f1d2c3b-8a9e-4f70-b1c2-d3e4f5a6b7c8")


def split_messages(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if _CHAT_HEADER.search(text):
        parts = _CHAT_HEADER.split(text)
    elif re.search(r"\n\s*\n", text):
        parts = re.split(r"\n\s*\n", text)
    else:
        parts = text.split("\n")
    return [" ".join(p.split()) for p in parts if p.strip()]


class Desk:
    def __init__(self, db: Database, ingestor: Ingestor, cases: CaseBook, coverage: Coverage, reader: KeywordReader,
                 ai: AIReader):
        self.db = db
        self.ingestor = ingestor
        self.cases = cases
        self.coverage = coverage
        self.reader = reader
        self.ai = ai

    def intake(self, req: dict, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        reading = self._read(req["note"], req.get("hazard"), now) if req.get("note") else None
        hazard = req.get("hazard") or (reading.hazard if reading else None) or self._active(now)[1]
        problems = self.reader.profiles.check_details(hazard, req.get("details") or {})
        if problems:
            raise ValueError("; ".join(problems))
        filled = reading if reading and reading.hazard == hazard else None
        details = dict(filled.details if filled else {}, **(req.get("details") or {}))
        conditions = list(dict.fromkeys((req.get("conditions") or []) + (filled.conditions if filled else [])))
        payload = {
            "hazard": hazard, "for_whom": req.get("for_whom") or "other",
            "people": req.get("people") or (filled.people if filled else 1),
            "conditions": conditions, "details": details,
            "lat": req.get("lat"), "lng": req.get("lng"), "reporter_role": "call_taker",
        }
        optional = {"note": req.get("note"), "gps_accuracy_m": req.get("gps_accuracy_m"),
                    "landmark": req.get("landmark") or (filled.landmark if filled else None),
                    "contact": req.get("contact"), "registry_id": req.get("registry_id")}
        payload.update({k: v for k, v in optional.items() if v})
        typed = bool(req.get("details") or req.get("conditions"))
        reader = "form" if typed or not filled else "keywords"
        result = self.ingestor.ingest_internal(payload, source="call", reader=reader,
                                               device=f"call:{slug(by)}", received_at=now)
        if reader == "keywords":                          # the AI refines it in the background
            self.ai.enqueue(result.id, req["note"], req.get("hazard"))
        detail = self.cases.detail(result.case_id, now)
        return {"report_id": result.id, "case_id": result.case_id, "case": detail["case"],
                "read": self._public(reading)}

    def paste(self, text: str, hazard: str | None, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        if len(text) > MAX_PASTE_CHARS:
            raise ValueError(f"paste at most {MAX_PASTE_CHARS} characters at a time")
        messages = split_messages(text)
        if len(messages) > MAX_MESSAGES:
            raise ValueError(f"{len(messages)} messages; paste at most {MAX_MESSAGES} at a time")
        reports, skipped = [], []
        for message in messages:
            reading = self._read(message, hazard, now)
            if not reading.found_anything:
                skipped.append({"text": message[:120], "reason": "nothing to act on (no keyword matched)"})
                continue
            payload = {"hazard": reading.hazard, "for_whom": "other", "people": reading.people,
                       "conditions": reading.conditions, "details": reading.details, "note": message[:500],
                       "lat": None, "lng": None, "reporter_role": "helper"}
            if reading.landmark:
                payload["landmark"] = reading.landmark
            packet_id = str(uuid.uuid5(_PASTE_NS, normalise(message)))
            result = self.ingestor.ingest_internal(payload, source="paste", reader="keywords",
                                                   device=f"paste:{slug(by)}", received_at=now, packet_id=packet_id)
            case_id = result.case_id if result.status == "accepted" else self.db.scalar(
                "SELECT case_id FROM reports WHERE id = ?", (packet_id,))
            if result.status == "accepted":
                self.ai.enqueue(result.id, message, hazard or (reading.hazard if reading.hazard_from != "text" else None))
            reports.append({"text": message[:120], "report_id": result.id, "case_id": case_id,
                            "duplicate": result.status == "duplicate", "read": self._public(reading)})
        return {"messages": len(messages), "reports": reports, "skipped": skipped}

    def simulate(self, messages: list[dict], hazard: str | None, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        if len(messages) > MAX_MESSAGES:
            raise ValueError(f"send at most {MAX_MESSAGES} messages at a time")
        out = []
        for m in messages:
            text = " ".join(m["text"].split())[:500]
            reading = self._read(text, m.get("hazard") or hazard, now)
            if not reading.found_anything:
                out.append({"text": text[:120], "status": "skipped", "case_id": None})
                continue
            payload = {"hazard": reading.hazard, "for_whom": "other", "people": reading.people,
                       "conditions": reading.conditions, "details": reading.details, "note": text,
                       "lat": m.get("lat"), "lng": m.get("lng"), "reporter_role": "helper"}
            if m.get("lat") is not None:
                payload["gps_accuracy_m"] = m.get("accuracy_m") or 30
            if reading.landmark:
                payload["landmark"] = reading.landmark
            sender = slug(m.get("sender") or "unknown") or "unknown"
            packet_id = str(uuid.uuid5(_PASTE_NS, f"sms:{sender}:{normalise(text)}"))
            result = self.ingestor.ingest_internal(payload, source="sms", reader="keywords",
                                                   device=f"sms:{sender}", received_at=now, packet_id=packet_id)
            if result.status == "accepted":
                self.ai.enqueue(result.id, text, m.get("hazard") or hazard)
            out.append({"text": text[:120], "status": result.status, "report_id": result.id,
                        "case_id": result.case_id if result.status == "accepted" else self.db.scalar(
                            "SELECT case_id FROM reports WHERE id = ?", (packet_id,))})
        return {"messages": out}

    # ---- helpers ------------------------------------------------------------------------------------
    def _active(self, now: datetime) -> tuple[str | None, str]:
        """(hazard of the newest active alert, the active hazard)."""
        with self.db.read() as conn:
            alerts = self.coverage.active_alerts(conn, now)
            active = setting(conn, "active_hazard", "flood")
        newest = max(alerts, key=lambda a: a["issued_at"])["hazard"] if alerts else None
        return newest, active

    def _read(self, text: str, hint: str | None, now: datetime):
        alert_hazard, active = self._active(now)
        return self.reader.read(text, hint=hint, alert_hazard=alert_hazard, active=active)

    @staticmethod
    def _public(reading) -> dict | None:
        if reading is None:
            return None
        return {"hazard": reading.hazard, "hazard_from": reading.hazard_from, "details": reading.details,
                "conditions": reading.conditions, "people": reading.people, "landmark": reading.landmark}

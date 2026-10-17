"""Demo reset per pack (System Design 14.8: reset_demo.py --pack flood).

A pack is a folder scenario/packs/<name>/:
  pack.json       {"hazard": "flood", "hard_hit": ["Ward 4", ...]}       required
  zones.geojson   the town's zones; else scenario/zones.geojson           one of the two
  registry.csv    the opt-in registry (columns as shared/examples/registry.csv)
  shelters.json   [POST /api/shelters bodies]
  teams.json      [POST /api/teams bodies]
  supplies.json   [{"item", "qty", "place" (command_post, shelter:<id> or team:<id>; default command_post), "warn_at", "unit"}]
Other files (people.json, messages.json, windows.json) are for generate.py and replay.py.

A reset ends the incident on this server and starts the pack's. Cleared: reports, cases, alerts,
replies, zones, registry, teams, jobs, places, supplies and the audit log. Kept: the command post
keys (no new setup QR), the devices (pinned keys and trust; revocations are lifted), the packets
already seen (phones still carrying rehearsal packets cannot bring them back), the outbound
sequence and the alert and job numbers (phones' cursors and "already shown" lists keep working).
Every file is read and checked before anything is cleared, and the old database is backed up.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import timeutil
from .backups import Backups
from .cases import CaseBook, NotFound
from .config import Settings
from .coverage import Coverage
from .db import Database
from .profiles import Profiles
from .supplies import COMMAND_POST, SupplyBook
from .teams import TeamBook
from .zones import ZoneBook

CLEARED = ("reports", "cases", "alerts", "alert_replies", "registry", "zones", "teams", "team_pings",
           "team_status_log", "jobs", "shelters", "supplies", "supply_moves", "audit_log")
KEPT_SETTINGS = ("rev", "alert_number", "job_number")


class DemoReset:
    def __init__(self, db: Database, backups: Backups, cases: CaseBook, zones: ZoneBook, coverage: Coverage,
                 teams: TeamBook, supplies: SupplyBook, profiles: Profiles, settings: Settings):
        self.db = db
        self.backups = backups
        self.cases = cases
        self.zones = zones
        self.coverage = coverage
        self.teams = teams
        self.supplies = supplies
        self.profiles = profiles
        self.settings = settings

    def packs(self) -> list[str]:
        folder = self.settings.scenario_dir / "packs"
        return sorted(p.name for p in folder.iterdir() if (p / "pack.json").exists()) if folder.exists() else []

    def reset(self, pack: str, by: str, now: datetime | None = None) -> dict:
        now = now or timeutil.now()
        plan = self._read(pack)
        backup = self.backups.make(now, label="before-reset")
        with self.db.write() as conn:
            for table in CLEARED:
                conn.execute(f"DELETE FROM {table}")
            conn.execute("UPDATE packets SET result = 'before_reset' WHERE result = 'accepted'")
            top = conn.execute("SELECT MAX(seq) FROM outbound").fetchone()[0]
            if top is not None:                       # keep one empty row so the sequence carries on
                conn.execute("DELETE FROM outbound WHERE seq < ?", (top,))
                conn.execute("UPDATE outbound SET wire = NULL, packet_id = NULL, to_device = NULL WHERE seq = ?", (top,))
            conn.execute(f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(KEPT_SETTINGS))})", KEPT_SETTINGS)
            conn.execute("INSERT INTO settings(key, value) VALUES('active_hazard', ?)", (json.dumps(plan["hazard"]),))
            conn.execute("UPDATE devices SET revoked = 0")
        self.zones.import_geojson(plan["zones"], by, now)
        registry = self.coverage.import_registry(plan["registry"], by, now) if plan["registry"] else None
        for place in plan["shelters"]:
            self.supplies.save_shelter(place, by, now)
        for team in plan["teams"]:
            self.teams.save(team, by, now)
        for row in plan["supplies"]:
            if row.get("qty"):
                self.supplies.move({"kind": "restock", "item": row["item"], "qty": row["qty"],
                                    "to": row.get("place") or COMMAND_POST}, by, now)
            if row.get("warn_at") is not None or row.get("unit"):
                self.supplies.set_level(row["item"], row.get("warn_at"), row.get("unit"), by, now)
        if plan["hard_hit"]:
            self.zones.set_hard_hit(plan["hard_hit"], True, by, now)
        self.zones.update(now)
        with self.db.write() as conn:
            self.cases.audit(conn, now, by, "demo_reset", "server", f"pack {pack}; backup {backup.name}")
        return {"pack": pack, "hazard": plan["hazard"], "zones": len(plan["zones"]["features"]),
                "registry": registry["total"] if registry else 0, "skipped_registry_rows": registry["skipped"] if registry else [],
                "shelters": len(plan["shelters"]), "teams": len(plan["teams"]),
                "supplies": len({r["item"] for r in plan["supplies"]}), "hard_hit": plan["hard_hit"],
                "backup": backup.name}

    def _read(self, pack: str) -> dict:
        """Load and check every file of the pack; nothing is changed if one is wrong."""
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", pack or ""):
            raise ValueError("a pack name is lower-case letters, digits, '-' or '_'")
        folder = self.settings.scenario_dir / "packs" / pack
        if not (folder / "pack.json").exists():
            known = ", ".join(self.packs()) or "none yet"
            raise NotFound(f"no pack {pack!r} in {folder.parent} (packs: {known})")
        meta = _json(folder / "pack.json", dict)
        if meta.get("hazard") not in self.profiles.hazards:
            raise ValueError(f"pack.json: hazard must be one of {', '.join(self.profiles.hazards)}")
        zones_file = folder / "zones.geojson"
        if not zones_file.exists():
            zones_file = self.settings.scenario_dir / "zones.geojson"
        if not zones_file.exists():
            raise ValueError(f"no zones.geojson in {folder} or {self.settings.scenario_dir}")
        zones = _json(zones_file, dict)
        errors = self.zones.schemas.errors("zones", zones)
        if errors:
            raise ValueError(f"{zones_file.name}: " + "; ".join(errors[:3]))
        names = {f["properties"]["name"] for f in zones["features"]}
        hard_hit = meta.get("hard_hit") or []
        unknown = [z for z in hard_hit if z not in names]
        if unknown:
            raise ValueError(f"pack.json: hard_hit names unknown zones: {', '.join(unknown)}")
        plan = {"hazard": meta["hazard"], "zones": zones, "hard_hit": hard_hit,
                "registry": (folder / "registry.csv").read_text(encoding="utf-8-sig")
                if (folder / "registry.csv").exists() else None}
        for name, required in (("shelters", ("id", "name")), ("teams", ("name", "type")), ("supplies", ("item",))):
            rows = _json(folder / f"{name}.json", list) if (folder / f"{name}.json").exists() else []
            for i, row in enumerate(rows):
                if not isinstance(row, dict) or any(not row.get(k) for k in required):
                    raise ValueError(f"{name}.json[{i}] needs {', '.join(required)}")
            plan[name] = rows
        types = self.teams.constants["teams"]["types"]
        bad = [t["name"] for t in plan["teams"] if t["type"] not in types]
        if bad:
            raise ValueError(f"teams.json: unknown type for {', '.join(bad)} ({', '.join(types)})")
        return plan


def _json(path: Path, kind: type):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(doc, kind):
        raise ValueError(f"{path.name} must hold a JSON {'object' if kind is dict else 'list'}")
    return doc

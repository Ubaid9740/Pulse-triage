import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import timeutil  # noqa: E402
from app.config import SHARED_DIR, Settings, load_constants  # noqa: E402
from app.devtools import load_example, phone_wire  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas import Schemas  # noqa: E402

PHONE_KINDS = ["report", "alert_reply", "welfare_check", "volunteer", "ack", "team_ping"]


@pytest.fixture(scope="session")
def schemas() -> Schemas:
    return Schemas(SHARED_DIR)


@pytest.fixture(scope="session")
def constants() -> dict:
    return load_constants(SHARED_DIR)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    overrides.setdefault("scenario_dir", tmp_path / "scenario")
    overrides.setdefault("ai_enabled", False)          # tests never call the API; test_ai_reader uses a fake client
    return Settings(db_path=tmp_path / "test.db", keys_dir=tmp_path / "keys", dashboard_dir=tmp_path / "no-dashboard",
                    backups_dir=tmp_path / "backups", **overrides)


@pytest.fixture
def make_client(tmp_path):
    """make_client(require_signatures=True, ...) -> TestClient on its own fresh database and keys."""
    count = 0

    def _make(**overrides) -> TestClient:
        nonlocal count
        count += 1
        folder = tmp_path / f"server{count}"
        folder.mkdir()
        return TestClient(create_app(make_settings(folder, **overrides)))
    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


class Phone:
    """A fake phone that builds packets like the real app."""

    def __init__(self, client: TestClient, device_id: str = "dev_TEST1"):
        self.client = client
        self.device_id = device_id
        self.key = SigningKey.generate()
        self.box_pk = client.get("/api/setup-qr").json()["box_pk"]

    def wire(self, name: str = "report", *, signed: bool = True, sealed: bool = True, **kw) -> dict:
        ex = load_example(SHARED_DIR, name)
        payload = kw.pop("payload", ex["payload"])
        return phone_wire(ex["body"]["kind"], payload, device_id=kw.pop("device_id", self.device_id),
                          signing_key=self.key if signed else None, box_pk=self.box_pk if sealed else None,
                          urgency=ex["body"]["urgency"], area=ex["body"]["area"],
                          replace_key=ex["body"].get("replace_key"), **kw)

    def send(self, *wires: dict) -> dict:
        resp = self.client.post("/api/packets", json={"packets": list(wires)})
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.fixture
def phone(client) -> Phone:
    return Phone(client)


# ---- zones, registry and alerts ----------------------------------------------------------------
def load_zones(client: TestClient) -> dict:
    """The three example zones: Ward 4 (2,000 people), Riverside (1,500), Old Market (1,000)."""
    doc = json.loads((SHARED_DIR / "examples" / "zones.geojson").read_text(encoding="utf-8"))
    resp = client.post("/api/zones/import", json=doc)
    assert resp.status_code == 200, resp.text
    return resp.json()


def load_registry(client: TestClient, text: str | None = None) -> dict:
    """The example registry (R-0007 and R-0193 in Ward 4, R-0310 in Old Market), or the given CSV."""
    text = text if text is not None else (SHARED_DIR / "examples" / "registry.csv").read_text(encoding="utf-8")
    resp = client.post("/api/registry/import", content=text.encode("utf-8"), headers={"Content-Type": "text/csv"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def registry_csv(people: list[tuple]) -> str:
    """people: (id, zone, conditions 'a;b', lat, lng) -> registry CSV text."""
    lines = ["id,name,zone,lat,lng,conditions,phone,consent_at"]
    for pid, zone, conditions, lat, lng in people:
        lines.append(f"{pid},Demo {pid},{zone},{'' if lat is None else lat},{'' if lng is None else lng},"
                     f"{conditions},,2026-01-01T00:00:00Z")
    return "\n".join(lines) + "\n"


def add_alert(client: TestClient, *, hazard: str = "flood", severity: str = "warning", zones: tuple = ("Ward 4",),
              issued_at: datetime | None = None, valid_hours: float = 12) -> str:
    """Issue an alert through AlertBook as if at issued_at (the API always uses now). Returns its ID."""
    issued = issued_at or timeutil.now()
    req = {"hazard": hazard, "severity": severity, "zones": list(zones), "headline": {"en": "Test alert"},
           "do_now": {"en": []}, "valid_until": timeutil.iso(issued + timedelta(hours=valid_hours))}
    return client.app.state.ctx.alerts.issue(req, "test", now=issued)["alert_id"]

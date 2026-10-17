import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    return Settings(db_path=tmp_path / "test.db", keys_dir=tmp_path / "keys",
                    dashboard_dir=tmp_path / "no-dashboard", **overrides)


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

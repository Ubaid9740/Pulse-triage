"""Data retention: purge personal data, keep anonymous counts (System Design 10.4)."""
import copy
import importlib.util
import json
import sqlite3

import pytest
from conftest import Phone, load_registry, load_zones

from app.config import SERVER_DIR, SHARED_DIR
from app.devtools import load_example
from app.purge import DELETED, after_action, purge


def busy_incident(client, phone):
    """Reports, a merge, a registry, an alert with a reply, a team job done with an outcome."""
    load_zones(client)
    load_registry(client)
    phone.send(phone.wire("report"))
    Phone(client, "dev_JO02").send(Phone(client, "dev_JO02").wire("report"))
    client.post("/api/paste", json={"text": "grandmother confused and very hot, no fan"})
    client.post("/api/alerts", json={"hazard": "flood", "severity": "warning", "zones": ["Ward 4"]})
    reply = copy.deepcopy(load_example(SHARED_DIR, "alert_reply")["payload"])
    phone.send(phone.wire("alert_reply", payload=dict(reply, alert_id="A-0001", registry_id="R-0007")))
    client.post("/api/teams", json={"id": "boat_2", "name": "Boat 2", "type": "boat", "skills": ["nurse_doctor"],
                                    "lat": 0.0, "lng": 0.0456, "device_id": "dev_BOAT2"})
    client.post("/api/supplies/move", json={"kind": "restock", "item": "oxygen_cylinder", "qty": 3})
    client.post("/api/supplies/move", json={"kind": "load", "item": "oxygen_cylinder", "qty": 1, "to": "team:boat_2"})
    case_id = next(c["id"] for c in client.get("/api/snapshot").json()["cases"] if c["hazard"] == "flood")
    client.post("/api/assign", json={"case_id": case_id, "team_id": "boat_2"})
    boat = Phone(client, "dev_BOAT2")
    boat.send(boat.wire("ack", payload={"team_id": "boat_2", "job_id": "J-001", "status": "arrived"}))
    boat.send(boat.wire("ack", payload={"team_id": "boat_2", "job_id": "J-001", "status": "done",
                                        "outcome": {"people_helped": 1, "supplies_used": {"oxygen_cylinder": 1}}}))


def test_the_counts_name_and_locate_nobody(client, phone):
    busy_incident(client, phone)
    counts = after_action(client.app.state.ctx.db)
    assert counts["reports"]["total"] == 3 and counts["reports"]["by_source"] == {"app": 2, "paste": 1}
    assert counts["cases"]["merged"] == 1 and counts["cases"]["by_zone"] == {"Ward 4": "<5", "unknown": "<5"}
    assert counts["jobs"]["people_helped"] == 1 and counts["jobs"]["by_status"] == {"done": 1}
    assert counts["registry"] == {"registered": 3, "confirmed": 1} and counts["alerts"]["replies"] == {"safe": 1}
    assert counts["supplies_used"] == {"oxygen_cylinder": 1}
    text = json.dumps(counts)
    for personal in ("R-0007", "Demo Resident", "dev_", "mosque", "house 14", "0.0123", "oxygen tank"):
        assert personal not in text


def test_purge_deletes_personal_data_and_keeps_the_rest(client, phone, tmp_path):
    busy_incident(client, phone)
    ctx = client.app.state.ctx
    ctx.backups.make()
    out = purge(ctx.db, tmp_path / "after_action", ctx.settings.backups_dir)
    assert out["deleted_rows"]["reports"] == 3 and out["deleted_rows"]["registry"] == 3 and out["backups_deleted"] == 1
    report = json.loads(open(out["after_action"], encoding="utf-8").read())
    assert report["jobs"]["people_helped"] == 1
    with sqlite3.connect(ctx.settings.db_path) as conn:
        for table in DELETED:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM outbound WHERE wire IS NOT NULL").fetchone()[0] == 0
        team = conn.execute("SELECT device_id, ping_at, status, lat FROM teams").fetchone()
        assert team == (None, None, "available", 0.0)
        assert conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1
        raw = ctx.settings.db_path.read_bytes()
    assert b"mosque" not in raw and b"Demo Resident" not in raw            # vacuumed: nothing left in free pages
    snap = client.get("/api/snapshot").json()
    assert snap["cases"] == [] and [z["registered"] for z in snap["zones"]] == [0, 0, 0]
    assert client.get("/api/outbound?since=0").json()["packets"] == []


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, value in {"PT_DB_PATH": tmp_path / "srv" / "pulsetriage.db", "PT_KEYS_DIR": tmp_path / "srv" / "keys",
                       "PT_BACKUPS_DIR": tmp_path / "srv" / "backups", "PT_SCENARIO_DIR": tmp_path / "scenario",
                       "PT_PORT": "59996", "PT_AI": "off"}.items():
        monkeypatch.setenv(key, str(value))
    return tmp_path


def test_the_script_is_a_dry_run_unless_told(env, capsys):
    spec = importlib.util.spec_from_file_location("purge_script", SERVER_DIR / "scripts" / "purge.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main([]) == 1                                      # no database yet
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app(Settings.from_env()))
    Phone(client).send(Phone(client).wire("report"))
    client.app.state.ctx.db.close()
    assert script.main([]) == 0 and "Dry run" in capsys.readouterr().out
    with sqlite3.connect(env / "srv" / "pulsetriage.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
    assert script.main(["--yes", "--report-dir", str(env / "aa")]) == 0 and "Purged" in capsys.readouterr().out
    with sqlite3.connect(env / "srv" / "pulsetriage.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
    assert len(list((env / "aa").glob("after-action-*.json"))) == 1

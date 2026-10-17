"""Revoking devices, backups and the demo reset (System Design 10.3, 11.4 and 14.8)."""
import importlib.util
import json
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import Phone, load_zones

from app import timeutil
from app.backups import Backups, copy_database, restore_database
from app.config import SERVER_DIR, SHARED_DIR
from app.crypto import verify


def script(name):
    spec = importlib.util.spec_from_file_location(name, SERVER_DIR / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_pack(scenario: Path, name="heat", **files) -> Path:
    """A small heat pack: three zones, the example registry, a cooling centre, a volunteer, supplies."""
    folder = scenario / "packs" / name
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(SHARED_DIR / "examples" / "zones.geojson", scenario / "zones.geojson")
    shutil.copy(SHARED_DIR / "examples" / "registry.csv", folder / "registry.csv")
    content = {
        "pack.json": {"hazard": "heat", "hard_hit": ["Ward 4"]},
        "shelters.json": [{"id": "cool_hall", "name": "Community hall", "type": "cooling_centre", "lat": 0.015,
                           "lng": 0.041, "capacity": 120}],
        "teams.json": [{"id": "vol_7", "name": "Volunteer 7", "type": "volunteer", "lat": 0.02, "lng": 0.04,
                        "device_id": "dev_VOL07"}],
        "supplies.json": [{"item": "drinking_water", "qty": 500, "warn_at": 100},
                          {"item": "oral_rehydration_salts", "qty": 20, "place": "team:vol_7"}],
    }
    content.update(files)
    for file, doc in content.items():
        (folder / file).write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return folder


# ---- revoke ---------------------------------------------------------------------------------------------
def test_a_revoked_phone_is_refused_and_phones_get_the_list(client, phone, schemas):
    phone.send(phone.wire("report"))
    assert client.post("/api/devices/dev_NOPE/revoke", json={}).status_code == 404
    out = client.post(f"/api/devices/{phone.device_id}/revoke", json={"reason": "Team phone reported stolen"}).json()
    assert out["revoked_devices"] == [phone.device_id] and out["outbound_seq"] == 1
    [wire] = client.get("/api/outbound?since=0").json()["packets"]
    body = json.loads(wire["body"])
    assert verify(client.app.state.ctx.keys.sign_pk, wire["body"], wire["sig"])
    assert (body["kind"], body["urgency"], body["replace_key"]) == ("revoke", 4, "revoke")
    assert body["public"] == {"device_ids": [phone.device_id], "reason": "Team phone reported stolen"}
    assert phone.send(phone.wire("report"))["rejected"][0]["reason"] == "revoked"
    assert client.get("/api/devices").json()["devices"][0]["revoked"] is True

    out = client.post(f"/api/devices/{phone.device_id}/revoke", json={"revoked": False, "reason": "Found"}).json()
    assert out["revoked_devices"] == []
    last = json.loads(client.get("/api/outbound?since=1").json()["packets"][0]["body"])["public"]
    assert schemas.errors("payloads/revoke", last) == [] and last["device_ids"] == []
    assert phone.send(phone.wire("report"))["accepted"]


# ---- backups ----------------------------------------------------------------------------------------------
def test_backups_every_5_minutes_keeping_the_newest(client, phone, constants, tmp_path):
    phone.send(phone.wire("report"))
    ctx = client.app.state.ctx
    now = timeutil.now()
    first = ctx.backups.run(now)
    assert first.exists() and ctx.backups.run(now + timedelta(minutes=4)) is None
    assert ctx.backups.run(now + timedelta(minutes=5)) is not None
    with sqlite3.connect(first) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    assert client.get("/api/status").json()["last_backup"] == timeutil.iso(now + timedelta(minutes=5))
    few = Backups(ctx.db, tmp_path / "few", dict(constants, server=dict(constants["server"], backups_kept=2)))
    for minutes in (0, 10, 20):
        few.make(now + timedelta(minutes=minutes))
    assert len(few.files()) == 2 and few.files()[0].name.endswith(
        (now + timedelta(minutes=20)).strftime("%Y%m%d-%H%M%S") + ".db")


def test_copy_and_restore(client, phone, tmp_path):
    phone.send(phone.wire("report"))
    db_path = client.app.state.ctx.settings.db_path
    copy = tmp_path / "copy.db"
    copy_database(db_path, copy)                                 # while the server has it open
    target = tmp_path / "laptop2" / "pulsetriage.db"
    target.parent.mkdir()
    assert restore_database(copy, target) is None
    kept = restore_database(copy, target)
    assert kept is not None and kept.exists()
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1


# ---- the demo reset -------------------------------------------------------------------------------------------
def test_reset_starts_the_pack_and_keeps_what_phones_rely_on(client, phone, schemas):
    ctx = client.app.state.ctx
    load_zones(client)
    report = phone.wire("report")
    phone.send(report)
    client.post("/api/alerts", json={"hazard": "flood", "severity": "warning", "zones": ["Ward 4"]})
    vol = Phone(client, "dev_VOL07")
    vol.send(vol.wire("report_heat"))
    client.post("/api/devices/dev_VOL07/trust", json={"trusted": True})
    client.post(f"/api/devices/{phone.device_id}/revoke", json={})
    old_cursor = client.get("/api/outbound?since=0").json()["cursor"]
    write_pack(ctx.settings.scenario_dir)
    assert client.get("/api/demo/packs").json() == {"packs": ["heat"]}

    out = client.post("/api/demo/reset", json={"pack": "heat"}).json()
    assert {k: out[k] for k in ("hazard", "zones", "registry", "shelters", "teams", "supplies", "hard_hit")} == {
        "hazard": "heat", "zones": 3, "registry": 3, "shelters": 1, "teams": 1, "supplies": 2, "hard_hit": ["Ward 4"]}
    assert (ctx.settings.backups_dir / out["backup"]).exists() and out["backup"].endswith("before-reset.db")

    snap = client.get("/api/snapshot").json()
    assert schemas.errors("snapshot", snap) == []
    assert snap["cases"] == [] and snap["alerts"] == [] and snap["hazard"] == "heat"
    assert [z["name"] for z in snap["zones"] if z["hard_hit"]] == ["Ward 4"]
    assert [(t["id"], t["device_id"], t["load"]) for t in snap["teams"]] == [
        ("vol_7", "dev_VOL07", {"oral_rehydration_salts": 20})]
    water = next(s for s in snap["supplies"] if s["item"] == "drinking_water")
    assert (water["left"], water["warn_at"]) == (500, 100)
    devices = {d["id"]: d for d in client.get("/api/devices").json()["devices"]}
    assert devices["dev_VOL07"]["trusted"] and not devices[phone.device_id]["revoked"]

    assert client.get("/api/outbound?since=0").json() == {"cursor": old_cursor, "packets": []}
    new = client.post("/api/alerts", json={"hazard": "heat", "severity": "warning", "zones": ["Ward 4"],
                                           "fill": {"start": "12:00", "end": "17:00"}}).json()
    assert new["alert_id"] == "A-0002" and new["outbound_seq"] == old_cursor + 1
    assert len(phone.send(report)["duplicate"]) == 1                # a rehearsal packet cannot come back
    assert client.get("/api/snapshot").json()["cases"] == []
    with ctx.db.read() as conn:
        assert [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE action = 'demo_reset'")] == ["demo_reset"]


@pytest.mark.parametrize("pack, files, status, message", [
    ("Flood!", {}, 400, "lower-case"),
    ("missing", None, 404, "no pack 'missing'"),
    ("heat", {"teams.json": [{"name": "Raft 1", "type": "raft"}]}, 400, "unknown type for Raft 1"),
    ("heat", {"pack.json": {"hazard": "heat", "hard_hit": ["Atlantis"]}}, 400, "unknown zones: Atlantis"),
    ("heat", {"supplies.json": "{not json"}, 400, "supplies.json is not valid JSON"),
])
def test_a_bad_pack_changes_nothing(client, phone, pack, files, status, message):
    phone.send(phone.wire("report"))
    if files is not None:
        write_pack(client.app.state.ctx.settings.scenario_dir, **files)
    resp = client.post("/api/demo/reset", json={"pack": pack})
    assert resp.status_code == status and message in resp.json()["detail"]
    assert len(client.get("/api/snapshot").json()["cases"]) == 1


# ---- the scripts -------------------------------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = {"PT_DB_PATH": tmp_path / "srv" / "pulsetriage.db", "PT_KEYS_DIR": tmp_path / "srv" / "keys",
             "PT_BACKUPS_DIR": tmp_path / "srv" / "backups", "PT_SCENARIO_DIR": tmp_path / "scenario"}
    for key, value in paths.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("PT_PORT", "59997")                       # nothing listens there
    return paths


def test_reset_and_backup_scripts(env, capsys):
    write_pack(env["PT_SCENARIO_DIR"])
    reset, backup = script("reset_demo"), script("backup")
    assert reset.main(["--list"]) == 0 and capsys.readouterr().out.strip() == "heat"
    assert reset.main(["--pack", "heat"]) == 0
    assert json.loads(capsys.readouterr().out)["teams"] == 1
    assert reset.main(["--pack", "heat", "--keep-server"]) == 1          # no server to reset
    assert reset.main(["--pack", "nope"]) == 1

    assert backup.main([]) == 0 and "Backed up to" in capsys.readouterr().out
    assert backup.main(["--list"]) == 0 and "backups in" in capsys.readouterr().out
    assert backup.main(["--restore"]) == 0 and "Restored" in capsys.readouterr().out
    with sqlite3.connect(env["PT_DB_PATH"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 3

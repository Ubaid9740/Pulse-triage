"""The scenario replay: a pack's story through the normal paths, and teams that move."""
import json
import shutil
import time

from conftest import add_alert

from app.config import SHARED_DIR

REPORT = {"hazard": "flood", "for_whom": "neighbour", "people": 3, "conditions": ["elderly"],
          "details": {"water": "waist", "rising": True}, "note": "Water rising, grandmother upstairs",
          "lat": 0.0123, "lng": 0.0456, "gps_accuracy_m": 15, "landmark": "house 14",
          "reporter_role": "helper", "contact": ""}


def write_pack(client, events, teams=()):
    scenario = client.app.state.ctx.settings.scenario_dir
    folder = scenario / "packs" / "mini"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(SHARED_DIR / "examples" / "zones.geojson", scenario / "zones.geojson")
    shutil.copy(SHARED_DIR / "examples" / "registry.csv", folder / "registry.csv")
    (folder / "pack.json").write_text(json.dumps({"hazard": "flood", "hard_hit": ["Ward 4"]}), encoding="utf-8")
    (folder / "teams.json").write_text(json.dumps(list(teams)), encoding="utf-8")
    (folder / "messages.json").write_text(json.dumps({"start": "14:00", "speed": 600, "events": events}),
                                          encoding="utf-8")


def wait_for(client, check, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"timed out; replay: {client.get('/api/demo/replay').json()}")


def test_the_story_arrives_through_the_normal_paths(client):
    write_pack(client, [
        {"t": 0, "kind": "cue", "text": "River rising"},
        {"t": 1, "kind": "report", "device": "dev_R01", "payload": REPORT, "truth": {"severity": "critical"}},
        {"t": 2, "kind": "text", "sender": "+000 555 0101", "lat": 0.0124, "lng": 0.0457,
         "text": "water till waist granny upstairs house 14 pls help"},
        {"t": 3, "kind": "window", "zone": "Ward 4", "closes_in_min": 120, "text": "Bridge Rd floods"},
        {"t": 4, "kind": "reply", "device": "dev_REG07", "registry_id": "R-0007", "status": "safe"},
    ])
    out = client.post("/api/demo/replay", json={"pack": "mini"}).json()
    assert out["running"] is True and out["reset"]["zones"] == 3 and out["total"] == 5
    status = wait_for(client, lambda: (s := client.get("/api/demo/replay").json())["done"] == 5 and s)
    assert status["cues"][0]["text"] == "Ward 4: Bridge Rd floods in 120 min" and status["scenario_time"] >= "14:04"
    assert status["held_replies"] == 1 and not status["errors"]            # no alert yet: the reply waits

    [case] = client.get("/api/snapshot").json()["cases"]
    assert case["report_count"] == 2 and case["window_closes_at"]
    assert any(r["text"].startswith("Bridge Rd floods in about") for r in case["reasons"])

    add_alert(client, zones=("Ward 4",))
    wait_for(client, lambda: client.get("/api/demo/replay").json()["held_replies"] == 0)
    assert client.get("/api/coverage").json()["overall"]["confirmed"] == 1     # R-0007 said "I'm safe"
    assert client.post("/api/demo/replay/stop").json()["running"] is False


def test_a_team_with_a_phone_drives_to_its_case_and_finishes(client):
    team = {"id": "boat_9", "name": "Boat 9", "type": "boat", "lat": 0.0123, "lng": 0.0356, "device_id": "dev_BOAT9"}
    write_pack(client, [{"t": 0, "kind": "report", "device": "dev_R01", "payload": REPORT}], teams=[team])
    client.post("/api/demo/replay", json={"pack": "mini"})
    case = wait_for(client, lambda: client.get("/api/snapshot").json()["cases"])[0]
    assert client.post("/api/assign", json={"case_id": case["id"], "team_id": "boat_9"}).status_code == 200

    def boat():
        return next(t for t in client.get("/api/teams").json()["teams"] if t["id"] == "boat_9")
    wait_for(client, lambda: boat()["status"] == "on_scene")
    wait_for(client, lambda: boat()["status"] in ("returning", "available"), seconds=20)
    assert len(boat()["trail"]) >= 2
    client.post("/api/demo/replay/stop")


def test_a_pack_without_a_story_is_refused_before_any_reset(client):
    write_pack(client, [])
    (client.app.state.ctx.settings.scenario_dir / "packs" / "mini" / "messages.json").unlink()
    assert client.post("/api/demo/replay", json={"pack": "mini"}).status_code == 404
    assert client.post("/api/demo/replay", json={"pack": "../x"}).status_code == 422


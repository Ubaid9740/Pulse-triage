"""Zones and Silent Zones (System Design 9.5 and 13.1; Team Brief 4.4 h)."""
import copy
import json
from datetime import timedelta

import pytest
from conftest import Phone, add_alert, load_registry, load_zones, registry_csv

from app import timeutil
from app.config import SHARED_DIR
from app.devtools import load_example
from app.scoring import zone_task_score
from app.zones import ZoneCount, ZoneMap, centroid, contains, find_silent

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                                             [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
# Points inside the example zones (lat, lng).
IN_WARD_4, IN_RIVERSIDE, IN_OLD_MARKET = (0.015, 0.040), (0.015, 0.030), (0.030, 0.040)


def zone(name, population, actual=0, registered=0, confirmed=0, hard_hit=True) -> ZoneCount:
    return ZoneCount(name, population, hard_hit, actual, registered, confirmed)


# ---- geometry -----------------------------------------------------------------------------------
def test_points_in_polygons_respect_holes_and_multipolygons():
    assert contains(SQUARE, 1, 1) and not contains(SQUARE, 5, 5) and not contains(SQUARE, 11, 5)
    multi = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"],
                                                     [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]]}
    assert contains(multi, 25, 25) and not contains(multi, 15, 15)


def test_centroid_and_locate():
    lat, lng = centroid({"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]]})
    assert (lat, lng) == pytest.approx((1, 2))
    doc = json.loads((SHARED_DIR / "examples" / "zones.geojson").read_text(encoding="utf-8"))
    zones = ZoneMap([{"name": f["properties"]["name"], "polygon": f["geometry"]} for f in doc["features"]])
    assert zones.locate(0.0123, 0.0456) == "Ward 4" and zones.locate(*IN_RIVERSIDE) == "Riverside"
    assert zones.locate(0.5, 0.5) is None and zones.locate(None, 0.04) is None


# ---- the Silent Zone test -------------------------------------------------------------------------
def test_ward_4_worked_example_is_silent(constants):
    zones = [zone("Ward 4", 2000, actual=2, registered=41, confirmed=9),
             zone("Riverside", 1500, actual=18), zone("Old Market", 1000, actual=12)]
    ward = find_silent(zones, constants["silent"])["Ward 4"]
    assert ward.rate == pytest.approx(1.2) and ward.expected == pytest.approx(24)
    assert ward.ratio == pytest.approx(2 / 24) and ward.coverage == pytest.approx(9 / 41)
    assert ward.quiet and ward.unheard and ward.silent


def test_quiet_needs_8_expected_reports_and_unheard_needs_10_registered(constants):
    rules = constants["silent"]
    small = find_silent([zone("Small", 500), zone("Other", 1000, actual=15)], rules)["Small"]
    assert small.expected == pytest.approx(7.5) and not small.quiet          # 7.5 expected is too few to judge
    few = find_silent([zone("A", 100, registered=9), zone("B", 100)], rules)["A"]
    assert not few.unheard                                                    # 9 registered, none confirmed
    many = find_silent([zone("A", 100, registered=10, confirmed=2), zone("B", 100)], rules)["A"]
    assert many.unheard and many.coverage == 0.2


def test_quarter_of_the_expected_reports_is_enough(constants):
    zones = [zone("A", 800, actual=2), zone("B", 1000, actual=10)]          # A expects 8
    assert not find_silent(zones, constants["silent"])["A"].quiet
    zones[0] = zone("A", 800, actual=1)
    assert find_silent(zones, constants["silent"])["A"].quiet


def test_default_rate_when_nothing_to_compare_with(constants):
    only = find_silent([zone("Alone", 2000)], constants["silent"])["Alone"]
    assert only.rate == constants["silent"]["default_rate_per_100"] and only.expected == 20 and only.silent


def test_zones_that_are_not_hard_hit_are_never_silent(constants):
    calm = find_silent([zone("Calm", 5000, registered=50, hard_hit=False)], constants["silent"])["Calm"]
    assert not calm.silent and calm.expected is None and calm.coverage == 0


@pytest.mark.parametrize("registered, points", [(0, 60), (12, 72), (30, 90), (41, 90)])
def test_zone_task_points(constants, registered, points):
    total, reasons = zone_task_score("Ward 4", registered, constants["silent"])
    assert total == points and sum(r["points"] for r in reasons) == points
    assert {r["kind"] for r in reasons} == {"zone"}


# ---- through the API --------------------------------------------------------------------------------
def report_at(lat, lng) -> dict:
    """The house 14 report moved to (lat, lng), with no conditions, landmark or note."""
    p = copy.deepcopy(load_example(SHARED_DIR, "report")["payload"])
    p.update(lat=lat, lng=lng, conditions=[])
    p.pop("landmark", None)
    p.pop("note", None)
    return p


def zones_by_name(client) -> dict:
    return {z["name"]: z for z in client.get("/api/snapshot").json()["zones"]}


def test_import_places_reports_and_cases_in_their_zones(client, phone, schemas):
    phone.send(phone.wire("report"))                    # house 14, before any zones exist
    assert client.get("/api/snapshot").json()["cases"][0]["zone"] is None
    assert load_zones(client) == {"zones": 3, "reports_located": 1}
    phone.send(phone.wire("report_heat"))
    cases = client.get("/api/snapshot").json()["cases"]
    assert {c["zone"] for c in cases} == {"Ward 4"}
    case = client.get(f"/api/cases/{cases[0]['id']}").json()
    assert schemas.errors("case_detail", case) == [] and case["reports"][0]["zone"] == "Ward 4"
    snap = client.get("/api/snapshot").json()
    assert schemas.errors("snapshot", snap) == [] and len(snap["zones"]) == 3
    assert client.get("/api/setup-qr").json()["zones"] == ["Old Market", "Riverside", "Ward 4"]


def test_bad_zones_files_are_rejected(client):
    assert client.post("/api/zones/import", json={"type": "FeatureCollection", "features": []}).status_code == 400
    doc = json.loads((SHARED_DIR / "examples" / "zones.geojson").read_text(encoding="utf-8"))
    doc["features"][1]["properties"]["name"] = "Ward 4"
    resp = client.post("/api/zones/import", json=doc)
    assert resp.status_code == 400 and "unique" in resp.json()["detail"]


def test_a_quiet_hard_hit_zone_turns_silent_and_fades_when_reports_arrive(client, phone, schemas):
    load_zones(client)
    assert not any(z["hard_hit"] for z in zones_by_name(client).values())
    resp = client.post("/api/zones/hard-hit", json={"zones": ["Ward 4", "Riverside", "Old Market"]})
    assert resp.status_code == 200 and all(z["hard_hit"] for z in resp.json()["zones"])
    zones = zones_by_name(client)
    assert all(z["silent"] and z["quiet"] for z in zones.values())        # nobody has reported yet
    assert zones["Ward 4"]["expected"] == 20 and zones["Ward 4"]["rate"] == 1.0

    for _ in range(6):
        phone.send(phone.wire("report", payload=report_at(*IN_RIVERSIDE)))
    for _ in range(4):
        phone.send(phone.wire("report", payload=report_at(*IN_OLD_MARKET)))
    zones = zones_by_name(client)
    ward = zones["Ward 4"]
    assert ward["rate"] == 0.4 and ward["expected"] == 8 and ward["actual"] == 0 and ward["silent"]
    assert ward["lines"][0] == "Expected about 8 reports, got 0"
    assert not zones["Riverside"]["silent"] and not zones["Old Market"]["silent"]
    snap = client.get("/api/snapshot").json()
    assert snap["summary"]["warnings"] == ["Silent Zone: Ward 4"] and schemas.errors("snapshot", snap) == []

    other = Phone(client, "dev_W4")
    other.send(other.wire("report", payload=report_at(*IN_WARD_4)), other.wire("report", payload=report_at(*IN_WARD_4)))
    ward = zones_by_name(client)["Ward 4"]
    assert ward["actual"] == 2 and not ward["silent"] and ward["silent_since"] is None   # 2 of 8 is a quarter
    with client.app.state.ctx.db.read() as conn:
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE target = 'zone:Ward 4' ORDER BY id")]
    assert actions == ["hard_hit", "silent", "not_silent"]


def test_clearing_the_mark_ends_hard_hit(client):
    load_zones(client)
    client.post("/api/zones/hard-hit", json={"zones": ["Ward 4"]})
    assert zones_by_name(client)["Ward 4"]["hard_hit_since"] is not None
    client.post("/api/zones/hard-hit", json={"zones": ["Ward 4"], "hard_hit": False})
    ward = zones_by_name(client)["Ward 4"]
    assert not ward["hard_hit"] and not ward["silent"] and ward["expected"] is None
    assert client.post("/api/zones/hard-hit", json={"zones": ["Nowhere"]}).status_code == 400


def test_heat_alert_zones_are_hard_hit(client):
    load_zones(client)
    add_alert(client, "A-0001", hazard="heat", zones=("Ward 4", "Old Market"))
    ctx = client.app.state.ctx
    ctx.zones.update()
    assert not any(z["hard_hit"] for z in zones_by_name(client).values())   # flood profile: marks only
    assert client.post("/api/settings/hazard", json={"hazard": "heat"}).json() == {"hazard": "heat"}
    zones = zones_by_name(client)
    assert zones["Ward 4"]["hard_hit"] and zones["Old Market"]["hard_hit"] and not zones["Riverside"]["hard_hit"]
    later = timeutil.now() + timedelta(hours=13)                             # the alert has run out
    ctx.zones.update(later)
    assert not any(z["hard_hit"] for z in zones_by_name(client).values())
    assert client.post("/api/settings/hazard", json={"hazard": "volcano"}).status_code == 400


def test_heat_zone_with_low_coverage_is_silent(client):
    load_zones(client)
    load_registry(client, registry_csv([(f"R-{i:04d}", "Ward 4", "elderly", None, None) for i in range(12)]))
    client.post("/api/settings/hazard", json={"hazard": "heat"})
    add_alert(client, "A-0002", hazard="heat", zones=("Ward 4",))
    client.app.state.ctx.zones.update()
    ward = zones_by_name(client)["Ward 4"]
    assert ward["unheard"] and ward["silent"] and ward["coverage"] == 0
    assert "Warning coverage: 0 of 12 registered vulnerable people confirmed (0%)" in ward["lines"]


def test_send_welfare_check_team_makes_one_zone_task(client, phone, schemas):
    load_zones(client)
    load_registry(client, registry_csv([(f"R-{i:04d}", "Ward 4", "alone", None, None) for i in range(12)]))
    client.post("/api/zones/hard-hit", json={"zones": ["Ward 4"]})
    card = client.get("/api/zones/Ward 4").json()
    assert schemas.errors("zone_card", card) == []
    assert card["task"]["case_id"] is None and card["task"]["points"] == 72

    detail = client.post("/api/zones/Ward 4/task", json={"by": "maria"}).json()
    case = detail["case"]
    assert schemas.errors("case_detail", detail) == []
    assert (case["source"], case["points"], case["confidence"], case["zone"]) == ("zone_task", 72, 1.0, "Ward 4")
    assert case["needs"] == ["welfare"] and case["hours_left"] is None and case["people"] == 12
    assert case["badges"] == ["zone task"] and case["status"] == "verified"
    assert client.post("/api/zones/Ward 4/task").json()["case"]["id"] == case["id"]      # one per zone
    assert zones_by_name(client)["Ward 4"]["task_case_id"] == case["id"]

    lat, lng = case["lat"], case["lng"]
    assert (lat, lng) == pytest.approx((0.0175, 0.0425))
    phone.send(phone.wire("report", payload=report_at(lat, lng)))           # a real report there stays apart
    cases = client.get("/api/snapshot").json()["cases"]
    assert len(cases) == 2 and cases[0]["id"] == case["id"]
    assert zones_by_name(client)["Ward 4"]["actual"] == 1                   # the task is not a report


def test_unknown_zone_is_404(client):
    load_zones(client)
    assert client.get("/api/zones/Nowhere").status_code == 404
    assert client.post("/api/zones/Nowhere/task").status_code == 404

"""PulseTriage command server: FastAPI app and routes.

Run from the repo root:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir server
"""
from __future__ import annotations

import io
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import qrcode
from fastapi import Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, outbound, timeutil
from .alerts import AlertBook
from .backups import Backups
from .cases import CaseBook, NotFound
from .config import Settings, load_constants
from .coverage import MAX_REGISTRY_BYTES, Coverage
from .crypto import CommandPostKeys
from .db import Database
from .demo import DemoReset
from .devices import DeviceBook
from .ingest import Ingestor
from .intake import Desk
from .net import lan_ipv4_addresses
from .profiles import Profiles
from .reader import KeywordReader
from .scheduler import Scheduler
from .schemas import Schemas
from .snapshot import SnapshotBuilder
from .suggest import Dispatch
from .supplies import SupplyBook
from .teams import TeamBook
from .zones import ZoneBook, ZoneMap

log = logging.getLogger("pulsetriage")


@dataclass
class Context:
    settings: Settings
    constants: dict
    schemas: Schemas
    profiles: Profiles
    db: Database
    keys: CommandPostKeys
    cases: CaseBook
    coverage: Coverage
    zones: ZoneBook
    alerts: AlertBook
    teams: TeamBook
    supplies: SupplyBook
    dispatch: Dispatch
    devices: DeviceBook
    backups: Backups
    demo: DemoReset
    desk: Desk
    ingestor: Ingestor
    snapshots: SnapshotBuilder
    scheduler: Scheduler


class UploadRequest(BaseModel):
    packets: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class ByRequest(BaseModel):
    by: str = Field("dispatcher", min_length=1, max_length=40)


class SplitRequest(ByRequest):
    report_id: str = Field(min_length=1, max_length=64)


class TrustRequest(ByRequest):
    trusted: bool = True


class HardHitRequest(ByRequest):
    zones: list[str] = Field(min_length=1, max_length=50)
    hard_hit: bool = True


class HazardRequest(ByRequest):
    hazard: str = Field(min_length=1, max_length=20)


class AlertRequest(ByRequest):
    """A new alert; with 'replaces' an update (fields left out are kept); with 'cancel' the all-clear."""
    hazard: str | None = None
    severity: Literal["watch", "warning", "emergency"] | None = None
    zones: list[str] | None = Field(None, min_length=1, max_length=50)
    headline: dict[str, str] | None = None
    do_now: dict[str, list[str]] | None = None
    places: list[str] | None = Field(None, description="Place IDs; leave out to pick the nearest with space")
    languages: list[str] | None = None
    fill: dict[str, str] = Field(default_factory=dict, description="Template values, e.g. start and end")
    valid_until: str | None = None
    replaces: str | None = None
    cancel: bool = False


class TeamRequest(ByRequest):
    id: str | None = Field(None, pattern=r"^[a-z0-9_]{1,40}$")
    name: str | None = Field(None, min_length=1, max_length=60)
    type: str | None = None
    capabilities: list[str] | None = Field(None, description="Replaces what the type and skills give")
    skills: list[str] | None = None
    device_id: str | None = Field(None, max_length=64)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    base: bool = Field(False, description="Also make (lat, lng) the team's base")
    fuel: Literal["full", "half", "low"] | None = None
    battery: int | None = Field(None, ge=0, le=100)
    speed_kmh: float | None = Field(None, gt=0, le=200)


class TeamStatusRequest(ByRequest):
    status: str = Field(min_length=1, max_length=20)
    reason: str | None = Field(None, max_length=200)


class AssignRequest(ByRequest):
    case_id: int
    team_id: str = Field(min_length=1, max_length=40)
    place: str | None = Field(None, description="Shelter or cooling centre to take people to")
    reassign: bool = False
    eta_min: float | None = Field(None, gt=0, le=1440, description="Needed when the case or team has no position")


class ShelterRequest(ByRequest):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    name: str | None = Field(None, min_length=1, max_length=60)
    type: Literal["shelter", "cooling_centre", "hospital", "other"] | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    capacity: int | None = Field(None, ge=0)
    occupancy: int | None = Field(None, ge=0)


class SupplyLevelRequest(ByRequest):
    item: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    warn_at: float | None = Field(None, ge=0)
    unit: str | None = Field(None, min_length=1, max_length=10)


class MoveRequest(ByRequest):
    kind: Literal["restock", "used", "load", "unload", "deliver", "transfer"]
    item: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    qty: float = Field(gt=0)
    from_place: str | None = Field(None, alias="from")
    to: str | None = None
    job_id: str | None = None


class RevokeRequest(ByRequest):
    revoked: bool = True
    reason: str = Field("revoked by the dispatcher", max_length=200)


class ResetRequest(ByRequest):
    pack: str = Field(min_length=1, max_length=40)


HAZARDS = Literal["flood", "heat", "earthquake", "storm", "fire", "landslide", "other"]


class IntakeRequest(ByRequest):
    """A call, radio message or walk-in, typed by a call-taker. Anything left out is read from the note."""
    hazard: HAZARDS | None = None
    for_whom: Literal["self", "neighbour", "other"] | None = None
    people: int | None = Field(None, ge=1, le=500)
    conditions: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(None, max_length=500)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    gps_accuracy_m: float | None = Field(None, ge=0)
    landmark: str | None = Field(None, max_length=200)
    contact: str | None = Field(None, max_length=40)
    registry_id: str | None = Field(None, max_length=40)


class PasteRequest(ByRequest):
    text: str = Field(min_length=1)
    hazard: HAZARDS | None = Field(None, description="Use this disaster when a message does not say")


class OverrideRequest(ByRequest):
    points: int | None = Field(None, ge=0, le=500, description="Leave out (with no status) to clear an override")
    status: Literal["new", "verified", "closed", "done"] | None = None
    reason: str = Field(min_length=1, max_length=200)


class WeightsRequest(ByRequest):
    weights: dict[str, float] = Field(default_factory=dict)
    reset: bool = Field(False, description="Back to the defaults in constants.json, then apply 'weights'")


class AnnouncementRequest(BaseModel):
    alert_id: str = Field(min_length=1, max_length=20)
    languages: list[str] | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.from_env()
    constants = load_constants(settings.shared_dir)
    schemas = Schemas(settings.shared_dir)
    profiles = Profiles(settings.shared_dir, schemas)
    db = Database(settings.db_path)
    keys = CommandPostKeys.load_or_create(settings.keys_dir)
    zone_map = ZoneMap.from_db(db)
    cases = CaseBook(db, profiles, constants, zone_map)
    coverage = Coverage(db, cases, zone_map, profiles, constants)
    zones = ZoneBook(db, zone_map, cases, coverage, profiles, schemas, constants)
    alerts = AlertBook(db, keys, schemas, profiles, zone_map, coverage, zones, cases, constants)
    supplies = SupplyBook(db, cases, constants)
    teams = TeamBook(db, cases, supplies, constants)
    dispatch = Dispatch(db, keys, schemas, profiles, cases, teams, supplies, constants)
    backups = Backups(db, settings.backups_dir, constants)
    ingestor = Ingestor(db, keys, schemas, profiles, settings, constants, cases, coverage, zones, teams)
    ctx = Context(settings, constants, schemas, profiles, db, keys, cases, coverage, zones, alerts, teams, supplies,
                  dispatch, DeviceBook(db, keys, schemas, cases, constants), backups,
                  DemoReset(db, backups, cases, zones, coverage, teams, supplies, profiles, settings),
                  Desk(db, ingestor, cases, coverage, KeywordReader(profiles)), ingestor,
                  SnapshotBuilder(db, settings, zones, alerts, teams, supplies),
                  Scheduler(cases, coverage, zones, alerts, teams, backups, constants))
    if not settings.require_signatures or not settings.require_sealing:
        log.warning("Development mode: unsigned=%s, unsealed=%s packets are accepted.",
                    not settings.require_signatures, not settings.require_sealing)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ctx.scheduler.start()        # tests that use TestClient without "with" skip this
        try:
            yield
        finally:
            ctx.scheduler.stop()

    app = FastAPI(title="PulseTriage command server", version=__version__, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # ---- health and setup --------------------------------------------------------------
    @app.get("/api/status")
    def status() -> dict:
        five_min_ago = timeutil.iso(timeutil.now() - timedelta(minutes=5))
        return {
            "ok": True,
            "version": __version__,
            "time": timeutil.iso(timeutil.now()),
            "hazard": db.get_setting("active_hazard", "flood"),
            "ai_online": False,
            "packets_last_5_min": db.scalar(
                "SELECT COUNT(*) FROM packets WHERE received_at >= ? AND result = 'accepted'", (five_min_ago,)),
            "require_signatures": settings.require_signatures,
            "require_sealing": settings.require_sealing,
            "scheduler_last_run": db.get_setting("scheduler_last_run"),
            "last_backup": backups.latest(),
        }

    def setup_payload(request: Request) -> dict:
        servers = [f"http://{ip}:{settings.port}" for ip in lan_ipv4_addresses()]
        if not servers:
            servers = [str(request.base_url).rstrip("/")]
        if settings.public_url:
            servers.append(settings.public_url.rstrip("/"))
        zones = [r["name"] for r in db.all("SELECT name FROM zones ORDER BY name")]
        return {"v": 1, "servers": servers, "sign_pk": keys.sign_pk, "box_pk": keys.box_pk,
                "time": timeutil.iso(timeutil.now()), "zones": zones}

    @app.get("/api/setup-qr")
    def setup_qr(request: Request) -> dict:
        return setup_payload(request)

    @app.get("/api/setup-qr.png")
    def setup_qr_png(request: Request) -> Response:
        img = qrcode.make(json.dumps(setup_payload(request), separators=(",", ":")))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.get("/api/profiles")
    def get_profiles() -> dict:
        return profiles.as_dict()

    # ---- phones ------------------------------------------------------------------------
    @app.post("/api/packets")
    def upload(req: UploadRequest) -> dict:
        out: dict[str, list] = {"accepted": [], "duplicate": [], "rejected": []}
        for wire in req.packets:
            result = ctx.ingestor.ingest_wire(wire)
            if result.status == "rejected":
                out["rejected"].append({"id": result.id, "reason": result.reason, "detail": result.detail})
            else:
                out[result.status].append(result.id)
        return out

    @app.get("/api/outbound")
    def get_outbound(since: int = Query(0, ge=0), device: str | None = None) -> dict:
        # 'device' will feed last-contact tracking in the team tracker step.
        return outbound.since(db, since)

    # ---- dashboard ---------------------------------------------------------------------
    @app.get("/api/snapshot")
    def snapshot() -> dict:
        return ctx.snapshots.get()

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: int) -> dict:
        return cases.detail(case_id)

    @app.post("/api/cases/{case_id}/verify")
    def verify_case(case_id: int, req: ByRequest | None = None) -> dict:
        return cases.verify(case_id, (req or ByRequest()).by)

    @app.post("/api/cases/{case_id}/split")
    def split_case(case_id: int, req: SplitRequest) -> dict:
        return cases.split(case_id, req.report_id, req.by)

    @app.get("/api/devices")
    def get_devices() -> dict:
        return {"devices": ctx.devices.views()}

    @app.post("/api/devices/{device_id}/revoke")
    def revoke_device(device_id: str, req: RevokeRequest | None = None) -> dict:
        req = req or RevokeRequest()
        return ctx.devices.revoke(device_id, req.revoked, req.reason, req.by)

    @app.get("/api/demo/packs")
    def demo_packs() -> dict:
        return {"packs": ctx.demo.packs()}

    @app.post("/api/demo/reset")
    def demo_reset(req: ResetRequest) -> dict:
        return ctx.demo.reset(req.pack, req.by)

    @app.post("/api/cases/{case_id}/override")
    def override_case(case_id: int, req: OverrideRequest) -> dict:
        return cases.override(case_id, req.points, req.status, req.reason, req.by)

    @app.post("/api/intake")
    def intake(req: IntakeRequest) -> dict:
        return ctx.desk.intake(req.model_dump(exclude={"by"}), req.by)

    @app.post("/api/paste")
    def paste(req: PasteRequest) -> dict:
        return ctx.desk.paste(req.text, req.hazard, req.by)

    @app.get("/api/settings/weights")
    def get_weights() -> dict:
        return cases.weights()

    @app.post("/api/settings/weights")
    def set_weights(req: WeightsRequest) -> dict:
        return cases.set_weights(req.weights, req.reset, req.by)

    @app.post("/api/devices/{device_id}/trust")
    def trust_device(device_id: str, req: TrustRequest | None = None) -> dict:
        req = req or TrustRequest()
        return {"device_id": device_id, "trusted": req.trusted,
                "cases_rescored": cases.set_trusted(device_id, req.trusted, req.by)}

    # ---- alerts -------------------------------------------------------------------------------
    @app.post("/api/alerts")
    def issue_alert(req: AlertRequest) -> dict:
        return alerts.issue(req.model_dump(exclude={"by"}), req.by)

    @app.post("/api/alerts/preview")
    def preview_alert(req: AlertRequest) -> dict:
        return alerts.preview(req.model_dump(exclude={"by"}))

    @app.get("/api/alerts")
    def list_alerts() -> dict:
        return {"alerts": alerts.views()}

    @app.get("/api/alerts/{alert_id}")
    def get_alert(alert_id: str) -> dict:
        return alerts.view(alert_id)

    @app.post("/api/announcement")
    def announcement(req: AnnouncementRequest) -> dict:
        return alerts.announcement(req.alert_id, req.languages)

    # ---- teams, suggestions and jobs ------------------------------------------------------------
    @app.get("/api/teams")
    def get_teams() -> dict:
        return {"teams": teams.views()}

    @app.post("/api/teams")
    def save_team(req: TeamRequest) -> dict:
        return teams.save(req.model_dump(exclude={"by"}), req.by)

    @app.post("/api/teams/{team_id}/status")
    def team_status(team_id: str, req: TeamStatusRequest) -> dict:
        return teams.set_status(team_id, req.status, req.reason, req.by)

    @app.get("/api/suggest")
    def suggest(case_id: int) -> dict:
        return dispatch.suggest(case_id)

    @app.get("/api/suggest/all")
    def suggest_all() -> dict:
        return dispatch.suggest_all()

    @app.post("/api/assign")
    def assign(req: AssignRequest) -> dict:
        return dispatch.assign(req.model_dump(exclude={"by"}), req.by)

    # ---- places and supplies ---------------------------------------------------------------------
    @app.get("/api/shelters")
    def get_shelters() -> dict:
        return {"shelters": supplies.shelters()}

    @app.post("/api/shelters")
    def save_shelter(req: ShelterRequest) -> dict:
        return supplies.save_shelter(req.model_dump(exclude={"by"}), req.by)

    @app.get("/api/supplies")
    def get_supplies() -> dict:
        return {"supplies": supplies.views()}

    @app.post("/api/supplies")
    def supply_level(req: SupplyLevelRequest) -> dict:
        return supplies.set_level(req.item, req.warn_at, req.unit, req.by)

    @app.post("/api/supplies/move")
    def supply_move(req: MoveRequest) -> dict:
        body = req.model_dump(exclude={"by", "from_place"})
        return supplies.move(dict(body, **{"from": req.from_place}), req.by)

    @app.get("/api/resources/summary")
    def resources_summary() -> dict:
        views = teams.views()
        counts, warnings = teams.summary(views)
        shelters = supplies.shelters()
        return {"teams": counts, "warnings": warnings + supplies.warnings(supplies.views(), shelters)}

    @app.post("/api/settings/hazard")
    def set_hazard(req: HazardRequest) -> dict:
        if req.hazard not in profiles.hazards:
            raise ValueError(f"no profile for {req.hazard!r}; known: {', '.join(profiles.hazards)}")
        with db.write() as conn:
            conn.execute("INSERT INTO settings(key, value) VALUES('active_hazard', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(req.hazard),))
            cases.audit(conn, timeutil.now(), req.by, "hazard", "settings", req.hazard)
        zones.update()
        return {"hazard": req.hazard}

    # ---- zones, registry and coverage --------------------------------------------------------
    @app.post("/api/zones/import")
    def import_zones(geojson: dict[str, Any] = Body(...), by: str = Query("dispatcher", max_length=40)) -> dict:
        return zones.import_geojson(geojson, by)

    @app.get("/api/zones")
    def get_zones() -> dict:
        zones.refresh_if_dirty()
        return {"zones": zones.views()}

    @app.post("/api/zones/hard-hit")
    def mark_hard_hit(req: HardHitRequest) -> dict:
        return {"zones": zones.set_hard_hit(req.zones, req.hard_hit, req.by)}

    @app.get("/api/zones/{name}")
    def zone_card(name: str) -> dict:
        return zones.card(name)

    @app.post("/api/zones/{name}/task")
    def zone_task(name: str, req: ByRequest | None = None) -> dict:
        return zones.create_task(name, (req or ByRequest()).by)

    @app.post("/api/registry/import")
    async def import_registry(request: Request, by: str = Query("dispatcher", max_length=40)) -> dict:
        raw = await request.body()
        if len(raw) > MAX_REGISTRY_BYTES:
            raise ValueError(f"registry file is over {MAX_REGISTRY_BYTES // 1_000_000} MB")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("registry file must be UTF-8 CSV") from exc
        result = coverage.import_registry(text, by)
        zones.update()
        return result

    @app.get("/api/coverage")
    def get_coverage() -> dict:
        return coverage.summary()

    @app.exception_handler(ValueError)
    def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"error": "invalid", "detail": str(exc)}, status_code=400)

    @app.exception_handler(NotFound)
    def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"error": "not_found", "detail": str(exc)}, status_code=404)

    if settings.dashboard_dir.exists():
        app.mount("/", StaticFiles(directory=settings.dashboard_dir, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def home() -> str:
            return ("<h1>PulseTriage command server</h1><p>The dashboard is not built yet "
                    "(<code>cd dashboard && npm run build</code>).</p>"
                    "<p><a href='/docs'>API docs</a> &middot; <a href='/api/status'>status</a> &middot; "
                    "<a href='/api/snapshot'>snapshot</a> &middot; <a href='/api/setup-qr.png'>setup QR</a></p>")

    return app


def __getattr__(name: str):
    """'app.main:app' builds the app on first use, so importing this module has no side effects."""
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)

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
from typing import Any

import qrcode
from fastapi import Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, outbound, timeutil
from .cases import CaseBook, NotFound
from .config import Settings, load_constants
from .coverage import MAX_REGISTRY_BYTES, Coverage
from .crypto import CommandPostKeys
from .db import Database
from .ingest import Ingestor
from .net import lan_ipv4_addresses
from .profiles import Profiles
from .scheduler import Scheduler
from .schemas import Schemas
from .snapshot import SnapshotBuilder
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
    ctx = Context(settings, constants, schemas, profiles, db, keys, cases, coverage, zones,
                  Ingestor(db, keys, schemas, profiles, settings, constants, cases, coverage, zones),
                  SnapshotBuilder(db, settings, zones), Scheduler(cases, coverage, zones, constants))
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

    @app.post("/api/devices/{device_id}/trust")
    def trust_device(device_id: str, req: TrustRequest | None = None) -> dict:
        req = req or TrustRequest()
        return {"device_id": device_id, "trusted": req.trusted,
                "cases_rescored": cases.set_trusted(device_id, req.trusted, req.by)}

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

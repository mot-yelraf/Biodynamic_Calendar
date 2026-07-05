from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tomllib
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from biodynamic_calendar import (
    BiodynamicConfig,
    get_astro_payload,
    get_biodynamic_calendar_range,
    get_daily_summary,
    get_biodynamic_payload,
)
from .config_store import ConfigStore, DetectedLocation, create_store


BASE_DIR = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger("uvicorn.error")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
store = create_store()


def _project_version() -> str:
    try:
        data = tomllib.loads((BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    project = data.get("project") if isinstance(data, dict) else {}
    version = project.get("version") if isinstance(project, dict) else ""
    if version:
        return str(version).strip()
    try:
        installed_version = metadata.version("biodynamic-calendar")
    except metadata.PackageNotFoundError:
        return ""
    return installed_version if installed_version.startswith("v") else f"v{installed_version}"


def _config_payload(config: BiodynamicConfig, location: DetectedLocation | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "latitude": float(config.latitude),
        "longitude": float(config.longitude),
        "timezone_name": str(config.timezone_name),
    }
    if location is not None:
        payload.update(
            {
                "source": location.source,
                "provider": location.provider,
                "error": location.error,
                "altitude": location.altitude,
            }
        )
    return payload


def _location_payload(location: DetectedLocation | None) -> dict[str, object]:
    if location is not None:
        return location.as_payload()
    return {
        "ok": False,
        "source": "none",
        "provider": "",
        "error": "location unavailable",
        "altitude": None,
        "latitude": None,
        "longitude": None,
        "timezone_name": "",
        "lat": None,
        "lon": None,
        "tz": "",
    }


def _sensorius_launch(request: Request) -> bool:
    params = request.query_params
    candidates = (
        params.get("source", ""),
        params.get("from", ""),
        params.get("embed", ""),
        params.get("launch", ""),
        params.get("sensorius", ""),
    )
    return any(str(value or "").strip().lower() in {"1", "true", "yes", "sensorius"} for value in candidates)


def _load_location() -> DetectedLocation | None:
    if hasattr(store, "load_location"):
        return store.load_location()
    config = store.load()
    return DetectedLocation(config=config, source="manual") if config is not None else None


def _load_plantings() -> list[dict[str, object]]:
    if hasattr(store, "load_plantings"):
        return store.load_plantings()
    return []


def _local_date(config: BiodynamicConfig):
    return datetime.now(ZoneInfo(config.timezone_name)).date()


def _config_task_key(config: BiodynamicConfig) -> str:
    return ":".join(
        (
            str(round(float(config.latitude), 4)),
            str(round(float(config.longitude), 4)),
            str(config.timezone_name),
        )
    )


def _cache_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _daily_summary_cache_key(
    summary_date,
    *,
    crop_stage: str,
    plantings: list[dict[str, object]],
) -> str:
    inputs = {
        "crop_stage": str(crop_stage or ""),
        "plantings": plantings,
    }
    return f"daily-summary:v1:{summary_date.isoformat()}:{_cache_digest(inputs)}"


def _cached_calendar_payload(
    cache_key: str,
    config: BiodynamicConfig,
    build_payload,
    refresh_cached: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    load_entry = getattr(store, "load_calendar_cache_entry", None)
    if callable(load_entry):
        try:
            cached = load_entry(config, cache_key)
        except Exception:
            cached = None
        if isinstance(cached, dict):
            if callable(refresh_cached):
                try:
                    return refresh_cached(cached)
                except Exception:
                    pass
            return cached

    payload = build_payload()
    if isinstance(payload, dict) and payload.get("ok"):
        save_entry = getattr(store, "save_calendar_cache_entry", None)
        if callable(save_entry):
            try:
                save_entry(config, cache_key, payload)
            except Exception:
                pass
    return payload


def _stable_calendar_range_cache_key(anchor, month_count: int) -> str:
    return f"calendar-range-stable:v1:{anchor.strftime('%Y-%m')}:{int(month_count)}"


def _refresh_cached_range_payload(payload: dict[str, object], config: BiodynamicConfig) -> dict[str, object]:
    refreshed = dict(payload)
    today_iso = _local_date(config).isoformat()
    refreshed_months: list[dict[str, object]] = []
    for month_payload in list(payload.get("months") or []):
        if not isinstance(month_payload, dict):
            continue
        month_copy = dict(month_payload)
        refreshed_rows: list[dict[str, object]] = []
        for row in list(month_payload.get("calendar") or []):
            if not isinstance(row, dict):
                continue
            row_copy = dict(row)
            row_copy["is_today"] = str(row_copy.get("date") or "") == today_iso
            refreshed_rows.append(row_copy)
        month_copy["calendar"] = refreshed_rows
        refreshed_months.append(month_copy)
    refreshed["months"] = refreshed_months
    refreshed["generated_at"] = datetime.now(timezone.utc).isoformat()
    return refreshed


async def _run_single_flight(
    task_key: str,
    tasks: dict[str, asyncio.Task],
    build_value: Callable[[], object],
) -> object:
    task = tasks.get(task_key)
    if task is None or task.done():
        task = asyncio.create_task(asyncio.to_thread(build_value))
        tasks[task_key] = task

        def _discard(done_task: asyncio.Task, *, key: str = task_key) -> None:
            if tasks.get(key) is done_task:
                tasks.pop(key, None)
            try:
                if not done_task.cancelled():
                    done_task.exception()
            except Exception:
                pass

        task.add_done_callback(_discard)
    return await task


async def _cached_calendar_payload_async(
    cache_key: str,
    config: BiodynamicConfig,
    build_payload: Callable[[], dict[str, object]],
    tasks: dict[str, asyncio.Task],
    refresh_cached: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    task_key = f"{_config_task_key(config)}:{cache_key}"
    payload = await _run_single_flight(
        task_key,
        tasks,
        lambda: _cached_calendar_payload(cache_key, config, build_payload, refresh_cached),
    )
    return dict(payload) if isinstance(payload, dict) else {}


def _valid_manual_config(body: dict[str, object]) -> tuple[BiodynamicConfig | None, str]:
    lat_raw = str(body.get("latitude") or "").strip()
    lon_raw = str(body.get("longitude") or "").strip()
    tz_name = str(body.get("timezone_name") or "").strip()
    if not lat_raw and not lon_raw:
        return None, "auto"
    if not lat_raw or not lon_raw:
        return None, "Latitude and longitude must both be filled, or both left blank."
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except Exception:
        return None, "Latitude and longitude must be numeric values."
    if not (-90.0 <= lat <= 90.0):
        return None, "Latitude must be between -90 and 90."
    if not (-180.0 <= lon <= 180.0):
        return None, "Longitude must be between -180 and 180."
    try:
        ZoneInfo(tz_name)
    except Exception:
        return None, "Timezone must be a valid IANA timezone."
    return BiodynamicConfig(latitude=lat, longitude=lon, timezone_name=tz_name), ""


async def _bootstrap_astral_location(
    *,
    attempts: int = 1,
    initial_delay_sec: float = 0.0,
    delay_sec: float = 30.0,
) -> DetectedLocation | None:
    if not hasattr(store, "bootstrap_auto_location"):
        return None
    if initial_delay_sec > 0:
        await asyncio.sleep(initial_delay_sec)
    last: DetectedLocation | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            last = await asyncio.to_thread(store.bootstrap_auto_location, timeout_sec=5.0)
            if last is not None and last.config is not None:
                return last
        except Exception as exc:
            last = DetectedLocation(config=None, source="none", error=str(exc))
        if attempt < attempts:
            await asyncio.sleep(delay_sec)
    return last


@asynccontextmanager
async def _lifespan(app: FastAPI):
    LOGGER.info("BD Calendar app version: %s", _project_version() or "unknown")
    detected = await _bootstrap_astral_location(attempts=1)
    if detected is None or detected.config is None:
        asyncio.create_task(_bootstrap_astral_location(attempts=6, initial_delay_sec=5.0, delay_sec=30.0))
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Biodynamic Calendar", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    calendar_payload_tasks: dict[str, asyncio.Task] = {}
    summary_tasks: dict[str, asyncio.Task] = {}

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz():
        return "ok"

    @app.get("/api/health", response_class=JSONResponse)
    async def api_health():
        return JSONResponse({"ok": True, "store": store.__class__.__name__})

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "config": store.load(),
                "notes": store.load_notes(),
                "plantings": _load_plantings(),
                "app_version": _project_version(),
                "sensorius_launch": _sensorius_launch(request),
            },
        )

    @app.get("/api/calendar", response_class=JSONResponse)
    async def api_calendar(month: str = ""):
        location = _load_location()
        config = location.config if location is not None else None
        if config is None:
            return JSONResponse(
                {
                    "ok": False,
                    "reason": "config_missing",
                    "calendar": [],
                    "notes": store.load_notes(),
                    "plantings": _load_plantings(),
                    "location": _location_payload(location),
                },
                status_code=200,
            )
        try:
            if month:
                anchor = datetime.strptime(month, "%Y-%m").date().replace(day=1)
            else:
                anchor = _local_date(config).replace(day=1)
        except Exception:
            return JSONResponse({"error": "invalid_month"}, status_code=400)
        cache_key = f"calendar:{anchor.strftime('%Y-%m')}:{_local_date(config).isoformat()}"
        payload = await _cached_calendar_payload_async(
            cache_key,
            config,
            lambda: {
                **get_biodynamic_payload(anchor, config=config),
                "astro": get_astro_payload(config=config),
            },
            calendar_payload_tasks,
        )
        payload["notes"] = store.load_notes()
        payload["plantings"] = _load_plantings()
        payload["location"] = _location_payload(location)
        return JSONResponse(payload)

    @app.get("/api/calendar-range", response_class=JSONResponse)
    async def api_calendar_range(start: str = "", months: int = 13):
        location = _load_location()
        config = location.config if location is not None else None
        if config is None:
            return JSONResponse(
                {
                    "ok": False,
                    "reason": "config_missing",
                    "months": [],
                    "notes": store.load_notes(),
                    "plantings": _load_plantings(),
                    "location": _location_payload(location),
                },
                status_code=200,
            )
        try:
            if start:
                anchor = datetime.strptime(start, "%Y-%m").date().replace(day=1)
            else:
                anchor = _local_date(config).replace(day=1)
            month_count = max(1, min(int(months or 13), 36))
        except Exception:
            return JSONResponse({"error": "invalid_range"}, status_code=400)
        cache_key = _stable_calendar_range_cache_key(anchor, month_count)
        payload = await _cached_calendar_payload_async(
            cache_key,
            config,
            lambda: get_biodynamic_calendar_range(anchor, months=month_count, config=config),
            calendar_payload_tasks,
            lambda cached: _refresh_cached_range_payload(cached, config),
        )
        payload["notes"] = store.load_notes()
        payload["plantings"] = _load_plantings()
        payload["location"] = _location_payload(location)
        return JSONResponse(payload)

    @app.get("/api/daily-summary", response_class=JSONResponse)
    async def api_daily_summary(day: str = "", crop_stage: str = ""):
        location = _load_location()
        config = location.config if location is not None else None
        if config is None:
            return JSONResponse({"ok": False, "reason": "config_missing", "summary": "", "location": _location_payload(location)}, status_code=200)
        try:
            summary_date = datetime.strptime(day, "%Y-%m-%d").date()
        except Exception:
            return JSONResponse({"error": "invalid_day"}, status_code=400)
        plantings = _load_plantings()
        cache_key = _daily_summary_cache_key(summary_date, crop_stage=crop_stage or "", plantings=plantings)
        payload = await _cached_calendar_payload_async(
            cache_key,
            config,
            lambda: {
                "ok": True,
                "date": summary_date.isoformat(),
                "summary": str(
                    get_daily_summary(
                        summary_date,
                        config=config,
                        crop_stage=crop_stage or None,
                        plantings=plantings,
                    )
                    or ""
                ),
            },
            summary_tasks,
        )
        return JSONResponse(
            {
                "ok": True,
                "date": summary_date.isoformat(),
                "summary": str(payload.get("summary") or ""),
            }
        )

    @app.post("/api/config", response_class=JSONResponse)
    async def api_config(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_config"}, status_code=400)
        config, error = _valid_manual_config(body)
        if error == "auto":
            detected = store.reset_location()
            if detected is None or detected.config is None:
                return JSONResponse(
                    {"ok": False, "reason": "location_detection_failed", "location": _location_payload(detected)},
                    status_code=503,
                )
            return JSONResponse({"ok": True, "config": _config_payload(detected.config, detected), "location": _location_payload(detected)})
        if config is None:
            return JSONResponse({"error": "invalid_config", "reason": error}, status_code=400)
        store.save(config, source="manual")
        location = DetectedLocation(config=config, source="manual")
        return JSONResponse({"ok": True, "config": _config_payload(config, location), "location": _location_payload(location)})

    @app.post("/api/config/reset", response_class=JSONResponse)
    async def api_config_reset():
        detected = store.reset_location()
        if detected is None or detected.config is None:
            return JSONResponse(
                {"ok": False, "reason": "location_detection_failed", "location": _location_payload(detected)},
                status_code=503,
            )
        return JSONResponse(
            {
                "ok": True,
                "source": detected.source,
                "provider": detected.provider,
                "error": detected.error,
                "config": _config_payload(detected.config, detected),
                "location": _location_payload(detected),
            }
        )

    @app.post("/api/note", response_class=JSONResponse)
    async def api_note(request: Request):
        body = await request.json()
        day_iso = str(body.get("date") or "").strip()
        if not day_iso:
            return JSONResponse({"error": "missing_date"}, status_code=400)
        store.save_note(day_iso, str(body.get("note") or ""))
        return JSONResponse({"ok": True})

    @app.get("/api/plantings", response_class=JSONResponse)
    async def api_plantings():
        return JSONResponse({"ok": True, "plantings": _load_plantings()})

    @app.post("/api/planting", response_class=JSONResponse)
    async def api_save_planting(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_planting"}, status_code=400)
        try:
            planting = store.save_planting(body)
        except ValueError as exc:
            return JSONResponse({"error": "invalid_planting", "reason": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "planting": planting, "plantings": _load_plantings()})

    @app.delete("/api/planting/{planting_id}", response_class=JSONResponse)
    async def api_delete_planting(planting_id: str):
        deleted = store.delete_planting(planting_id)
        return JSONResponse({"ok": True, "deleted": deleted, "plantings": _load_plantings()})

    return app


app = create_app()

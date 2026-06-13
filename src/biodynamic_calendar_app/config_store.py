from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import socket
import tomllib
from uuid import uuid4
from zoneinfo import ZoneInfo

from astral import geocoder

from biodynamic_calendar import BiodynamicConfig


IP_GEOLOCATION_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("ipapi.co", "https://ipapi.co/json/"),
    ("ip-api.com", "http://ip-api.com/json/"),
    ("ipwho.is", "https://ipwho.is/"),
)


@dataclass(frozen=True)
class DetectedLocation:
    config: BiodynamicConfig | None
    source: str
    provider: str = ""
    error: str = ""
    altitude: float | None = None

    @property
    def ok(self) -> bool:
        return self.config is not None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "source": self.source,
            "provider": self.provider,
            "error": self.error,
            "altitude": self.altitude,
        }
        if self.config is not None:
            payload.update(
                {
                    "latitude": float(self.config.latitude),
                    "longitude": float(self.config.longitude),
                    "timezone_name": str(self.config.timezone_name),
                    "lat": float(self.config.latitude),
                    "lon": float(self.config.longitude),
                    "tz": str(self.config.timezone_name),
                }
            )
        else:
            payload.update(
                {
                    "latitude": None,
                    "longitude": None,
                    "timezone_name": "",
                    "lat": None,
                    "lon": None,
                    "tz": "",
                }
            )
        return payload


def _valid_timezone_name(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ZoneInfo(text)
    except Exception:
        return None
    return text


def _safe_float(value: object) -> float | None:
    try:
        text = str(value).strip() if value is not None else ""
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _safe_int(value: object, *, minimum: int = 0, maximum: int = 10000) -> int | None:
    try:
        text = str(value).strip() if value is not None else ""
        if not text:
            return None
        out = int(float(text))
    except Exception:
        return None
    return out if minimum <= out <= maximum else None


def _short_text(value: object, *, limit: int = 200) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _valid_date_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except Exception:
        return ""


def _normalize_start_method(value: object) -> str:
    text = str(value or "").strip().lower()
    if "transplant" in text:
        return "transplant"
    if "seed" in text or "sow" in text:
        return "seed"
    return "seed"


def _normalize_plant_part(value: object) -> str:
    text = str(value or "").strip().lower()
    labels = {
        "root": "Root",
        "roots": "Root",
        "leaf": "Leaf",
        "leaves": "Leaf",
        "leafy": "Leaf",
        "flower": "Flower",
        "flowers": "Flower",
        "fruit": "Fruit",
        "fruits": "Fruit",
        "seed": "Fruit",
        "seeds": "Fruit",
    }
    if text in labels:
        return labels[text]
    for token, label in labels.items():
        if token in text:
            return label
    return ""


def _normalize_planting(raw: dict[str, object], *, fallback_id: str = "") -> tuple[dict[str, object] | None, str]:
    if not isinstance(raw, dict):
        return None, "Planting must be an object."

    name = _short_text(raw.get("name") or raw.get("plant") or raw.get("crop"), limit=80)
    if not name:
        return None, "Plant name is required."

    start_date = _valid_date_text(raw.get("start_date") or raw.get("started_on") or raw.get("date"))
    if not start_date:
        return None, "Start date is required."

    expected_harvest_date = _valid_date_text(raw.get("expected_harvest_date") or raw.get("harvest_date"))
    days_to_maturity = _safe_int(raw.get("days_to_maturity"), minimum=1, maximum=730)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    if not expected_harvest_date and days_to_maturity is not None:
        expected_harvest_date = (start_dt + timedelta(days=days_to_maturity)).isoformat()
    if expected_harvest_date:
        harvest_dt = datetime.strptime(expected_harvest_date, "%Y-%m-%d").date()
        if harvest_dt < start_dt:
            return None, "Expected harvest date must be on or after the start date."
        if days_to_maturity is None:
            days_to_maturity = max(1, (harvest_dt - start_dt).days)

    planting_id = _short_text(raw.get("id"), limit=80) or fallback_id or f"planting-{uuid4().hex[:12]}"
    harvest_window_days = _safe_int(raw.get("harvest_window_days"), minimum=0, maximum=90)

    return {
        "id": planting_id,
        "name": name,
        "variety": _short_text(raw.get("variety"), limit=80),
        "plant_type": _short_text(raw.get("plant_type") or raw.get("type"), limit=80),
        "plant_part": _normalize_plant_part(raw.get("plant_part") or raw.get("biodynamic_part") or raw.get("part")),
        "start_method": _normalize_start_method(raw.get("start_method") or raw.get("method")),
        "start_date": start_date,
        "expected_harvest_date": expected_harvest_date,
        "days_to_maturity": days_to_maturity,
        "harvest_window_days": 3 if harvest_window_days is None else harvest_window_days,
        "location": _short_text(raw.get("location") or raw.get("bed"), limit=100),
        "attributes": _short_text(raw.get("attributes"), limit=240),
        "notes": _short_text(raw.get("notes"), limit=240),
    }, ""


def _truthy_text(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return default
        return text in {"1", "true", "yes", "on"}
    return bool(value)


def _valid_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _valid_altitude(value: object) -> float | None:
    altitude = _safe_float(value)
    if altitude is None:
        return None
    return altitude if -500.0 <= altitude <= 10000.0 else None


def _raw_value(raw: dict[str, object], *keys: str, default: object = "") -> object:
    for key in keys:
        if key in raw:
            return raw[key]
    return default


def _raw_auto_ip(raw: dict[str, object]) -> bool:
    return _truthy_text(_raw_value(raw, "auto_ip", "AUTO_IP", default=True), default=True)


def _raw_source(raw: dict[str, object]) -> str:
    return str(_raw_value(raw, "location_source", "SOURCE", "source", default="") or "").strip().lower()


def _raw_provider(raw: dict[str, object]) -> str:
    return str(_raw_value(raw, "location_provider", "PROVIDER", "provider", default="") or "").strip()


def _raw_timezone(raw: dict[str, object], *, fallback: object = "") -> str | None:
    return _valid_timezone_name(
        _raw_value(raw, "timezone_name", "TIMEZONE", "timezone", default="")
    ) or _valid_timezone_name(
        _raw_value(raw, "primary_timezone", "TZ", default=fallback)
    ) or _valid_timezone_name(fallback) or _system_timezone_name() or "UTC"


def _config_from_values(lat_value: object, lon_value: object, tz_value: object) -> BiodynamicConfig | None:
    lat = _safe_float(lat_value)
    lon = _safe_float(lon_value)
    tz_name = _valid_timezone_name(tz_value)
    if not _valid_lat_lon(lat, lon) or tz_name is None:
        return None
    return BiodynamicConfig(latitude=float(lat), longitude=float(lon), timezone_name=tz_name)


def _system_timezone_name() -> str | None:
    tzinfo = datetime.now().astimezone().tzinfo
    direct_name = _valid_timezone_name(getattr(tzinfo, "key", None))
    if direct_name:
        return direct_name

    env_name = _valid_timezone_name(os.getenv("TZ", ""))
    if env_name:
        return env_name

    try:
        resolved = Path("/etc/localtime").resolve()
        parts = resolved.parts
        if "zoneinfo" in parts:
            idx = parts.index("zoneinfo")
            candidate = "/".join(parts[idx + 1 :])
            localtime_name = _valid_timezone_name(candidate)
            if localtime_name:
                return localtime_name
    except Exception:
        pass

    return None


def _extract_ip_geolocation(payload: dict[str, object] | None) -> tuple[float | None, float | None, str]:
    if not isinstance(payload, dict):
        return None, None, ""

    lat = _safe_float(payload.get("latitude"))
    lon = _safe_float(payload.get("longitude"))
    if lat is None:
        lat = _safe_float(payload.get("lat"))
    if lon is None:
        lon = _safe_float(payload.get("lon"))

    tz_raw = payload.get("timezone")
    if isinstance(tz_raw, dict):
        tz_name = str(tz_raw.get("id") or tz_raw.get("name") or "").strip()
    else:
        tz_name = str(tz_raw or "").strip()
    return lat, lon, tz_name


def probe_ip_geolocation_providers(timeout_sec: float = 2.5) -> list[dict[str, object]]:
    import httpx

    rows: list[dict[str, object]] = []
    with httpx.Client(timeout=timeout_sec) as client:
        for provider, url in IP_GEOLOCATION_PROVIDERS:
            row: dict[str, object] = {
                "provider": provider,
                "url": url,
                "status": "",
                "lat": None,
                "lon": None,
                "tz": "",
                "city": "",
                "region": "",
                "ip": "",
                "error": "",
            }
            try:
                resp = client.get(url)
                row["status"] = resp.status_code
                if resp.status_code != 200:
                    row["error"] = f"HTTP {resp.status_code}"
                    rows.append(row)
                    continue
                payload = resp.json() or {}
                if not isinstance(payload, dict):
                    row["error"] = "invalid JSON payload"
                    rows.append(row)
                    continue
                if payload.get("success") is False:
                    row["error"] = str(payload.get("message") or "unsuccessful response")
                    rows.append(row)
                    continue
                if str(payload.get("status") or "").strip().lower() == "fail":
                    row["error"] = str(payload.get("message") or "failed response")
                    rows.append(row)
                    continue
                lat, lon, tz_name = _extract_ip_geolocation(payload)
                row["lat"] = lat
                row["lon"] = lon
                row["tz"] = tz_name
                row["city"] = str(payload.get("city") or "").strip()
                row["region"] = str(payload.get("region") or payload.get("regionName") or "").strip()
                row["ip"] = str(payload.get("ip") or payload.get("query") or "").strip()
                if not _valid_lat_lon(lat, lon):
                    row["error"] = "invalid coordinates"
            except Exception as exc:
                row["error"] = f"{exc.__class__.__name__}: {exc}"
            rows.append(row)
    return rows


def _detect_location_from_ip(
    timeout_sec: float = 2.5,
    *,
    timezone_fallback: object = "",
) -> DetectedLocation:
    rows = probe_ip_geolocation_providers(timeout_sec=timeout_sec)
    errors: list[str] = []
    fallback_tz = _valid_timezone_name(timezone_fallback) or _system_timezone_name() or "UTC"
    for row in rows:
        provider = str(row.get("provider") or "").strip()
        if row.get("error"):
            errors.append(f"{provider}: {row.get('error')}")
            continue
        tz_name = _valid_timezone_name(row.get("tz")) or fallback_tz
        config = _config_from_values(row.get("lat"), row.get("lon"), tz_name)
        if config is not None:
            return DetectedLocation(config=config, source="ip", provider=provider)
        errors.append(f"{provider}: invalid coordinates or timezone")
    return DetectedLocation(config=None, source="none", error="; ".join(errors[-3:]))


def _resolve_location_from_raw(
    raw: dict[str, object],
    *,
    persist_if_auto: bool = False,
    timeout_sec: float = 2.5,
    allow_provider_lookup: bool = True,
    timezone_fallback: object = "",
) -> DetectedLocation:
    resolved_tz = _raw_timezone(raw, fallback=timezone_fallback)
    cfg_lat = _safe_float(_raw_value(raw, "latitude", "LATITUDE", default=""))
    cfg_lon = _safe_float(_raw_value(raw, "longitude", "LONGITUDE", default=""))
    cfg_source = _raw_source(raw)
    cfg_provider = _raw_provider(raw)
    cfg_altitude = _valid_altitude(_raw_value(raw, "altitude", "ALTITUDE", default=""))
    auto_ip = _raw_auto_ip(raw)

    use_saved_coordinates = (
        _valid_lat_lon(cfg_lat, cfg_lon)
        and (cfg_source != "ip" or not auto_ip or not persist_if_auto)
    )
    if use_saved_coordinates:
        config = _config_from_values(cfg_lat, cfg_lon, resolved_tz)
        if config is None:
            return DetectedLocation(config=None, source="none", error="saved location has an invalid timezone")
        source = "ip_cached" if cfg_source == "ip" else "manual"
        provider = cfg_provider if cfg_source == "ip" else ""
        return DetectedLocation(config=config, source=source, provider=provider, altitude=cfg_altitude)

    if not auto_ip:
        return DetectedLocation(config=None, source="none", error="Astral.AUTO_IP is disabled", altitude=cfg_altitude)

    if allow_provider_lookup:
        detected = _detect_location_from_ip(timeout_sec=timeout_sec, timezone_fallback=resolved_tz)
        if detected.config is not None:
            return DetectedLocation(
                config=detected.config,
                source="ip",
                provider=detected.provider,
                altitude=cfg_altitude,
            )
    else:
        detected = DetectedLocation(config=None, source="none", error="provider lookup skipped", altitude=cfg_altitude)

    if cfg_source == "ip" and _valid_lat_lon(cfg_lat, cfg_lon):
        config = _config_from_values(cfg_lat, cfg_lon, resolved_tz)
        if config is not None:
            return DetectedLocation(
                config=config,
                source="ip_cached",
                provider=cfg_provider,
                error=detected.error,
                altitude=cfg_altitude,
            )

    return DetectedLocation(config=None, source="none", error=detected.error, altitude=cfg_altitude)


def _sensorius_settings_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = str(os.getenv("SENSORIUS_SETTINGS_DIR", "") or "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    home = Path.home()
    roots.extend(
        [
            home / "Sensorius" / "system_settings",
            home / "Projects" / "saiSensorius" / "system_settings",
        ]
    )
    return list(dict.fromkeys(path.resolve() for path in roots if path.exists()))


def _host_setting_names() -> set[str]:
    try:
        host = socket.gethostname().strip()
    except Exception:
        host = ""
    names = {host, host.split(".", 1)[0] if host else ""}
    names.update(f"{name}.local" for name in list(names) if name)
    return {name.lower() for name in names if name}


def _sensorius_settings_sort_key(path: Path) -> tuple[int, float, str]:
    parent_name = path.parent.name.lower()
    host_names = _host_setting_names()
    host_rank = 0 if parent_name in host_names else 1
    try:
        mtime_rank = -path.stat().st_mtime
    except Exception:
        mtime_rank = 0.0
    return (host_rank, mtime_rank, str(path))


def _detect_location_from_sensorius_settings() -> DetectedLocation | None:
    candidates: list[Path] = []
    for root in _sensorius_settings_roots():
        candidates.extend(path for path in root.glob("*/settings.toml") if path.parent.name != "factory")
    for path in sorted(candidates, key=_sensorius_settings_sort_key):
        try:
            raw_toml = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        astral = raw_toml.get("Astral") if isinstance(raw_toml, dict) else {}
        time_cfg = raw_toml.get("Time") if isinstance(raw_toml, dict) else {}
        if not isinstance(astral, dict):
            continue
        if not isinstance(time_cfg, dict):
            time_cfg = {}
        raw = {
            "AUTO_IP": astral.get("AUTO_IP", True),
            "LATITUDE": astral.get("LATITUDE", ""),
            "LONGITUDE": astral.get("LONGITUDE", ""),
            "ALTITUDE": astral.get("ALTITUDE", ""),
            "TIMEZONE": astral.get("TIMEZONE") or time_cfg.get("TZ") or _system_timezone_name() or "",
            "SOURCE": astral.get("SOURCE", ""),
            "PROVIDER": astral.get("PROVIDER", ""),
        }
        detected = _resolve_location_from_raw(raw, allow_provider_lookup=False)
        if detected.config is not None:
            return detected
    return None


def _lookup_location_for_timezone(tz_name: str) -> BiodynamicConfig | None:
    db = geocoder.database()

    for loc in geocoder.all_locations(db):
        if getattr(loc, "timezone", None) == tz_name:
            return BiodynamicConfig(
                latitude=float(loc.latitude),
                longitude=float(loc.longitude),
                timezone_name=tz_name,
            )

    city_name = tz_name.rsplit("/", 1)[-1].replace("_", " ").strip()
    if not city_name:
        return None

    try:
        loc = geocoder.lookup(city_name, db)
    except Exception:
        return None

    return BiodynamicConfig(
        latitude=float(loc.latitude),
        longitude=float(loc.longitude),
        timezone_name=tz_name,
    )


def _detect_location_from_timezone() -> BiodynamicConfig | None:
    try:
        tz_name = _system_timezone_name()
        if not tz_name:
            return None
        return _lookup_location_for_timezone(tz_name)
    except Exception:
        return None


def _detect_location(timeout_sec: float = 2.5) -> DetectedLocation | None:
    detected = _detect_location_from_sensorius_settings()
    if detected is not None and detected.config is not None:
        return detected
    detected = _detect_location_from_ip(timeout_sec=timeout_sec)
    return detected if detected.config is not None else None


def _stored_source(source: str) -> str:
    value = str(source or "").strip().lower()
    if value in {"ip", "ip_cached"}:
        return "ip"
    if value == "none":
        return ""
    return "manual"


class ConfigStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or (Path.home() / ".biodynamic_calendar")).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.json"
        self.notes_path = self.root / "notes.json"
        self.plantings_path = self.root / "plantings.json"

    def _read_raw_config(self) -> dict[str, object] | None:
        if not self.config_path.exists():
            return None
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None

    def _write_raw_config(self, raw: dict[str, object]) -> None:
        self.config_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load_location(self) -> DetectedLocation | None:
        raw = self._read_raw_config()
        if raw is not None:
            detected = _resolve_location_from_raw(raw, persist_if_auto=False)
            return detected if detected.config is not None else None

        detected = _detect_location()
        if detected is not None and detected.config is not None:
            self.save_detected_location(detected)
            return detected
        return None

    def load(self) -> BiodynamicConfig | None:
        detected = self.load_location()
        return detected.config if detected is not None else None

    def resolve_location(
        self,
        *,
        persist_if_auto: bool = False,
        force_auto: bool = False,
        timeout_sec: float = 2.5,
    ) -> DetectedLocation:
        raw = self._read_raw_config() or {"auto_ip": True, "timezone_name": _system_timezone_name() or ""}
        if force_auto:
            raw = dict(raw)
            raw.update(
                {
                    "latitude": "",
                    "longitude": "",
                    "timezone_name": "",
                    "location_source": "",
                    "location_provider": "",
                    "location_error": "",
                    "auto_ip": True,
                }
            )
        detected = _resolve_location_from_raw(raw, persist_if_auto=persist_if_auto, timeout_sec=timeout_sec)
        if persist_if_auto and detected.config is not None and detected.source == "ip":
            self.save_detected_location(detected, auto_ip=_raw_auto_ip(raw))
        return detected

    def bootstrap_auto_location(self, *, timeout_sec: float = 5.0) -> DetectedLocation | None:
        detected = self.resolve_location(persist_if_auto=True, timeout_sec=timeout_sec)
        if detected.config is not None:
            return detected
        sensorius = _detect_location_from_sensorius_settings()
        if sensorius is not None and sensorius.config is not None:
            self.save_detected_location(sensorius)
            return sensorius
        return detected

    def save(
        self,
        config: BiodynamicConfig,
        *,
        source: str = "manual",
        provider: str = "",
        altitude: float | None = None,
        auto_ip: bool = True,
        error: str = "",
    ) -> None:
        payload = asdict(config)
        payload["latitude"] = round(float(config.latitude), 6)
        payload["longitude"] = round(float(config.longitude), 6)
        payload["timezone_name"] = str(config.timezone_name)
        payload["auto_ip"] = bool(auto_ip)
        payload["location_source"] = _stored_source(source)
        payload["location_provider"] = str(provider or "") if _stored_source(source) == "ip" else ""
        payload["location_error"] = str(error or "")
        if altitude is not None:
            payload["altitude"] = round(float(altitude), 2)
        self._write_raw_config(payload)

    def save_detected_location(self, detected: DetectedLocation, *, auto_ip: bool = True) -> None:
        if detected.config is not None:
            self.save(
                detected.config,
                source=detected.source,
                provider=detected.provider,
                altitude=detected.altitude,
                auto_ip=auto_ip,
                error=detected.error,
            )
            return
        self._write_raw_config(
            {
                "latitude": "",
                "longitude": "",
                "timezone_name": "",
                "auto_ip": bool(auto_ip),
                "altitude": "",
                "location_source": "",
                "location_provider": "",
                "location_error": detected.error,
            }
        )

    def reset_location(self, *, timeout_sec: float = 3.5) -> DetectedLocation:
        detected = self.resolve_location(persist_if_auto=True, force_auto=True, timeout_sec=timeout_sec)
        if detected.config is None:
            sensorius = _detect_location_from_sensorius_settings()
            if sensorius is not None and sensorius.config is not None:
                self.save_detected_location(sensorius)
                return sensorius
            self.save_detected_location(detected)
            return detected
        self.save_detected_location(detected)
        return detected

    def load_notes(self) -> dict[str, str]:
        if not self.notes_path.exists():
            return {}
        try:
            raw = json.loads(self.notes_path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in raw.items()}
        except Exception:
            return {}

    def save_note(self, day_iso: str, note: str) -> None:
        notes = self.load_notes()
        text = str(note or "").strip()
        if text:
            notes[day_iso] = text
        else:
            notes.pop(day_iso, None)
        self.notes_path.write_text(json.dumps(notes, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load_plantings(self) -> list[dict[str, object]]:
        if not self.plantings_path.exists():
            return []
        try:
            raw = json.loads(self.plantings_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = raw.get("plantings") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return []
        plantings: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            normalized, _error = _normalize_planting(row, fallback_id=f"planting-{idx + 1}")
            if normalized is None:
                continue
            planting_id = str(normalized["id"])
            if planting_id in seen_ids:
                normalized["id"] = f"{planting_id}-{idx + 1}"
            seen_ids.add(str(normalized["id"]))
            plantings.append(normalized)
        return sorted(plantings, key=lambda item: (str(item.get("start_date") or ""), str(item.get("name") or "")))

    def _write_plantings(self, plantings: list[dict[str, object]]) -> None:
        self.plantings_path.write_text(json.dumps(plantings, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def save_planting(self, raw: dict[str, object]) -> dict[str, object]:
        normalized, error = _normalize_planting(raw)
        if normalized is None:
            raise ValueError(error or "Invalid planting.")
        planting_id = str(normalized["id"])
        plantings = [row for row in self.load_plantings() if str(row.get("id") or "") != planting_id]
        plantings.append(normalized)
        plantings = sorted(plantings, key=lambda item: (str(item.get("start_date") or ""), str(item.get("name") or "")))
        self._write_plantings(plantings)
        return normalized

    def delete_planting(self, planting_id: str) -> bool:
        target = str(planting_id or "").strip()
        if not target:
            return False
        plantings = self.load_plantings()
        remaining = [row for row in plantings if str(row.get("id") or "") != target]
        if len(remaining) == len(plantings):
            return False
        self._write_plantings(remaining)
        return True

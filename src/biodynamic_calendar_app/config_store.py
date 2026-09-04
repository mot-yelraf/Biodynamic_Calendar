from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import tomllib
from typing import Protocol
from zoneinfo import ZoneInfo

from astral import geocoder

from biodynamic_calendar import BiodynamicConfig
from biodynamic_calendar.core import CALCULATION_IMPLEMENTATION_VERSION
from .theme_manager import is_custom_theme_selection
from .storage_validation import (
    MAX_NOTE_LENGTH,
    _normalize_note,
    _normalize_planting,
    _safe_float,
    _truthy_text,
    _valid_altitude,
    _valid_date_text,
    _valid_lat_lon,
)


IP_GEOLOCATION_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("ipapi.co", "https://ipapi.co/json/"),
    ("ip-api.com", "http://ip-api.com/json/"),
    ("ipwho.is", "https://ipwho.is/"),
)
_STORE_LOCKS_GUARD = threading.Lock()
_STORE_LOCKS: dict[Path, threading.RLock] = {}
APPEARANCE_THEMES = frozenset({"auto", "spring", "summer", "autumn", "winter"})
LOGGER = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Base exception for unavailable or failed persistent storage."""


class StorageReadError(StorageError):
    """Persistent state could not be read safely."""


class StorageWriteError(StorageError):
    """A requested persistent mutation could not be completed."""


def _normalize_appearance_theme(value: object) -> str:
    theme = str(value or "").strip().lower()
    return theme if theme in APPEARANCE_THEMES or is_custom_theme_selection(theme) else "auto"


def _store_lock(root: Path) -> threading.RLock:
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(root, threading.RLock())


def _write_json_atomic(path: Path, payload: object) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


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


class CalendarStore(Protocol):
    root: Path

    def load(self) -> BiodynamicConfig | None: ...
    def load_location(self) -> DetectedLocation | None: ...
    def save(self, config: BiodynamicConfig, **kwargs: object) -> None: ...
    def reset_location(self, *, timeout_sec: float = 3.5) -> DetectedLocation: ...
    def load_notes(self) -> dict[str, str]: ...
    def save_note(self, day_iso: str, note: str) -> None: ...
    def load_plantings(self) -> list[dict[str, object]]: ...
    def save_planting(self, raw: dict[str, object]) -> dict[str, object]: ...
    def delete_planting(self, planting_id: str) -> bool: ...


def _valid_timezone_name(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ZoneInfo(text)
    except Exception:
        return None
    return text


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


_CALENDAR_CACHE_VERSION = 2
_MAX_CALENDAR_CACHE_ENTRIES = 120


def _calendar_cache_location(config: BiodynamicConfig) -> dict[str, object]:
    return {
        "lat": round(float(config.latitude), 6),
        "lon": round(float(config.longitude), 6),
        "tz": str(config.timezone_name),
    }


def _raw_calendar_cache_location(raw: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    config = _config_from_values(
        _raw_value(raw, "latitude", "LATITUDE", default=""),
        _raw_value(raw, "longitude", "LONGITUDE", default=""),
        _raw_timezone(raw),
    )
    return _calendar_cache_location(config) if config is not None else None


def _trim_calendar_cache_entries(entries: dict[str, object]) -> dict[str, object]:
    valid_entries = {str(key): value for key, value in entries.items() if isinstance(value, dict)}
    if len(valid_entries) <= _MAX_CALENDAR_CACHE_ENTRIES:
        return valid_entries
    ordered = sorted(
        valid_entries.items(),
        key=lambda item: str(item[1].get("created_at") or ""),
        reverse=True,
    )
    return dict(ordered[:_MAX_CALENDAR_CACHE_ENTRIES])


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _calendar_cache_location_key(config: BiodynamicConfig) -> str:
    return json.dumps(_calendar_cache_location(config), sort_keys=True, separators=(",", ":"))


def _versioned_cache_key(cache_key: str) -> str:
    return f"calculation-v{CALCULATION_IMPLEMENTATION_VERSION}:{cache_key}"


def _sensorius_db_env_path() -> Path | None:
    for name in ("SENSORIUS_DB_PATH", "BD_CALENDAR_SENSORIUS_DB_PATH", "BIODYNAMIC_CALENDAR_SENSORIUS_DB_PATH"):
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return Path(value).expanduser()
    return None


def _sensorius_db_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = _sensorius_db_env_path()
    if env_path is not None:
        candidates.append(env_path)
    home = Path.home()
    candidates.extend(
        [
            home / "Sensorius" / "sensorius_data.db",
            home / "Projects" / "saiSensorius" / "sensorius_data.db",
        ]
    )
    return list(dict.fromkeys(path for path in candidates))


def _resolve_sensorius_db_path(*, create_if_missing: bool = False) -> Path | None:
    candidates = _sensorius_db_candidates()
    for path in candidates:
        try:
            resolved = path.expanduser()
        except Exception:
            continue
        if resolved.exists():
            return resolved
    if create_if_missing and candidates:
        return candidates[0].expanduser()
    return None


class ConfigStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or (Path.home() / ".biodynamic_calendar")).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._store_lock = _store_lock(self.root)
        self.config_path = self.root / "config.json"
        self.notes_path = self.root / "notes.json"
        self.plantings_path = self.root / "plantings.json"
        self.calendar_cache_path = self.root / "calendar_cache.json"

    def _read_raw_config(self) -> dict[str, object] | None:
        if not self.config_path.exists():
            return None
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.exception("Could not read config from %s", self.config_path)
            raise StorageReadError("Could not read calendar configuration.") from exc
        if not isinstance(raw, dict):
            LOGGER.error("Calendar configuration at %s is not a JSON object", self.config_path)
            raise StorageReadError("Calendar configuration has an invalid format.")
        return raw

    def _write_raw_config(self, raw: dict[str, object]) -> None:
        try:
            _write_json_atomic(self.config_path, raw)
        except Exception as exc:
            LOGGER.exception("Could not write config to %s", self.config_path)
            raise StorageWriteError("Could not save calendar configuration.") from exc

    def load_appearance_theme(self) -> str:
        raw = self._read_raw_config() or {}
        return _normalize_appearance_theme(raw.get("appearance_theme"))

    def save_appearance_theme(self, theme: object) -> str:
        normalized = _normalize_appearance_theme(theme)
        with self._store_lock:
            raw = dict(self._read_raw_config() or {})
            raw["appearance_theme"] = normalized
            self._write_raw_config(raw)
        return normalized

    def _read_calendar_cache(self) -> dict[str, object] | None:
        if not self.calendar_cache_path.exists():
            return None
        try:
            raw = json.loads(self.calendar_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if (
            not isinstance(raw, dict)
            or raw.get("version") != _CALENDAR_CACHE_VERSION
            or raw.get("calculation_version") != CALCULATION_IMPLEMENTATION_VERSION
        ):
            return None
        entries = raw.get("entries")
        return raw if isinstance(entries, dict) else None

    def _write_calendar_cache(self, raw: dict[str, object]) -> None:
        _write_json_atomic(self.calendar_cache_path, raw)

    def clear_calendar_cache(self) -> None:
        with self._store_lock:
            try:
                self.calendar_cache_path.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:
                LOGGER.exception("Could not clear calendar cache at %s", self.calendar_cache_path)
                raise StorageWriteError("Could not clear calendar cache.") from exc

    def load_calendar_cache_entry(self, config: BiodynamicConfig, cache_key: str) -> dict[str, object] | None:
        raw = self._read_calendar_cache()
        if raw is None or raw.get("location") != _calendar_cache_location(config):
            return None
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            return None
        entry = entries.get(str(cache_key))
        if not isinstance(entry, dict):
            return None
        payload = entry.get("payload")
        return dict(payload) if isinstance(payload, dict) else None

    def save_calendar_cache_entry(self, config: BiodynamicConfig, cache_key: str, payload: dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return
        with self._store_lock:
            location = _calendar_cache_location(config)
            raw = self._read_calendar_cache()
            entries = raw.get("entries") if raw is not None and raw.get("location") == location else {}
            if not isinstance(entries, dict):
                entries = {}
            entries = dict(entries)
            entries[str(cache_key)] = {
                "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "payload": dict(payload),
            }
            try:
                self._write_calendar_cache(
                    {
                        "version": _CALENDAR_CACHE_VERSION,
                        "calculation_version": CALCULATION_IMPLEMENTATION_VERSION,
                        "location": location,
                        "entries": _trim_calendar_cache_entries(entries),
                    }
                )
            except Exception as exc:
                LOGGER.exception("Could not write calendar cache at %s", self.calendar_cache_path)
                raise StorageWriteError("Could not save calendar cache.") from exc

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
        with self._store_lock:
            previous_raw = self._read_raw_config() or {}
            previous_location = _raw_calendar_cache_location(previous_raw)
            current_location = _calendar_cache_location(config)
            payload = asdict(config)
            payload["latitude"] = round(float(config.latitude), 6)
            payload["longitude"] = round(float(config.longitude), 6)
            payload["timezone_name"] = str(config.timezone_name)
            payload["auto_ip"] = bool(auto_ip)
            payload["location_source"] = _stored_source(source)
            payload["location_provider"] = str(provider or "") if _stored_source(source) == "ip" else ""
            payload["location_error"] = str(error or "")
            payload["appearance_theme"] = _normalize_appearance_theme(previous_raw.get("appearance_theme"))
            if altitude is not None:
                payload["altitude"] = round(float(altitude), 2)
            self._write_raw_config(payload)
            if previous_location != current_location:
                try:
                    self.clear_calendar_cache()
                except StorageError:
                    LOGGER.warning("Configuration saved, but the calendar cache could not be cleared")

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
        previous_location = _raw_calendar_cache_location(self._read_raw_config())
        previous_raw = self._read_raw_config() or {}
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
                "appearance_theme": _normalize_appearance_theme(previous_raw.get("appearance_theme")),
            }
        )
        if previous_location is not None:
            try:
                self.clear_calendar_cache()
            except StorageError:
                LOGGER.warning("Location reset saved, but the calendar cache could not be cleared")

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
        except Exception as exc:
            LOGGER.exception("Could not read notes from %s", self.notes_path)
            raise StorageReadError("Could not read saved notes.") from exc

    def save_note(self, day_iso: str, note: str) -> None:
        clean_date, clean_text = _normalize_note(day_iso, note)
        with self._store_lock:
            notes = self.load_notes()
            if clean_text:
                notes[clean_date] = clean_text
            else:
                notes.pop(clean_date, None)
            try:
                _write_json_atomic(self.notes_path, notes)
            except Exception as exc:
                LOGGER.exception("Could not write notes to %s", self.notes_path)
                raise StorageWriteError("Could not save note.") from exc

    def load_plantings(self) -> list[dict[str, object]]:
        if not self.plantings_path.exists():
            return []
        try:
            raw = json.loads(self.plantings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.exception("Could not read plantings from %s", self.plantings_path)
            raise StorageReadError("Could not read saved plantings.") from exc
        rows = raw.get("plantings") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            LOGGER.error("Planting data at %s is not a JSON list", self.plantings_path)
            raise StorageReadError("Saved planting data has an invalid format.")
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
        try:
            _write_json_atomic(self.plantings_path, plantings)
        except Exception as exc:
            LOGGER.exception("Could not write plantings to %s", self.plantings_path)
            raise StorageWriteError("Could not save planting data.") from exc

    def save_planting(self, raw: dict[str, object]) -> dict[str, object]:
        normalized, error = _normalize_planting(raw)
        if normalized is None:
            raise ValueError(error or "Invalid planting.")
        with self._store_lock:
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
        with self._store_lock:
            plantings = self.load_plantings()
            remaining = [row for row in plantings if str(row.get("id") or "") != target]
            if len(remaining) == len(plantings):
                return False
            self._write_plantings(remaining)
            return True


class SensoriusSQLiteStore(ConfigStore):
    def __init__(self, db_path: Path | str, root: Path | None = None, *, import_local_json: bool = True):
        super().__init__(root=root)
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if import_local_json:
            self._import_local_json_state()

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _init_db(self) -> None:
        with self._open_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS biodynamic_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_date   TEXT NOT NULL UNIQUE,
                    note_text   TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_biodynamic_notes_date
                ON biodynamic_notes(note_date DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS biodynamic_daily_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_date TEXT NOT NULL UNIQUE,
                    summary_text TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_biodynamic_daily_summaries_date
                ON biodynamic_daily_summaries(summary_date DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS biodynamic_plantings (
                    planting_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    variety TEXT,
                    plant_type TEXT,
                    plant_part TEXT,
                    start_method TEXT,
                    start_date TEXT NOT NULL,
                    expected_harvest_date TEXT,
                    days_to_maturity INTEGER,
                    harvest_window_days INTEGER,
                    location TEXT,
                    attributes TEXT,
                    notes TEXT,
                    planting_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_biodynamic_plantings_dates
                ON biodynamic_plantings(start_date, expected_harvest_date)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS biodynamic_calendar_cache (
                    cache_key TEXT PRIMARY KEY,
                    location_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_biodynamic_calendar_cache_created
                ON biodynamic_calendar_cache(created_at DESC)
                """
            )
            conn.commit()

    def _import_local_json_state(self) -> None:
        try:
            with self._open_conn() as conn:
                note_count = int(conn.execute("SELECT COUNT(*) FROM biodynamic_notes").fetchone()[0] or 0)
                planting_count = int(conn.execute("SELECT COUNT(*) FROM biodynamic_plantings").fetchone()[0] or 0)
        except Exception:
            return
        if note_count == 0:
            for day_iso, note in ConfigStore.load_notes(self).items():
                self.save_note(day_iso, note)
        if planting_count == 0:
            for planting in ConfigStore.load_plantings(self):
                try:
                    self.save_planting(planting)
                except ValueError:
                    continue

    def load_location(self) -> DetectedLocation | None:
        sensorius = _detect_location_from_sensorius_settings()
        if sensorius is not None and sensorius.config is not None:
            return sensorius
        return super().load_location()

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
        super().save(
            config,
            source=source,
            provider=provider,
            altitude=altitude,
            auto_ip=auto_ip,
            error=error,
        )

    def load_notes(self) -> dict[str, str]:
        try:
            with self._open_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT note_date, note_text
                    FROM biodynamic_notes
                    ORDER BY note_date ASC
                    """
                ).fetchall()
            return {str(row["note_date"]): str(row["note_text"] or "") for row in rows if row["note_date"]}
        except Exception as exc:
            LOGGER.exception("Could not read notes from SQLite database %s", self.db_path)
            raise StorageReadError("Could not read saved notes.") from exc

    def save_note(self, day_iso: str, note: str) -> None:
        clean_date, clean_text = _normalize_note(day_iso, note)
        now = _utc_timestamp()
        try:
            with self._open_conn() as conn:
                if clean_text:
                    conn.execute(
                        """
                        INSERT INTO biodynamic_notes(note_date, note_text, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(note_date) DO UPDATE SET
                            note_text=excluded.note_text,
                            updated_at=excluded.updated_at
                        """,
                        (clean_date, clean_text, now, now),
                    )
                else:
                    conn.execute("DELETE FROM biodynamic_notes WHERE note_date = ?", (clean_date,))
                conn.commit()
        except Exception as exc:
            LOGGER.exception("Could not save note to SQLite database %s", self.db_path)
            raise StorageWriteError("Could not save note.") from exc

    def load_plantings(self) -> list[dict[str, object]]:
        try:
            with self._open_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT planting_id, planting_json
                    FROM biodynamic_plantings
                    ORDER BY start_date ASC, name ASC
                    """
                ).fetchall()
        except Exception as exc:
            LOGGER.exception("Could not read plantings from SQLite database %s", self.db_path)
            raise StorageReadError("Could not read saved plantings.") from exc

        plantings: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for idx, row in enumerate(rows):
            raw: dict[str, object] | None = None
            try:
                parsed = json.loads(str(row["planting_json"] or "{}"))
                raw = parsed if isinstance(parsed, dict) else None
            except Exception:
                raw = None
            if raw is None:
                raw = {"id": row["planting_id"], "name": "", "start_date": ""}
            normalized, _error = _normalize_planting(raw, fallback_id=f"planting-{idx + 1}")
            if normalized is None:
                continue
            planting_id = str(normalized["id"])
            if planting_id in seen_ids:
                normalized["id"] = f"{planting_id}-{idx + 1}"
            seen_ids.add(str(normalized["id"]))
            plantings.append(normalized)
        return sorted(plantings, key=lambda item: (str(item.get("start_date") or ""), str(item.get("name") or "")))

    def save_planting(self, raw: dict[str, object]) -> dict[str, object]:
        normalized, error = _normalize_planting(raw)
        if normalized is None:
            raise ValueError(error or "Invalid planting.")
        now = _utc_timestamp()
        try:
            with self._open_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO biodynamic_plantings(
                        planting_id, name, variety, plant_type, plant_part, start_method,
                        start_date, expected_harvest_date, days_to_maturity, harvest_window_days,
                        location, attributes, notes, planting_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(planting_id) DO UPDATE SET
                        name=excluded.name,
                        variety=excluded.variety,
                        plant_type=excluded.plant_type,
                        plant_part=excluded.plant_part,
                        start_method=excluded.start_method,
                        start_date=excluded.start_date,
                        expected_harvest_date=excluded.expected_harvest_date,
                        days_to_maturity=excluded.days_to_maturity,
                        harvest_window_days=excluded.harvest_window_days,
                        location=excluded.location,
                        attributes=excluded.attributes,
                        notes=excluded.notes,
                        planting_json=excluded.planting_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(normalized["id"]),
                        str(normalized["name"]),
                        str(normalized.get("variety") or ""),
                        str(normalized.get("plant_type") or ""),
                        str(normalized.get("plant_part") or ""),
                        str(normalized.get("start_method") or ""),
                        str(normalized.get("start_date") or ""),
                        str(normalized.get("expected_harvest_date") or ""),
                        normalized.get("days_to_maturity"),
                        normalized.get("harvest_window_days"),
                        str(normalized.get("location") or ""),
                        str(normalized.get("attributes") or ""),
                        str(normalized.get("notes") or ""),
                        json.dumps(normalized, sort_keys=True),
                        now,
                        now,
                    ),
                )
                conn.commit()
        except Exception as exc:
            LOGGER.exception("Could not save planting to SQLite database %s", self.db_path)
            raise StorageWriteError("Could not save planting.") from exc
        return normalized

    def delete_planting(self, planting_id: str) -> bool:
        target = str(planting_id or "").strip()
        if not target:
            return False
        try:
            with self._open_conn() as conn:
                cur = conn.execute("DELETE FROM biodynamic_plantings WHERE planting_id = ?", (target,))
                conn.commit()
                return int(cur.rowcount or 0) > 0
        except Exception as exc:
            LOGGER.exception("Could not delete planting from SQLite database %s", self.db_path)
            raise StorageWriteError("Could not delete planting.") from exc

    def load_calendar_cache_entry(self, config: BiodynamicConfig, cache_key: str) -> dict[str, object] | None:
        try:
            with self._open_conn() as conn:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM biodynamic_calendar_cache
                    WHERE cache_key = ? AND location_key = ?
                    LIMIT 1
                    """,
                    (_versioned_cache_key(cache_key), _calendar_cache_location_key(config)),
                ).fetchone()
            if not row:
                return None
            payload = json.loads(str(row["payload_json"] or "{}"))
            return dict(payload) if isinstance(payload, dict) else None
        except Exception:
            LOGGER.warning("Could not read SQLite calendar cache", exc_info=True)
            return None

    def save_calendar_cache_entry(self, config: BiodynamicConfig, cache_key: str, payload: dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return
        now = _utc_timestamp()
        try:
            with self._open_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO biodynamic_calendar_cache(cache_key, location_key, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        location_key=excluded.location_key,
                        payload_json=excluded.payload_json,
                        created_at=excluded.created_at
                    """,
                    (
                        _versioned_cache_key(cache_key),
                        _calendar_cache_location_key(config),
                        json.dumps(payload, sort_keys=True),
                        now,
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM biodynamic_calendar_cache
                    WHERE cache_key NOT IN (
                        SELECT cache_key
                        FROM biodynamic_calendar_cache
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    """,
                    (_MAX_CALENDAR_CACHE_ENTRIES,),
                )
                conn.commit()
        except Exception as exc:
            LOGGER.exception("Could not write SQLite calendar cache")
            raise StorageWriteError("Could not save calendar cache.") from exc

    def clear_calendar_cache(self) -> None:
        try:
            with self._open_conn() as conn:
                conn.execute("DELETE FROM biodynamic_calendar_cache")
                conn.commit()
        except Exception as exc:
            LOGGER.exception("Could not clear SQLite calendar cache")
            raise StorageWriteError("Could not clear calendar cache.") from exc

    def load_daily_summary(self, day_iso: str) -> str:
        clean_date = _valid_date_text(day_iso)
        if not clean_date:
            return ""
        try:
            with self._open_conn() as conn:
                row = conn.execute(
                    """
                    SELECT summary_text
                    FROM biodynamic_daily_summaries
                    WHERE summary_date = ?
                    LIMIT 1
                    """,
                    (clean_date,),
                ).fetchone()
            return str(row["summary_text"] or "") if row else ""
        except Exception:
            LOGGER.warning("Could not read SQLite daily-summary cache", exc_info=True)
            return ""

    def save_daily_summary(self, day_iso: str, summary: str) -> None:
        clean_date = _valid_date_text(day_iso)
        clean_text = str(summary or "").strip()
        if not clean_date:
            return
        now = _utc_timestamp()
        try:
            with self._open_conn() as conn:
                if clean_text:
                    conn.execute(
                        """
                        INSERT INTO biodynamic_daily_summaries(summary_date, summary_text, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(summary_date) DO UPDATE SET
                            summary_text=excluded.summary_text,
                            updated_at=excluded.updated_at
                        """,
                        (clean_date, clean_text, now, now),
                    )
                else:
                    conn.execute("DELETE FROM biodynamic_daily_summaries WHERE summary_date = ?", (clean_date,))
                conn.commit()
        except Exception as exc:
            LOGGER.exception("Could not write SQLite daily-summary cache")
            raise StorageWriteError("Could not save daily summary.") from exc


def create_store() -> ConfigStore:
    mode = str(os.getenv("BD_CALENDAR_STORE", os.getenv("BIODYNAMIC_CALENDAR_STORE", "")) or "").strip().lower()
    if mode in {"json", "local", "file", "files"}:
        return ConfigStore()

    env_path = _sensorius_db_env_path()
    explicit_sensorius = mode in {"sensorius", "sensorius_sqlite", "sqlite"}
    auto_sensorius = mode == "auto" or env_path is not None
    if explicit_sensorius or auto_sensorius:
        db_path = _resolve_sensorius_db_path(create_if_missing=explicit_sensorius or env_path is not None)
        if db_path is not None:
            return SensoriusSQLiteStore(db_path)

    return ConfigStore()

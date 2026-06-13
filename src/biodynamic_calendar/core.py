"""Reusable biodynamic calendar calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import math
import os
import threading
import time as time_mod
from zoneinfo import ZoneInfo

try:
    from astral import LocationInfo
    from astral import moon as _astral_moon
    from astral.sidereal import lmst as _astral_lmst
    from astral.sun import azimuth as _astral_azimuth, elevation as _astral_elevation, sun as _astral_sun
except Exception:  # pragma: no cover - exercised via graceful fallback
    LocationInfo = None
    _astral_moon = None
    _astral_lmst = None
    _astral_azimuth = None
    _astral_elevation = None
    _astral_sun = None


@dataclass(frozen=True)
class BiodynamicConfig:
    latitude: float
    longitude: float
    timezone_name: str


@dataclass(frozen=True)
class _Segment:
    start_local: datetime
    end_local: datetime
    sign_index: int


@dataclass(frozen=True)
class _Interval:
    start_local: datetime
    end_local: datetime
    kind: str


_SIGNS: tuple[dict[str, str], ...] = (
    {"abbr": "Ari", "name": "Aries", "element": "Fire", "plant_part": "Fruit", "color": "#f19707", "accent": "#d64b3b"},
    {"abbr": "Tau", "name": "Taurus", "element": "Earth", "plant_part": "Root", "color": "#e5b172", "accent": "#644817"},
    {"abbr": "Gem", "name": "Gemini", "element": "Air", "plant_part": "Flower", "color": "#F7E605", "accent": "#C4DCF8"},
    {"abbr": "Cnc", "name": "Cancer", "element": "Water", "plant_part": "Leaf", "color": "#277A00", "accent": "#2f6eb8"},
    {"abbr": "Leo", "name": "Leo", "element": "Fire", "plant_part": "Fruit", "color": "#f19707", "accent": "#d64b3b"},
    {"abbr": "Vir", "name": "Virgo", "element": "Earth", "plant_part": "Root", "color": "#e5b172", "accent": "#644817"},
    {"abbr": "Lib", "name": "Libra", "element": "Air", "plant_part": "Flower", "color": "#F7E605", "accent": "#C4DCF8"},
    {"abbr": "Sco", "name": "Scorpio", "element": "Water", "plant_part": "Leaf", "color": "#277A00", "accent": "#2f6eb8"},
    {"abbr": "Sgr", "name": "Sagittarius", "element": "Fire", "plant_part": "Fruit", "color": "#f19707", "accent": "#d64b3b"},
    {"abbr": "Cap", "name": "Capricorn", "element": "Earth", "plant_part": "Root", "color": "#e5b172", "accent": "#644817"},
    {"abbr": "Aqr", "name": "Aquarius", "element": "Air", "plant_part": "Flower", "color": "#F7E605", "accent": "#C4DCF8"},
    {"abbr": "Psc", "name": "Pisces", "element": "Water", "plant_part": "Leaf", "color": "#277A00", "accent": "#2f6eb8"},
)
_WEEKDAYS: tuple[str, ...] = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_EPHEMERIS_NAME = "de421.bsp"
_EPHEMERIS_RETRY_COOLDOWN_SEC = 900.0
_SKYFIELD_LOCK = threading.Lock()
_ephemeris_last_error = ""
_ephemeris_retry_after_monotonic = 0.0
_OFF_PERIOD_COLOR = "#5f6770"
_OFF_PERIOD_ACCENT = "#d7dbe0"
_MOON_NODE_WINDOW = timedelta(hours=2)
_PERIGEE_WINDOW = timedelta(hours=12)
_APOGEE_WINDOW = timedelta(hours=12)
_OFF_PERIOD_LABELS = {
    "lunar_node": "Lunar Node",
    "perigee": "Perigee",
    "apogee": "Apogee",
}
_OFF_OVERLAY_KINDS = {"lunar_node", "perigee"}
_GROUNDING_REMINDER = "Suggestion: prioritize actual plant health, irrigation status, weather, and disease pressure over calendar timing."
_PAYLOAD_CACHE_TTL_SEC = 30.0
_PAYLOAD_CACHE: dict[tuple[str, str, str, str], tuple[float, dict[str, object]]] = {}
_SIGN_INDEX_BY_ABBR: dict[str, int] = {str(item["abbr"]): idx for idx, item in enumerate(_SIGNS)}
_CONSTELLATION_ALIASES: dict[str, str] = {
    "Oph": "Sco",
    "Cet": "Psc",
    "Aur": "Tau",
    "Ori": "Tau",
    "Sex": "Leo",
}
_CALENDAR_GRID_DAYS = 42
_DAILY_FORECAST_DAYS = 29
_PLANT_PART_LABELS = {
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
_COMMON_PLANT_PART_TERMS = {
    "arugula": "Leaf",
    "basil": "Leaf",
    "beet": "Root",
    "broccoli": "Flower",
    "cabbage": "Leaf",
    "carrot": "Root",
    "cauliflower": "Flower",
    "celery": "Leaf",
    "chard": "Leaf",
    "cilantro": "Leaf",
    "cucumber": "Fruit",
    "dill": "Leaf",
    "eggplant": "Fruit",
    "garlic": "Root",
    "kale": "Leaf",
    "lavender": "Flower",
    "lettuce": "Leaf",
    "melon": "Fruit",
    "onion": "Root",
    "parsley": "Leaf",
    "pea": "Fruit",
    "pepper": "Fruit",
    "potato": "Root",
    "radish": "Root",
    "spinach": "Leaf",
    "squash": "Fruit",
    "tomato": "Fruit",
    "turnip": "Root",
    "zucchini": "Fruit",
}


def load_config_from_env() -> BiodynamicConfig | None:
    lat_raw = str(os.getenv("BIODYNAMIC_LAT", "")).strip()
    lon_raw = str(os.getenv("BIODYNAMIC_LON", "")).strip()
    tz_name = str(os.getenv("BIODYNAMIC_TZ", "")).strip()
    if not lat_raw or not lon_raw or not tz_name:
        return None
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
        ZoneInfo(tz_name)
    except Exception:
        return None
    return BiodynamicConfig(latitude=lat, longitude=lon, timezone_name=tz_name)


def _require_config(config: BiodynamicConfig | None) -> BiodynamicConfig:
    resolved = config or load_config_from_env()
    if resolved is None:
        raise ValueError("BiodynamicConfig is required or BIODYNAMIC_LAT/BIODYNAMIC_LON/BIODYNAMIC_TZ must be set")
    ZoneInfo(resolved.timezone_name)
    return resolved


def get_biodynamic_local_now(config: BiodynamicConfig | None = None) -> datetime:
    resolved = _require_config(config)
    return datetime.now(ZoneInfo(resolved.timezone_name))


def _empty_payload(month_date: date | None = None) -> dict[str, object]:
    month_label = month_date.strftime("%B %Y") if isinstance(month_date, date) else ""
    return {
        "ok": False,
        "reason": "unavailable",
        "tz": "",
        "source": "skyfield",
        "month_label": month_label,
        "weekday_labels": list(_WEEKDAYS),
        "current": {},
        "upcoming": [],
        "calendar": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _sign_meta(sign_index: int) -> dict[str, object]:
    meta = dict(_SIGNS[sign_index % len(_SIGNS)])
    meta["sign_index"] = int(sign_index % len(_SIGNS))
    return meta


def _traditional_full_moon_name(phase_date: date | None) -> str:
    names_by_month = {
        1: "Wolf Moon",
        2: "Snow Moon",
        3: "Worm Moon",
        4: "Pink Moon",
        5: "Flower Moon",
        6: "Strawberry Moon",
        7: "Buck Moon",
        8: "Sturgeon Moon",
        9: "Harvest Moon",
        10: "Hunter's Moon",
        11: "Beaver Moon",
        12: "Cold Moon",
    }
    return names_by_month.get(getattr(phase_date, "month", None), "Full Moon")


def _moon_phase_name(phase_val: float, phase_date: date | None = None) -> str:
    p = phase_val % 28.0

    def _circular_dist(a: float, b: float, cycle: float = 28.0) -> float:
        d = abs(a - b) % cycle
        return min(d, cycle - d)

    if _circular_dist(p, 0.0) <= 1.0:
        return "New Moon"
    if _circular_dist(p, 7.0) <= 1.0:
        return "1st Quarter"
    if _circular_dist(p, 14.0) <= 1.0:
        return _traditional_full_moon_name(phase_date)
    if _circular_dist(p, 21.0) <= 1.0:
        return "3rd Quarter"
    if 1.0 < p < 6.0:
        return "Waxing Crescent"
    if 8.0 < p < 13.0:
        return "Waxing Gibbous"
    if 15.0 < p < 20.0:
        return "Waning Gibbous"
    return "Waning Crescent"


def _skyfield_data_dir() -> Path:
    env_override = str(os.getenv("BIODYNAMIC_SKYFIELD_DIR", "")).strip()
    if env_override:
        data_dir = Path(env_override).expanduser().resolve()
    else:
        data_dir = Path(__file__).resolve().parent / "data" / "skyfield"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _ephemeris_path() -> Path:
    return _skyfield_data_dir() / _EPHEMERIS_NAME


def ephemeris_status() -> dict[str, object]:
    ephemeris_path = _ephemeris_path()
    retry_after = max(0.0, _ephemeris_retry_after_monotonic - time_mod.monotonic())
    return {
        "name": _EPHEMERIS_NAME,
        "path": str(ephemeris_path),
        "installed": ephemeris_path.exists(),
        "last_error": _ephemeris_last_error,
        "retry_after_sec": int(round(retry_after)),
    }


@lru_cache(maxsize=1)
def _skyfield_runtime() -> tuple[object, object, object, object]:
    global _ephemeris_last_error, _ephemeris_retry_after_monotonic
    try:
        from skyfield.api import Loader, load_constellation_map
    except Exception as exc:
        raise RuntimeError("skyfield_not_installed") from exc

    with _SKYFIELD_LOCK:
        data_dir = _skyfield_data_dir()
        loader = Loader(str(data_dir), verbose=False)
        ts = loader.timescale()
        ephemeris_path = _ephemeris_path()

        if not ephemeris_path.exists():
            now_mono = time_mod.monotonic()
            if now_mono < _ephemeris_retry_after_monotonic:
                retry_sec = int(round(_ephemeris_retry_after_monotonic - now_mono))
                raise RuntimeError(f"ephemeris_download_deferred:{retry_sec}s")
            try:
                eph = loader(_EPHEMERIS_NAME)
                constellation_at = load_constellation_map()
                _ephemeris_last_error = ""
                _ephemeris_retry_after_monotonic = 0.0
                return loader, ts, eph, constellation_at
            except Exception as exc:
                _ephemeris_last_error = exc.__class__.__name__
                _ephemeris_retry_after_monotonic = now_mono + _EPHEMERIS_RETRY_COOLDOWN_SEC
                raise RuntimeError(f"ephemeris_download_failed:{_ephemeris_last_error}") from exc

        eph = loader(_EPHEMERIS_NAME)
        constellation_at = load_constellation_map()
        _ephemeris_last_error = ""
        _ephemeris_retry_after_monotonic = 0.0
        return loader, ts, eph, constellation_at


def _moon_sign_index(dt_local: datetime, ts, eph, constellation_at) -> int:
    moon = eph["moon"]
    earth = eph["earth"]
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    apparent = earth.at(t).observe(moon).apparent()
    abbr = str(constellation_at(apparent))
    idx = _biodynamic_sign_index_for_constellation(abbr)
    return idx


def _biodynamic_sign_index_for_constellation(abbr: str) -> int:
    mapped_abbr = _CONSTELLATION_ALIASES.get(str(abbr), str(abbr))
    idx = _SIGN_INDEX_BY_ABBR.get(mapped_abbr)
    if idx is None:
        raise RuntimeError(f"unsupported_constellation:{abbr}")
    return idx


def _refine_transition(start_local: datetime, end_local: datetime, start_sign: int, ts, eph, constellation_at) -> datetime:
    lo = start_local
    hi = end_local
    for _ in range(20):
        span = (hi - lo).total_seconds()
        if span <= 60.0:
            break
        mid = lo + timedelta(seconds=span / 2.0)
        if _moon_sign_index(mid, ts, eph, constellation_at) == start_sign:
            lo = mid
        else:
            hi = mid
    return hi


def _split_segments(start_local: datetime, end_local: datetime, ts, eph, constellation_at) -> list[_Segment]:
    segments: list[_Segment] = []
    if start_local >= end_local:
        return segments
    current_start = start_local
    current_sign = _moon_sign_index(current_start, ts, eph, constellation_at)
    probe_prev = current_start
    probe = current_start + timedelta(hours=1)
    while probe < end_local:
        probe_sign = _moon_sign_index(probe, ts, eph, constellation_at)
        if probe_sign != current_sign:
            transition = _refine_transition(probe_prev, probe, current_sign, ts, eph, constellation_at)
            segments.append(_Segment(current_start, transition, current_sign))
            current_start = transition
            current_sign = _moon_sign_index(transition + timedelta(minutes=1), ts, eph, constellation_at)
        probe_prev = probe
        probe = probe + timedelta(hours=1)
    segments.append(_Segment(current_start, end_local, current_sign))
    return segments


def _format_hm(dt_local: datetime) -> str:
    return dt_local.strftime("%H:%M")


def _moon_latitude_deg(dt_local: datetime, ts, eph) -> float:
    from skyfield.framelib import ecliptic_frame

    moon = eph["moon"]
    earth = eph["earth"]
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    apparent = earth.at(t).observe(moon).apparent()
    lat, _, _ = apparent.frame_latlon(ecliptic_frame)
    return float(lat.degrees)


def _moon_distance_km(dt_local: datetime, ts, eph) -> float:
    moon = eph["moon"]
    earth = eph["earth"]
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    return float(earth.at(t).observe(moon).distance().km)


def _moon_declination_deg(dt_local: datetime, ts, eph) -> float:
    moon = eph["moon"]
    earth = eph["earth"]
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    apparent = earth.at(t).observe(moon).apparent()
    _ra, dec, _distance = apparent.radec()
    return float(dec.degrees)


def _moon_direction(dt_local: datetime, ts, eph) -> str:
    try:
        before = _moon_declination_deg(dt_local - timedelta(hours=6), ts, eph)
        after = _moon_declination_deg(dt_local + timedelta(hours=6), ts, eph)
    except Exception:
        return ""
    return "ascending" if after >= before else "descending"


def _refine_node_crossing(lo: datetime, hi: datetime, ts, eph) -> datetime:
    lo_val = _moon_latitude_deg(lo, ts, eph)
    for _ in range(24):
        span = (hi - lo).total_seconds()
        if span <= 60.0:
            break
        mid = lo + timedelta(seconds=span / 2.0)
        mid_val = _moon_latitude_deg(mid, ts, eph)
        if mid_val == 0.0:
            return mid
        if math.copysign(1.0, lo_val or 1.0) == math.copysign(1.0, mid_val or 1.0):
            lo = mid
            lo_val = mid_val
        else:
            hi = mid
    return hi


def _refine_distance_extreme(center: datetime, ts, eph, *, find_min: bool) -> datetime:
    lo = center - timedelta(hours=6)
    hi = center + timedelta(hours=6)
    for _ in range(24):
        if (hi - lo).total_seconds() <= 60.0:
            break
        third = (hi - lo) / 3
        m1 = lo + third
        m2 = hi - third
        d1 = _moon_distance_km(m1, ts, eph)
        d2 = _moon_distance_km(m2, ts, eph)
        prefer_left = d1 <= d2 if find_min else d1 >= d2
        if prefer_left:
            hi = m2
        else:
            lo = m1
    return lo + ((hi - lo) / 2)


def _refine_perigee(center: datetime, ts, eph) -> datetime:
    return _refine_distance_extreme(center, ts, eph, find_min=True)


def _refine_apogee(center: datetime, ts, eph) -> datetime:
    return _refine_distance_extreme(center, ts, eph, find_min=False)


def _build_off_intervals(start_local: datetime, end_local: datetime, ts, eph) -> list[_Interval]:
    intervals: list[_Interval] = []
    if start_local >= end_local:
        return intervals
    probe = start_local - timedelta(hours=24)
    probe_end = end_local + timedelta(hours=24)
    step = timedelta(hours=1)
    prev = probe
    prev_lat = _moon_latitude_deg(prev, ts, eph)
    prev_prev_dist = None
    prev_dist = _moon_distance_km(prev, ts, eph)
    cur = prev + step
    while cur <= probe_end:
        cur_lat = _moon_latitude_deg(cur, ts, eph)
        cur_dist = _moon_distance_km(cur, ts, eph)
        if (prev_lat == 0.0) or (cur_lat == 0.0) or (prev_lat < 0.0 < cur_lat) or (prev_lat > 0.0 > cur_lat):
            event = _refine_node_crossing(prev, cur, ts, eph)
            intervals.append(_Interval(event - _MOON_NODE_WINDOW, event + _MOON_NODE_WINDOW, "lunar_node"))
        if prev_prev_dist is not None and prev_dist <= prev_prev_dist and prev_dist <= cur_dist:
            event = _refine_perigee(prev, ts, eph)
            intervals.append(_Interval(event - _PERIGEE_WINDOW, event + _PERIGEE_WINDOW, "perigee"))
        elif prev_prev_dist is not None and prev_dist >= prev_prev_dist and prev_dist >= cur_dist:
            event = _refine_apogee(prev, ts, eph)
            intervals.append(_Interval(event - _APOGEE_WINDOW, event + _APOGEE_WINDOW, "apogee"))
        prev = cur
        prev_lat = cur_lat
        prev_prev_dist = prev_dist
        prev_dist = cur_dist
        cur = cur + step
    filtered = [
        _Interval(max(iv.start_local, start_local), min(iv.end_local, end_local), iv.kind)
        for iv in intervals
        if iv.end_local > start_local and iv.start_local < end_local
    ]
    filtered.sort(key=lambda iv: iv.start_local)
    merged: list[_Interval] = []
    for iv in filtered:
        if not merged or iv.start_local > merged[-1].end_local or iv.kind != merged[-1].kind:
            merged.append(iv)
        else:
            last = merged[-1]
            merged[-1] = _Interval(last.start_local, max(last.end_local, iv.end_local), last.kind)
    return merged


def _apply_off_overlays(day_segments: list[dict[str, object]], day_start: datetime, day_end: datetime, off_intervals: list[_Interval]) -> list[dict[str, object]]:
    segments = list(day_segments)
    for off in off_intervals:
        overlap_start = max(off.start_local, day_start)
        overlap_end = min(off.end_local, day_end)
        if overlap_end <= overlap_start:
            continue
        next_segments: list[dict[str, object]] = []
        for seg in segments:
            seg_start = datetime.combine(day_start.date(), time.min, tzinfo=day_start.tzinfo) + timedelta(
                minutes=int(str(seg.get("start", "00:00")).split(":")[0]) * 60 + int(str(seg.get("start", "00:00")).split(":")[1])
            )
            seg_end_raw = str(seg.get("end", "24:00"))
            if seg_end_raw == "24:00":
                seg_end = day_end
            else:
                seg_end = datetime.combine(day_start.date(), time.min, tzinfo=day_start.tzinfo) + timedelta(
                    minutes=int(seg_end_raw.split(":")[0]) * 60 + int(seg_end_raw.split(":")[1])
                )
            if seg_end <= overlap_start or seg_start >= overlap_end:
                next_segments.append(seg)
                continue
            if seg_start < overlap_start:
                left = dict(seg)
                left["start"] = _format_hm(seg_start)
                left["end"] = _format_hm(overlap_start)
                next_segments.append(left)
            mid = dict(seg)
            mid["start"] = _format_hm(max(seg_start, overlap_start))
            mid["end"] = "24:00" if overlap_end >= day_end else _format_hm(overlap_end)
            mid["kind"] = "off"
            mid["off_kind"] = off.kind
            mid["off_label"] = _OFF_PERIOD_LABELS.get(off.kind, "Rest")
            mid["sign"] = "Rest"
            mid["element"] = "Pause"
            mid["plant_part"] = "Rest"
            mid["color"] = _OFF_PERIOD_COLOR
            mid["accent"] = _OFF_PERIOD_ACCENT
            next_segments.append(mid)
            if seg_end > overlap_end:
                right = dict(seg)
                right["start"] = _format_hm(overlap_end)
                right["end"] = "24:00" if seg_end >= day_end else _format_hm(seg_end)
                next_segments.append(right)
        segments = next_segments
    return segments


def _lunar_flags_for_day(day_start: datetime, day_end: datetime, off_intervals: list[_Interval]) -> dict[str, object]:
    events: list[dict[str, str]] = []
    flags = {
        "lunar_node": False,
        "perigee": False,
        "apogee": False,
    }
    for interval in off_intervals:
        overlap_start = max(interval.start_local, day_start)
        overlap_end = min(interval.end_local, day_end)
        if overlap_end <= overlap_start:
            continue
        if interval.kind in flags:
            flags[interval.kind] = True
        events.append(
            {
                "type": interval.kind,
                "label": _OFF_PERIOD_LABELS.get(interval.kind, "Rest"),
                "start": _format_hm(overlap_start),
                "end": "24:00" if overlap_end >= day_end else _format_hm(overlap_end),
            }
        )
    return {
        "lunar_node": flags["lunar_node"],
        "perigee": flags["perigee"],
        "apogee": flags["apogee"],
        "lunar_events": events,
    }


def _segment_bounds_for_day(day_date: date, seg: dict[str, object], tzinfo: ZoneInfo) -> tuple[datetime, datetime] | None:
    start_raw = str(seg.get("start", "00:00"))
    end_raw = str(seg.get("end", "24:00"))
    try:
        start_h, start_m = [int(x) for x in start_raw.split(":", 1)]
        start_dt = datetime.combine(day_date, time.min, tzinfo=tzinfo) + timedelta(hours=start_h, minutes=start_m)
        if end_raw == "24:00":
            end_dt = datetime.combine(day_date, time.min, tzinfo=tzinfo) + timedelta(days=1)
        else:
            end_h, end_m = [int(x) for x in end_raw.split(":", 1)]
            end_dt = datetime.combine(day_date, time.min, tzinfo=tzinfo) + timedelta(hours=end_h, minutes=end_m)
        if end_dt <= start_dt:
            return None
        return start_dt, end_dt
    except Exception:
        return None


def _build_segment_timeline(days: list[dict[str, object]], tzinfo: ZoneInfo) -> list[dict[str, object]]:
    timeline: list[dict[str, object]] = []
    for day in days:
        try:
            day_date = date.fromisoformat(str(day.get("date") or ""))
        except Exception:
            continue
        for seg in list(day.get("segments") or []):
            bounds = _segment_bounds_for_day(day_date, seg, tzinfo)
            if not bounds:
                continue
            start_dt, end_dt = bounds
            timeline.append(
                {
                    "start_local": start_dt,
                    "end_local": end_dt,
                    "start_hm": _format_hm(start_dt),
                    "end_hm": _format_hm(end_dt) if end_dt.date() == day_date else "24:00",
                    "sign": str(seg.get("sign") or ""),
                    "element": str(seg.get("element") or ""),
                    "plant_part": str(seg.get("plant_part") or ""),
                    "color": str(seg.get("color") or ""),
                    "accent": str(seg.get("accent") or ""),
                    "kind": str(seg.get("kind") or "sign"),
                    "off_kind": str(seg.get("off_kind") or ""),
                    "off_label": str(seg.get("off_label") or ""),
                }
            )
    timeline.sort(key=lambda item: item["start_local"])
    return timeline


def _build_current_segment_timeline(
    now_local: datetime,
    tzinfo: ZoneInfo,
    ts,
    eph,
    constellation_at,
) -> list[dict[str, object]]:
    start_date = now_local.date() - timedelta(days=1)
    current_days, _segments = _build_day_rows(start_date, 4, tzinfo, ts, eph, constellation_at, now_local)
    return _build_segment_timeline(current_days, tzinfo)


def _build_day_rows(
    start_date: date,
    day_count: int,
    tzinfo: ZoneInfo,
    ts,
    eph,
    constellation_at,
    now_local: datetime,
    *,
    in_month_for: int | None = None,
) -> tuple[list[dict[str, object]], list[_Segment]]:
    range_start = datetime.combine(start_date, time.min, tzinfo=tzinfo)
    range_end = datetime.combine(start_date + timedelta(days=day_count), time.min, tzinfo=tzinfo)

    segments = _split_segments(range_start, range_end, ts, eph, constellation_at)
    off_intervals = _build_off_intervals(range_start, range_end, ts, eph)
    days: list[dict[str, object]] = []
    today = now_local.date()

    for day_index in range(day_count):
        day_date = start_date + timedelta(days=day_index)
        day_start = datetime.combine(day_date, time.min, tzinfo=tzinfo)
        day_end = day_start + timedelta(days=1)
        day_segments: list[dict[str, object]] = []
        dominant_sign = None
        dominant_seconds = -1.0

        for segment in segments:
            overlap_start = max(segment.start_local, day_start)
            overlap_end = min(segment.end_local, day_end)
            if overlap_end <= overlap_start:
                continue
            span_sec = (overlap_end - overlap_start).total_seconds()
            meta = _sign_meta(segment.sign_index)
            if span_sec > dominant_seconds:
                dominant_seconds = span_sec
                dominant_sign = meta
            day_segments.append(
                {
                    "start": _format_hm(overlap_start),
                    "end": "24:00" if overlap_end >= day_end else _format_hm(overlap_end),
                    "sign": meta["name"],
                    "element": meta["element"],
                    "plant_part": meta["plant_part"],
                    "color": meta["color"],
                    "accent": meta["accent"],
                    "kind": "sign",
                }
            )

        overlay_intervals = [iv for iv in off_intervals if iv.kind in _OFF_OVERLAY_KINDS]
        day_segments = _apply_off_overlays(day_segments, day_start, day_end, overlay_intervals)
        lunar_flags = _lunar_flags_for_day(day_start, day_end, off_intervals)
        day_payload = {
            "date": day_date.isoformat(),
            "day": day_date.day,
            "weekday": _WEEKDAYS[(day_date.weekday() + 1) % 7],
            "in_month": in_month_for is None or day_date.month == in_month_for,
            "is_today": day_date == today,
            "segments": day_segments,
            "dominant_sign": (dominant_sign or {}).get("name", ""),
            "dominant_sign_abbr": (dominant_sign or {}).get("abbr", ""),
            "dominant_element": (dominant_sign or {}).get("element", ""),
            "dominant_plant_part": (dominant_sign or {}).get("plant_part", ""),
            "dominant_color": (dominant_sign or {}).get("color", "#d8d8d8"),
            "dominant_accent": (dominant_sign or {}).get("accent", "#f2f2f2"),
            "moon_direction": _moon_direction(day_start + timedelta(hours=12), ts, eph),
        }
        day_payload.update(lunar_flags)
        days.append(day_payload)
    return days, segments


def _build_calendar(month_anchor: date, tzinfo: ZoneInfo, ts, eph, constellation_at, now_local: datetime) -> tuple[list[dict[str, object]], list[_Segment]]:
    month_start = month_anchor.replace(day=1)
    grid_start = month_start - timedelta(days=(month_start.weekday() + 1) % 7)
    return _build_day_rows(
        grid_start,
        _CALENDAR_GRID_DAYS,
        tzinfo,
        ts,
        eph,
        constellation_at,
        now_local,
        in_month_for=month_anchor.month,
    )


def get_biodynamic_forecast(
    start_date: date,
    *,
    config: BiodynamicConfig | None = None,
    days: int = _DAILY_FORECAST_DAYS,
) -> list[dict[str, object]]:
    resolved = _require_config(config)
    if days <= 0:
        return []

    _, ts, eph, constellation_at = _skyfield_runtime()
    tzinfo = ZoneInfo(resolved.timezone_name)
    now_local = datetime.now(tzinfo)
    forecast_days, _ = _build_day_rows(start_date, days, tzinfo, ts, eph, constellation_at, now_local)
    return forecast_days


def _normalize_crop_stage(crop_stage: str | None) -> str:
    stage = str(crop_stage or "general").strip().lower()
    return stage if stage in {"immature", "seedling", "veg", "maturing", "mature", "harvest", "general"} else "general"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "stress", "stressed"}


def _safe_float(value: object) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _safe_int(value: object, default: int = 0) -> int:
    try:
        out = int(float(str(value).strip()))
    except Exception:
        return default
    return out


def _parse_iso_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _normalize_plant_part_label(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in _PLANT_PART_LABELS:
        return _PLANT_PART_LABELS[text]
    for token, label in _PLANT_PART_LABELS.items():
        if token in text:
            return label
    return ""


def _planting_label(planting: dict[str, object]) -> str:
    name = str(planting.get("name") or planting.get("plant") or planting.get("crop") or "Unnamed planting").strip()
    variety = str(planting.get("variety") or "").strip()
    if variety and variety.lower() not in name.lower():
        return f"{name} ({variety})"
    return name


def _planting_part(planting: dict[str, object]) -> str:
    for key in ("plant_part", "biodynamic_part", "part", "plant_type", "type"):
        explicit = _normalize_plant_part_label(planting.get(key))
        if explicit:
            return explicit
    haystack = " ".join(
        str(planting.get(key) or "")
        for key in ("name", "plant", "crop", "variety", "plant_type", "type", "attributes", "notes")
    ).lower()
    for token, label in _COMMON_PLANT_PART_TERMS.items():
        if token in haystack:
            return label
    return ""


def _planting_method(planting: dict[str, object]) -> str:
    method = str(planting.get("start_method") or planting.get("method") or planting.get("started_as") or "").strip().lower()
    if "transplant" in method:
        return "transplant"
    if "seed" in method or "sow" in method:
        return "seed"
    return "start"


def _is_cannabis_planting(planting: dict[str, object]) -> bool:
    haystack = " ".join(
        str(planting.get(key) or "")
        for key in ("name", "plant", "crop", "variety", "plant_type", "type", "attributes", "notes")
    ).lower()
    return any(token in haystack for token in ("cannabis", "hemp", "marijuana", "marihuana"))


def _planting_stage_for_day(planting: dict[str, object], target_date: date) -> str:
    start = _parse_iso_date(planting.get("start_date"))
    harvest = _parse_iso_date(planting.get("expected_harvest_date") or planting.get("harvest_date"))
    harvest_window = max(0, min(_safe_int(planting.get("harvest_window_days"), 3), 60))
    if start is not None and target_date < start:
        return "general"
    if harvest is not None:
        days_to_harvest = (harvest - target_date).days
        if -harvest_window <= days_to_harvest <= 0:
            return "harvest"
        if days_to_harvest < -harvest_window:
            return "mature"
    if start is None:
        return "general"
    days_since_start = (target_date - start).days
    if _is_cannabis_planting(planting):
        immature_days = 21 if _planting_method(planting) == "seed" else 14
        return "immature" if days_since_start <= immature_days else "mature"
    seedling_days = 21 if _planting_method(planting) == "seed" else 10
    if days_since_start <= seedling_days:
        return "seedling"
    if harvest is not None and harvest > start:
        progress = days_since_start / max(1, (harvest - start).days)
        if progress >= 0.78:
            return "maturing"
    return "veg"


def _planting_entries_for_day(plantings: list[dict[str, object]] | None, target_date: date) -> list[dict[str, object]]:
    if not isinstance(plantings, list):
        return []
    entries: list[dict[str, object]] = []
    for idx, planting in enumerate(plantings):
        if not isinstance(planting, dict):
            continue
        start = _parse_iso_date(planting.get("start_date"))
        harvest = _parse_iso_date(planting.get("expected_harvest_date") or planting.get("harvest_date"))
        if start is None and harvest is None:
            continue
        priority = 999
        reason = ""
        days_from_start: int | None = None
        days_to_harvest: int | None = None
        if start is not None:
            days_from_start = (target_date - start).days
            if days_from_start == 0:
                priority, reason = 0, "start_due"
            elif -7 <= days_from_start < 0:
                priority, reason = min(priority, 30 + abs(days_from_start)), "upcoming_start"
            elif 0 < days_from_start <= 21:
                priority, reason = min(priority, 40 + days_from_start), "recent_start"
        if harvest is not None:
            days_to_harvest = (harvest - target_date).days
            harvest_window = max(0, min(_safe_int(planting.get("harvest_window_days"), 3), 60))
            if days_to_harvest == 0:
                priority, reason = min(priority, 0), "harvest_due"
            elif 0 < days_to_harvest <= 14:
                priority, reason = min(priority, 10 + days_to_harvest), "upcoming_harvest"
            elif -harvest_window <= days_to_harvest < 0:
                priority, reason = min(priority, 15 + abs(days_to_harvest)), "harvest_window"
        if reason == "" and start is not None and start <= target_date and (harvest is None or target_date <= harvest):
            priority, reason = 80, "active"
        if reason == "":
            continue
        entries.append(
            {
                "planting": planting,
                "start": start,
                "harvest": harvest,
                "priority": priority,
                "reason": reason,
                "days_from_start": days_from_start,
                "days_to_harvest": days_to_harvest,
                "stage": _planting_stage_for_day(planting, target_date),
                "part": _planting_part(planting),
                "method": _planting_method(planting),
                "index": idx,
            }
        )
    return sorted(entries, key=lambda row: (int(row["priority"]), int(row["index"])))


def _stage_from_planting_entries(entries: list[dict[str, object]]) -> str:
    stage_priority = {"harvest": 0, "immature": 1, "seedling": 2, "maturing": 3, "mature": 4, "veg": 5, "general": 6}
    stage = next(
        (
            str(row.get("stage") or "")
            for row in sorted(entries, key=lambda item: stage_priority.get(str(item.get("stage") or "general"), 9))
            if str(row.get("stage") or "") in stage_priority
        ),
        "",
    )
    return stage if stage in {"immature", "seedling", "veg", "maturing", "mature", "harvest"} else ""


def _days_away_phrase(days: int | None, *, past: str) -> str:
    if days is None:
        return ""
    if days == 0:
        return "today"
    if days > 0:
        return f"in {days} day{'s' if days != 1 else ''}"
    return f"{abs(days)} day{'s' if abs(days) != 1 else ''} {past}"


def _planting_alignment(day_part: str, planting_part: str) -> str:
    if not planting_part or not day_part:
        return "Use the configured crop timing as the practical anchor."
    if planting_part.lower() == day_part.lower():
        return f"{planting_part} focus aligns with this {day_part.title()} day."
    return f"{planting_part} focus does not match this {day_part.title()} day; use plant health and schedule pressure first."


def _planting_hint_lines(day: dict[str, object], plantings: list[dict[str, object]] | None) -> list[str]:
    target_date = _parse_iso_date(day.get("date"))
    if target_date is None:
        return []
    configured = [row for row in (plantings or []) if isinstance(row, dict)]
    if not configured:
        return []
    entries = _planting_entries_for_day(plantings, target_date)
    if not entries:
        return ["Plant Plan: no configured seed, transplant, or harvest dates are close to the selected day."]

    day_part = str(day.get("dominant_plant_part") or "").strip().lower()
    lines: list[str] = []
    for entry in entries[:5]:
        planting = entry["planting"]
        label = _planting_label(planting)
        method = str(entry.get("method") or "start")
        part = str(entry.get("part") or "")
        alignment = _planting_alignment(day_part, part)
        reason = str(entry.get("reason") or "")
        days_from_start = entry.get("days_from_start") if isinstance(entry.get("days_from_start"), int) else None
        days_to_harvest = entry.get("days_to_harvest") if isinstance(entry.get("days_to_harvest"), int) else None
        if reason == "start_due":
            action = "transplant" if method == "transplant" else "sow" if method == "seed" else "start"
            lines.append(f"Plant Plan: {action.capitalize()} {label} on the selected day. {alignment}")
        elif reason == "upcoming_start":
            action = "transplant" if method == "transplant" else "sow" if method == "seed" else "start"
            days_until_start = abs(days_from_start) if days_from_start is not None else None
            phrase = _days_away_phrase(days_until_start, past="ago")
            lines.append(f"Plant Plan: {label} is scheduled to {action} {phrase}; use this day for bed, media, label, and water planning.")
        elif reason == "recent_start":
            days_since_start = max(0, days_from_start) if days_from_start is not None else None
            phrase = f"{days_since_start} day{'s' if days_since_start != 1 else ''} ago" if days_since_start is not None else "recently"
            stage = str(entry.get("stage") or "")
            stage_note = f" and is in {stage} stage" if stage in {"immature", "seedling", "veg", "maturing", "mature"} else ""
            lines.append(f"Plant Plan: {label} was started {phrase}{stage_note}; check establishment, moisture consistency, and early vigor. {alignment}")
        elif reason == "harvest_due":
            lines.append(f"Plant Plan: {label} reaches its expected harvest date on the selected day. {alignment}")
        elif reason == "upcoming_harvest":
            phrase = _days_away_phrase(days_to_harvest, past="ago")
            lines.append(f"Plant Plan: {label} is expected to harvest {phrase}; use hints for ripeness checks, irrigation restraint, and harvest logistics.")
        elif reason == "harvest_window":
            phrase = _days_away_phrase(days_to_harvest, past="past expected harvest")
            lines.append(f"Plant Plan: {label} is {phrase}; inspect maturity and quality before waiting for a better calendar window.")
        else:
            stage = str(entry.get("stage") or "general")
            lines.append(f"Plant Plan: {label} is in {stage} stage. {alignment}")

        location = str(planting.get("location") or planting.get("bed") or "").strip()
        attributes = str(planting.get("attributes") or planting.get("notes") or "").strip()
        details = "; ".join(part for part in (f"location: {location}" if location else "", attributes) if part)
        if details:
            lines.append(f"Plant Attributes: {label}: {details[:180]}")
    if len(entries) > 5:
        lines.append(f"Plant Plan: {len(entries) - 5} additional configured plantings are near this date.")
    return lines


def get_hint_lines_for_day(
    day: dict | None,
    crop_stage: str | None = None,
    plant_state: dict | None = None,
    plantings: list[dict[str, object]] | None = None,
) -> list[str]:
    lines = ["Biodynamic Hints"]
    if not isinstance(day, dict):
        lines.append("Suggestion: no biodynamic hint available for this day.")
        return lines

    part = str(day.get("dominant_plant_part") or "").strip().lower()
    sign = str(day.get("dominant_sign") or "--").strip()
    target_date = _parse_iso_date(day.get("date"))
    planting_entries = _planting_entries_for_day(plantings, target_date) if target_date is not None else []
    stage = _normalize_crop_stage(crop_stage or _stage_from_planting_entries(planting_entries))
    part_hints = {
        "root": {
            "immature": ["Suggestion: suitable for immature-stage establishment checks, gentle irrigation review, and avoiding unnecessary root disturbance."],
            "seedling": ["Suggestion: suitable for transplant timing, root establishment checks, and gentle media moisture review."],
            "veg": ["Suggestion: suitable for soil cultivation, root-zone feeding, compost teas, and drainage checks."],
            "maturing": ["Suggestion: suitable for stabilizing irrigation and avoiding unnecessary root disturbance."],
            "mature": ["Suggestion: suitable for root crop harvest, storage checks, and restrained soil work."],
            "harvest": ["Suggestion: suitable for root crop lifting, curing, sorting, and storage preparation."],
            "general": ["Suggestion: suitable for root-zone work, soil amendments, transplanting, and root crop attention."],
        },
        "leaf": {
            "immature": ["Suggestion: suitable for immature-stage establishment checks, moisture consistency, and early leaf health review."],
            "seedling": ["Suggestion: suitable for moisture consistency, gentle hardening, and early leaf health checks."],
            "veg": ["Suggestion: suitable for leafy growth support, irrigation tuning, foliar feeding, and canopy inspection."],
            "maturing": ["Suggestion: suitable for maintaining canopy function without pushing excess soft growth."],
            "mature": ["Suggestion: suitable for leafy harvest, quality checks, and disease scouting."],
            "harvest": ["Suggestion: suitable for harvesting leafy greens and herbs when freshness is the priority."],
            "general": ["Suggestion: suitable for irrigation, leafy crops, foliar feeding, and canopy health review."],
        },
        "flower": {
            "immature": ["Suggestion: suitable for immature-stage establishment checks and structure observation; avoid forcing flower-stage decisions too early."],
            "seedling": ["Suggestion: suitable for observing early vigor; avoid forcing bloom too early."],
            "veg": ["Suggestion: suitable for pruning, trellising, airflow work, and pre-flower structure."],
            "maturing": ["Suggestion: suitable for bloom support, pollinator observation, and gentle flower-stage inputs."],
            "mature": ["Suggestion: suitable for flower harvest, aroma checks, seed-set observation, and pollination review."],
            "harvest": ["Suggestion: suitable for harvesting flowers, herbs, and aromatic crops for quality."],
            "general": ["Suggestion: suitable for flowering crops, pollination, pruning for airflow, and bloom observation."],
        },
        "fruit": {
            "immature": ["Suggestion: suitable for immature-stage establishment checks, early vigor observation, and gentle training only if plants are stable."],
            "seedling": ["Suggestion: suitable for planning fruiting crop placement and checking early vigor."],
            "veg": ["Suggestion: suitable for training fruiting plants, trellising, and balanced feeding."],
            "maturing": ["Suggestion: suitable for fruit set checks, ripening support, and avoiding stress swings."],
            "mature": ["Suggestion: suitable for fruit harvest, seed saving, ripeness checks, and quality assessment."],
            "harvest": ["Suggestion: suitable for fruit, seed, and grain harvest when flavor and storage quality matter."],
            "general": ["Suggestion: suitable for fruiting crops, seed work, ripeness checks, and reproductive growth support."],
        },
    }
    if part in part_hints:
        lines.extend(part_hints[part].get(stage) or part_hints[part]["general"])
    else:
        lines.append(f"Suggestion: use {sign} Moon as a planning cue rather than a rigid rule.")

    moon_direction = str(day.get("moon_direction") or "").strip().lower()
    if moon_direction == "ascending":
        lines.append("Timing: ascending Moon emphasizes above-ground growth, grafting, harvest of aerial parts, and observation of upward sap tendency.")
    elif moon_direction == "descending":
        lines.append("Timing: descending Moon emphasizes transplanting, pruning, soil work, compost, and root-zone recovery.")

    if _truthy(day.get("lunar_node")):
        lines.append("Caution: keep lunar node windows observational; avoid major sowing, transplanting, pruning, or harvest decisions near the node.")
    if _truthy(day.get("perigee")):
        lines.append("Caution: perigee can intensify conditions; avoid high-risk interventions if plants are already stressed.")
    if _truthy(day.get("apogee")):
        lines.append("Observation: apogee favors restraint for sensitive crops; avoid over-interpreting weak plant signals.")

    state = plant_state if isinstance(plant_state, dict) else {}
    if _truthy(state.get("stress")):
        lines.append("Plant Condition: stress is reported; delay non-essential biodynamic timing actions until the plant stabilizes.")
    vpd = (
        _safe_float(state.get("vpd"))
        or _safe_float(state.get("plant_vpd"))
        or _safe_float(state.get("Plant VPD"))
        or _safe_float(state.get("ambient_vpd"))
        or _safe_float(state.get("Ambient VPD"))
    )
    if vpd is not None and vpd > 1.8:
        lines.append("Plant Condition: VPD is above 1.8; prioritize climate and irrigation correction before calendar-driven actions.")

    lines.extend(_planting_hint_lines(day, plantings))
    lines.append(_GROUNDING_REMINDER)
    return lines


def _hint_lines_for_day(day: dict | None) -> list[str]:
    return get_hint_lines_for_day(day)


def _moon_local_canvas_angle(moon_az: float, moon_el: float, sun_az: float, sun_el: float) -> float | None:
    def _unit_from_az_el(az_deg: float, el_deg: float) -> tuple[float, float, float]:
        az = math.radians(az_deg)
        el = math.radians(el_deg)
        return (
            math.cos(el) * math.sin(az),
            math.cos(el) * math.cos(az),
            math.sin(el),
        )

    def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])

    def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            (a[1] * b[2]) - (a[2] * b[1]),
            (a[2] * b[0]) - (a[0] * b[2]),
            (a[0] * b[1]) - (a[1] * b[0]),
        )

    def _normalized(v: tuple[float, float, float]) -> tuple[float, float, float] | None:
        mag = math.sqrt(_dot(v, v))
        if not math.isfinite(mag) or mag < 1e-9:
            return None
        return (v[0] / mag, v[1] / mag, v[2] / mag)

    if not all(math.isfinite(v) for v in (moon_az, moon_el, sun_az, sun_el)):
        return None

    moon_vec = _unit_from_az_el(moon_az, moon_el)
    sun_vec = _unit_from_az_el(sun_az, sun_el)
    bright_vec = _normalized(tuple(sun_vec[i] - (_dot(sun_vec, moon_vec) * moon_vec[i]) for i in range(3)))
    if bright_vec is None:
        return None

    zenith = (0.0, 0.0, 1.0)
    screen_up = _normalized(tuple(zenith[i] - (_dot(zenith, moon_vec) * moon_vec[i]) for i in range(3)))
    if screen_up is None:
        north = (0.0, 1.0, 0.0)
        screen_up = _normalized(tuple(north[i] - (_dot(north, moon_vec) * moon_vec[i]) for i in range(3)))
    if screen_up is None:
        return None

    screen_right = _normalized(_cross(moon_vec, screen_up))
    if screen_right is None:
        return None

    canvas_x = -_dot(bright_vec, screen_right)
    canvas_y = _dot(bright_vec, screen_up)
    return (math.degrees(math.atan2(canvas_y, canvas_x)) + 360.0) % 360.0


def get_astro_payload(*, config: BiodynamicConfig | None = None, target_date: date | None = None) -> dict[str, object]:
    resolved = _require_config(config)
    tzinfo = ZoneInfo(resolved.timezone_name)
    now_local = datetime.now(tzinfo)
    summary_date = target_date or now_local.date()
    out: dict[str, object] = {
        "ok": False,
        "lat": round(float(resolved.latitude), 6),
        "lon": round(float(resolved.longitude), 6),
        "tz": resolved.timezone_name,
        "date": summary_date.isoformat(),
        "timestamp": now_local.isoformat(),
        "current_time": now_local.strftime("%H:%M"),
        "current_minutes": round((now_local.hour * 60) + now_local.minute + (now_local.second / 60.0), 2),
        "sunrise": "",
        "sunset": "",
        "sun_noon": "",
        "sun_points": [],
        "moon_points": [],
        "sun_altitude_now": None,
        "sun_azimuth_now": None,
        "moon_phase_value": None,
        "moon_phase_label": "",
        "moon_lit_pct": None,
        "moon_rise": "",
        "moon_set": "",
        "moon_rise_today": "",
        "moon_set_today": "",
        "moon_declination": None,
        "moon_position_source": "",
        "moon_next_full": "",
        "moon_next_phase_label": "",
        "moon_next_phase_date": "",
        "moon_visible_angle": None,
        "moon_reference_angle": None,
        "position_29d": [],
    }
    if (
        LocationInfo is None
        or _astral_sun is None
        or _astral_elevation is None
        or _astral_azimuth is None
        or _astral_moon is None
        or _astral_lmst is None
    ):
        out["reason"] = "astral_unavailable"
        return out

    try:
        summary_local = now_local if summary_date == now_local.date() else datetime.combine(summary_date, now_local.time(), tzinfo=tzinfo)
        obs = LocationInfo(
            name="biodynamic-calendar",
            region="local",
            timezone=resolved.timezone_name,
            latitude=resolved.latitude,
            longitude=resolved.longitude,
        ).observer

        sun_map = _astral_sun(obs, date=summary_date, tzinfo=tzinfo)
        sunrise = sun_map.get("sunrise")
        sunset = sun_map.get("sunset")
        noon = sun_map.get("noon")
        if not isinstance(sunrise, datetime) or not isinstance(sunset, datetime):
            out["reason"] = "sun_events_unavailable"
            return out

        day_start = datetime.combine(summary_date, time.min, tzinfo=tzinfo)
        moon_val = float(_astral_moon.phase(summary_date))
        moon_lit_pct = int(round((0.5 * (1 - math.cos((2 * math.pi * (moon_val % 28.0)) / 28.0))) * 100))
        sun_points = [
            {
                "m": step * 30,
                "t": probe.strftime("%H:%M"),
                "e": round(float(_astral_elevation(obs, probe)), 2),
            }
            for step in range(49)
            for probe in (day_start + timedelta(minutes=step * 30),)
        ]

        moon_points: list[dict[str, object]] = []
        moon_declination: float | None = None
        moon_position_source = ""
        try:
            _, ts, eph, _constellation_at = _skyfield_runtime()
            from skyfield.api import wgs84

            topo = wgs84.latlon(float(resolved.latitude), float(resolved.longitude))
            observer_sf = eph["earth"] + topo
            moon_body = eph["moon"]
            for minute in range(0, 1441, 10):
                sample_dt = day_start + timedelta(minutes=minute)
                t = ts.from_datetime(sample_dt.astimezone(timezone.utc))
                apparent = observer_sf.at(t).observe(moon_body).apparent()
                alt, az, _distance = apparent.altaz()
                _ra, dec, _radec_distance = apparent.radec()
                elev = float(alt.degrees)
                azimuth = float(az.degrees)
                declination = float(dec.degrees)
                if all(math.isfinite(v) for v in (elev, azimuth, declination)):
                    moon_points.append(
                        {
                            "m": minute,
                            "t": (day_start + timedelta(minutes=minute)).strftime("%H:%M"),
                            "e": round(elev, 2),
                            "az": round(azimuth, 2),
                            "d": round(declination, 2),
                        }
                    )
            now_t = ts.from_datetime(summary_local.astimezone(timezone.utc))
            now_apparent = observer_sf.at(now_t).observe(moon_body).apparent()
            _now_ra, now_dec, _now_dist = now_apparent.radec()
            now_declination = float(now_dec.degrees)
            if math.isfinite(now_declination):
                moon_declination = round(now_declination, 2)
            if moon_points:
                moon_position_source = "skyfield"
        except Exception:
            moon_points = []
            moon_declination = None
            moon_position_source = ""
        if not moon_points:
            try:
                moon_az_fn = getattr(_astral_moon, "azimuth", None)
                moon_el_fn = getattr(_astral_moon, "elevation", None)
                if callable(moon_az_fn) and callable(moon_el_fn):
                    for minute in range(0, 1441, 10):
                        sample_dt = day_start + timedelta(minutes=minute)
                        sample_utc = sample_dt.astimezone(timezone.utc)
                        elev = float(moon_el_fn(obs, sample_utc))
                        azimuth = float(moon_az_fn(obs, sample_utc))
                        if all(math.isfinite(v) for v in (elev, azimuth)):
                            moon_points.append(
                                {
                                    "m": minute,
                                    "t": sample_dt.strftime("%H:%M"),
                                    "e": round(elev, 2),
                                    "az": round(azimuth, 2),
                                }
                            )
                if moon_points:
                    moon_position_source = "astral"
            except Exception:
                moon_points = []
                moon_position_source = ""

        moon_visible_angle = None
        moon_reference_angle = None
        try:
            moon_az_fn = getattr(_astral_moon, "azimuth", None)
            moon_el_fn = getattr(_astral_moon, "elevation", None)
            moon_az = float(moon_az_fn(obs, summary_local)) if callable(moon_az_fn) else float("nan")
            moon_el = float(moon_el_fn(obs, summary_local)) if callable(moon_el_fn) else float("nan")
            sun_az = float(_astral_azimuth(obs, summary_local))
            sun_el = float(_astral_elevation(obs, summary_local))
            moon_obs_dt = summary_local.astimezone(timezone.utc)
            moon_pos = _astral_moon.moon_position(_astral_moon.julianday_2000(moon_obs_dt))
            moon_ra = float(moon_pos.right_ascension)
            moon_dec = float(moon_pos.declination)

            if all(math.isfinite(v) for v in (moon_az, moon_el, sun_az, sun_el)):
                lat_rad = math.radians(float(resolved.latitude))
                moon_az_rad = math.radians(moon_az)
                moon_el_rad = math.radians(moon_el)
                sun_az_rad = math.radians(sun_az)
                sun_el_rad = math.radians(sun_el)

                sin_sun_dec = (
                    (math.sin(sun_el_rad) * math.sin(lat_rad))
                    + (math.cos(sun_el_rad) * math.cos(lat_rad) * math.cos(sun_az_rad))
                )
                sun_dec = math.asin(max(-1.0, min(1.0, sin_sun_dec)))
                sun_hour_angle = math.atan2(
                    -math.sin(sun_az_rad) * math.cos(sun_el_rad),
                    (math.sin(sun_el_rad) * math.cos(lat_rad))
                    - (math.cos(sun_el_rad) * math.sin(lat_rad) * math.cos(sun_az_rad)),
                )
                lst_rad = math.radians(float(_astral_lmst(summary_local, float(resolved.longitude))))
                sun_ra = (lst_rad - sun_hour_angle) % (2 * math.pi)

                chi_num = math.cos(sun_dec) * math.sin(sun_ra - moon_ra)
                chi_den = (
                    (math.sin(sun_dec) * math.cos(moon_dec))
                    - (math.cos(sun_dec) * math.sin(moon_dec) * math.cos(sun_ra - moon_ra))
                )
                bright_limb_angle = math.degrees(math.atan2(chi_num, chi_den)) % 360.0

                parallactic_angle = math.degrees(
                    math.atan2(
                        math.sin(moon_az_rad),
                        (math.tan(lat_rad) * math.cos(moon_el_rad))
                        - (math.sin(moon_el_rad) * math.cos(moon_az_rad)),
                    )
                )

                moon_reference_angle = round(bright_limb_angle, 2)
                local_canvas_angle = _moon_local_canvas_angle(moon_az, moon_el, sun_az, sun_el)
                if local_canvas_angle is not None:
                    moon_visible_angle = round(local_canvas_angle, 2)
                else:
                    moon_visible_angle = round((bright_limb_angle + parallactic_angle) % 360.0, 2)
        except Exception:
            moon_visible_angle = None
            moon_reference_angle = None

        def _event_for_day(fn, event_date: date) -> str:
            if not callable(fn):
                return ""
            try:
                ev = fn(obs, date=event_date, tzinfo=tzinfo)
            except TypeError:
                try:
                    ev = fn(obs, event_date, tzinfo=tzinfo)
                except Exception:
                    return ""
            except Exception:
                return ""
            if not isinstance(ev, datetime):
                return ""
            if ev.tzinfo is None:
                ev = ev.replace(tzinfo=tzinfo)
            else:
                ev = ev.astimezone(tzinfo)
            return ev.strftime("%H:%M") if ev.date() == event_date else ""

        def _pick_nearest_event(fn) -> str:
            if not callable(fn):
                return ""
            candidates: list[datetime] = []
            for offset in (-1, 0, 1):
                try:
                    ev = fn(obs, date=summary_date + timedelta(days=offset), tzinfo=tzinfo)
                except TypeError:
                    try:
                        ev = fn(obs, summary_date + timedelta(days=offset), tzinfo=tzinfo)
                    except Exception:
                        continue
                except Exception:
                    continue
                if isinstance(ev, datetime):
                    if ev.tzinfo is None:
                        candidates.append(ev.replace(tzinfo=tzinfo))
                    else:
                        candidates.append(ev.astimezone(tzinfo))
            if not candidates:
                return ""
            same_day = [ev for ev in candidates if ev.date() == summary_date]
            if same_day:
                return min(same_day).strftime("%H:%M")
            center = datetime.combine(summary_date, time.min, tzinfo=tzinfo)
            chosen = min(candidates, key=lambda ev: abs((ev - center).total_seconds()))
            return chosen.strftime("%H:%M")

        moon_rise_fn = getattr(_astral_moon, "moonrise", None)
        moon_set_fn = getattr(_astral_moon, "moonset", None)
        moon_rise_today = _event_for_day(moon_rise_fn, summary_date)
        moon_set_today = _event_for_day(moon_set_fn, summary_date)
        moon_rise = _pick_nearest_event(moon_rise_fn)
        moon_set = _pick_nearest_event(moon_set_fn)

        moon_next_full = ""
        try:
            nf_fn = getattr(_astral_moon, "next_full_moon", None)
            nf = nf_fn(summary_date) if callable(nf_fn) else None
            if isinstance(nf, datetime):
                moon_next_full = nf.date().isoformat()
            elif hasattr(nf, "isoformat"):
                moon_next_full = str(nf.isoformat())[:10]
        except Exception:
            moon_next_full = ""
        if not moon_next_full:
            for day_offset in range(1, 32):
                probe = summary_date + timedelta(days=day_offset)
                try:
                    phase_val = float(_astral_moon.phase(probe))
                except Exception:
                    continue
                dist = abs((phase_val % 28.0) - 14.0)
                if min(dist, 28.0 - dist) <= 0.6:
                    moon_next_full = probe.isoformat()
                    break

        moon_next_phase_label = ""
        moon_next_phase_date = ""
        try:
            phase_targets = (
                ("New Moon", 0.0),
                ("1st Quarter", 7.0),
                ("Full Moon", 14.0),
                ("3rd Quarter", 21.0),
            )
            phase_cycle = 28.0
            current_phase = moon_val % phase_cycle
            for label, target in phase_targets:
                if current_phase < target:
                    moon_next_phase_label = label
                    break
            if not moon_next_phase_label:
                moon_next_phase_label = "New Moon"
            target_phase = next(target for label, target in phase_targets if label == moon_next_phase_label)

            best_date = None
            best_key = None
            for day_offset in range(0, 17):
                probe = summary_date + timedelta(days=day_offset)
                try:
                    phase_val = float(_astral_moon.phase(probe)) % phase_cycle
                except Exception:
                    continue
                dist = abs(phase_val - target_phase)
                dist = min(dist, phase_cycle - dist)
                candidate_key = (dist, day_offset)
                if best_key is None or candidate_key < best_key:
                    best_key = candidate_key
                    best_date = probe
            if best_date is not None:
                moon_next_phase_date = best_date.isoformat()
                if moon_next_phase_label == "Full Moon":
                    moon_next_phase_label = _traditional_full_moon_name(best_date)
        except Exception:
            moon_next_phase_label = ""
            moon_next_phase_date = ""

        position_29d: list[dict[str, object]] = []
        try:
            sample_minutes = range(0, 1441, 120)
            position_ts = None
            position_observer = None
            position_moon_body = None
            try:
                _, position_ts, position_eph, _constellation_at = _skyfield_runtime()
                from skyfield.api import wgs84

                topo = wgs84.latlon(float(resolved.latitude), float(resolved.longitude))
                position_observer = position_eph["earth"] + topo
                position_moon_body = position_eph["moon"]
            except Exception:
                position_ts = None
                position_observer = None
                position_moon_body = None

            moon_el_fn = getattr(_astral_moon, "elevation", None)
            for day_offset in range(29):
                graph_day_start = day_start + timedelta(days=day_offset)
                graph_date = graph_day_start.date()
                sun_day: list[list[float | int]] = []
                moon_day: list[list[float | int]] = []
                for minute in sample_minutes:
                    sample_dt = graph_day_start + timedelta(minutes=minute)
                    try:
                        sun_elev = float(_astral_elevation(obs, sample_dt))
                    except Exception:
                        sun_elev = float("nan")
                    if math.isfinite(sun_elev):
                        sun_day.append([minute, round(sun_elev, 2)])

                    moon_elev = float("nan")
                    try:
                        if position_ts is not None and position_observer is not None and position_moon_body is not None:
                            t = position_ts.from_datetime(sample_dt.astimezone(timezone.utc))
                            apparent = position_observer.at(t).observe(position_moon_body).apparent()
                            alt, _az, _distance = apparent.altaz()
                            moon_elev = float(alt.degrees)
                        elif callable(moon_el_fn):
                            moon_elev = float(moon_el_fn(obs, sample_dt.astimezone(timezone.utc)))
                    except Exception:
                        moon_elev = float("nan")
                    if math.isfinite(moon_elev):
                        moon_day.append([minute, round(moon_elev, 2)])

                try:
                    graph_moon_phase = float(_astral_moon.phase(graph_date))
                    graph_moon_lit_pct = int(
                        round((0.5 * (1 - math.cos((2 * math.pi * (graph_moon_phase % 28.0)) / 28.0))) * 100)
                    )
                except Exception:
                    graph_moon_phase = None
                    graph_moon_lit_pct = None

                graph_moon_visible_angle = None
                try:
                    moon_az_fn = getattr(_astral_moon, "azimuth", None)
                    moon_el_fn_for_angle = getattr(_astral_moon, "elevation", None)
                    graph_moon_dt = graph_day_start.astimezone(timezone.utc)
                    graph_moon_az = float(moon_az_fn(obs, graph_moon_dt)) if callable(moon_az_fn) else float("nan")
                    graph_moon_el = (
                        float(moon_el_fn_for_angle(obs, graph_moon_dt))
                        if callable(moon_el_fn_for_angle)
                        else float("nan")
                    )
                    graph_sun_az = float(_astral_azimuth(obs, graph_day_start))
                    graph_sun_el = float(_astral_elevation(obs, graph_day_start))
                    graph_angle = _moon_local_canvas_angle(graph_moon_az, graph_moon_el, graph_sun_az, graph_sun_el)
                    if graph_angle is not None:
                        graph_moon_visible_angle = round(graph_angle, 2)
                except Exception:
                    graph_moon_visible_angle = None

                position_29d.append(
                    {
                        "date": graph_date.isoformat(),
                        "label": graph_day_start.strftime("%b%d"),
                        "sun": sun_day,
                        "moon": moon_day,
                        "moon_phase_value": round(graph_moon_phase, 2) if graph_moon_phase is not None else None,
                        "moon_lit_pct": graph_moon_lit_pct,
                        "moon_visible_angle": graph_moon_visible_angle,
                    }
                )
        except Exception:
            position_29d = []

        out.update(
            {
                "ok": True,
                "sunrise": sunrise.strftime("%H:%M"),
                "sunset": sunset.strftime("%H:%M"),
                "sun_noon": noon.strftime("%H:%M") if isinstance(noon, datetime) else "",
                "sun_points": sun_points,
                "moon_points": moon_points,
                "sun_altitude_now": round(float(_astral_elevation(obs, summary_local)), 2),
                "sun_azimuth_now": round(float(_astral_azimuth(obs, summary_local)), 2),
                "moon_phase_value": round(moon_val, 2),
                "moon_phase_label": _moon_phase_name(moon_val, summary_date),
                "moon_lit_pct": moon_lit_pct,
                "moon_rise": moon_rise,
                "moon_set": moon_set,
                "moon_rise_today": moon_rise_today,
                "moon_set_today": moon_set_today,
                "moon_declination": moon_declination,
                "moon_position_source": moon_position_source,
                "moon_next_full": moon_next_full,
                "moon_next_phase_label": moon_next_phase_label,
                "moon_next_phase_date": moon_next_phase_date,
                "moon_visible_angle": moon_visible_angle,
                "moon_reference_angle": moon_reference_angle,
                "position_29d": position_29d,
            }
        )
        return out
    except Exception as exc:
        out["reason"] = str(exc) or exc.__class__.__name__
        return out


def get_daily_summary(
    summary_date: date,
    *,
    config: BiodynamicConfig | None = None,
    crop_stage: str | None = None,
    plant_state: dict | None = None,
    plantings: list[dict[str, object]] | None = None,
) -> str:
    resolved = _require_config(config)
    payload = get_biodynamic_payload(summary_date, config=resolved)
    biodynamic_day = next(
        (row for row in (payload.get("calendar") or []) if isinstance(row, dict) and row.get("date") == summary_date.isoformat()),
        None,
    )

    astral = get_astro_payload(config=resolved, target_date=summary_date)
    astral_lines = ["Astral Notes"]
    if not astral.get("ok"):
        astral_lines.append("Astral data unavailable.")
    else:
        if astral.get("sunrise"):
            astral_lines.append(f"Sunrise: {astral['sunrise']}")
        if astral.get("sunset"):
            astral_lines.append(f"Sunset: {astral['sunset']}")
        if astral.get("sun_noon"):
            astral_lines.append(f"Solar Noon: {astral['sun_noon']}")
        if astral.get("moon_phase_label"):
            astral_lines.append(f"Moon Phase: {astral['moon_phase_label']} ({astral.get('moon_lit_pct', '--')}% lit)")
        if astral.get("moon_rise"):
            astral_lines.append(f"Moonrise: {astral['moon_rise']}")
        if astral.get("moon_set"):
            astral_lines.append(f"Moonset: {astral['moon_set']}")

    day_lines = ["Selected Day"]
    day_lines.append(f"Date: {summary_date.strftime('%A, %B')} {summary_date.day}, {summary_date.year}")

    if not payload.get("ok"):
        astral_lines.append(f"Biodynamic: unavailable ({payload.get('reason') or 'unavailable'})")
    elif not biodynamic_day:
        astral_lines.append("Biodynamic: unavailable for selected date.")
    else:
        sign = str(biodynamic_day.get("dominant_sign") or "--")
        element = str(biodynamic_day.get("dominant_element") or "--")
        part = str(biodynamic_day.get("dominant_plant_part") or "--")
        astral_lines.append(f"Biodynamic: {sign} Moon | {element} / {part}")
        day_lines.append(f"Zodiac Moon: {sign}")
        day_lines.append(f"Element / Plant Part: {element} / {part}")
        if biodynamic_day.get("moon_direction"):
            day_lines.append(f"Moon Direction: {biodynamic_day['moon_direction']}")
        segments = list(biodynamic_day.get("segments") or [])
        if segments:
            first = segments[0]
            astral_lines.append(f"Current Window: {first.get('start', '--')} to {first.get('end', '--')}")
            transitions = [f"{seg.get('start', '--')} {seg.get('sign', '--')}" for seg in segments[1:3] if isinstance(seg, dict)]
            if transitions:
                astral_lines.append(f"Transitions: {' | '.join(transitions)}")
            day_lines.append("Sign Windows:")
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                label = str(seg.get("off_label") or seg.get("sign") or "--")
                detail = str(seg.get("plant_part") or "")
                suffix = f" ({detail})" if detail and detail != "Rest" else ""
                day_lines.append(f"- {seg.get('start', '--')} to {seg.get('end', '--')}: {label}{suffix}")
        events = [ev for ev in list(biodynamic_day.get("lunar_events") or []) if isinstance(ev, dict)]
        if events:
            day_lines.append("Lunar Events:")
            for ev in events:
                day_lines.append(f"- {ev.get('label', 'Event')}: {ev.get('start', '--')} to {ev.get('end', '--')}")
        flags = [
            label
            for key, label in (("lunar_node", "Lunar node"), ("perigee", "Perigee"), ("apogee", "Apogee"))
            if _truthy(biodynamic_day.get(key))
        ]
        if flags:
            day_lines.append(f"Flags: {', '.join(flags)}")

    parts = [
        "\n".join(get_hint_lines_for_day(biodynamic_day, crop_stage=crop_stage, plant_state=plant_state, plantings=plantings)),
        "\n".join(day_lines),
        "\n".join(astral_lines),
    ]
    return "\n\n".join(part for part in parts if part.strip())


def get_biodynamic_payload(target_date: date | None = None, *, config: BiodynamicConfig | None = None) -> dict[str, object]:
    resolved = _require_config(config)
    tzinfo = ZoneInfo(resolved.timezone_name)
    now_local = datetime.now(tzinfo)
    month_anchor = target_date or now_local.date()
    payload = _empty_payload(month_anchor)
    payload["ephemeris"] = ephemeris_status()

    cache_key = (
        month_anchor.replace(day=1).isoformat(),
        str(round(float(resolved.latitude), 4)),
        str(round(float(resolved.longitude), 4)),
        resolved.timezone_name,
    )
    now_mono = time_mod.monotonic()
    cached = _PAYLOAD_CACHE.get(cache_key)
    cached_current_date = str((cached[1].get("current") or {}).get("timestamp") or "")[:10] if cached else ""
    if cached and cached[0] > now_mono and cached_current_date == now_local.date().isoformat():
        return dict(cached[1])

    try:
        _, ts, eph, constellation_at = _skyfield_runtime()
    except Exception as exc:
        payload["reason"] = str(exc) or exc.__class__.__name__
        return payload

    try:
        month_days, _month_segments = _build_calendar(month_anchor, tzinfo, ts, eph, constellation_at, now_local)
        timeline = _build_segment_timeline(month_days, tzinfo)
        current_timeline = timeline
        current_segment = next((segment for segment in timeline if segment["start_local"] <= now_local < segment["end_local"]), None)
        if current_segment is None:
            current_timeline = _build_current_segment_timeline(now_local, tzinfo, ts, eph, constellation_at)
            current_segment = next(
                (segment for segment in current_timeline if segment["start_local"] <= now_local < segment["end_local"]),
                None,
            )
        upcoming: list[dict[str, object]] = []
        for segment in current_timeline:
            if segment["start_local"] <= now_local:
                continue
            upcoming.append(
                {
                    "starts_at": segment["start_local"].isoformat(),
                    "start_hm": segment["start_hm"],
                    "sign": segment["sign"],
                    "element": segment["element"],
                    "plant_part": segment["plant_part"],
                    "color": segment["color"],
                    "accent": segment["accent"],
                    "kind": segment["kind"],
                    "off_kind": segment["off_kind"],
                    "off_label": segment["off_label"],
                }
            )
            if len(upcoming) >= 3:
                break
        payload.update(
            {
                "ok": True,
                "reason": "",
                "tz": resolved.timezone_name,
                "lat": round(float(resolved.latitude), 6),
                "lon": round(float(resolved.longitude), 6),
                "month_label": month_anchor.strftime("%B %Y"),
                "current": {
                    "timestamp": now_local.isoformat(),
                    "sign": str(current_segment.get("sign") or "") if current_segment else "",
                    "element": str(current_segment.get("element") or "") if current_segment else "",
                    "plant_part": str(current_segment.get("plant_part") or "") if current_segment else "",
                    "color": str(current_segment.get("color") or "") if current_segment else "",
                    "accent": str(current_segment.get("accent") or "") if current_segment else "",
                    "kind": str(current_segment.get("kind") or "") if current_segment else "",
                    "off_kind": str(current_segment.get("off_kind") or "") if current_segment else "",
                    "off_label": str(current_segment.get("off_label") or "") if current_segment else "",
                    "moon_direction": _moon_direction(now_local, ts, eph),
                    "window_start": current_segment["start_local"].isoformat() if current_segment else "",
                    "window_end": current_segment["end_local"].isoformat() if current_segment else "",
                    "window_start_hm": str(current_segment.get("start_hm") or "") if current_segment else "",
                    "window_end_hm": str(current_segment.get("end_hm") or "") if current_segment else "",
                    "calendar_basis": "moon apparent position classified against fixed-star constellation boundaries",
                },
                "upcoming": upcoming,
                "calendar": month_days,
                "ephemeris": ephemeris_status(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _PAYLOAD_CACHE[cache_key] = (now_mono + _PAYLOAD_CACHE_TTL_SEC, dict(payload))
        return payload
    except Exception as exc:
        payload["reason"] = str(exc) or exc.__class__.__name__
        return payload


def _add_months(month_anchor: date, offset: int) -> date:
    zero_based = (month_anchor.year * 12) + (month_anchor.month - 1) + offset
    year = zero_based // 12
    month = (zero_based % 12) + 1
    return date(year, month, 1)


def get_biodynamic_calendar_range(
    start_month: date | None = None,
    months: int = 13,
    *,
    config: BiodynamicConfig | None = None,
) -> dict[str, object]:
    resolved = _require_config(config)
    month_count = max(1, min(int(months or 13), 36))
    anchor = (start_month or get_biodynamic_local_now(resolved).date()).replace(day=1)
    month_payloads = [
        get_biodynamic_payload(_add_months(anchor, offset), config=resolved)
        for offset in range(month_count)
    ]
    ok = bool(month_payloads) and all(bool(month.get("ok")) for month in month_payloads)
    first_error = next((str(month.get("reason") or "") for month in month_payloads if not month.get("ok")), "")
    return {
        "ok": ok,
        "reason": "" if ok else (first_error or "unavailable"),
        "lat": round(float(resolved.latitude), 6),
        "lon": round(float(resolved.longitude), 6),
        "tz": resolved.timezone_name,
        "source": "skyfield",
        "start_month": anchor.strftime("%Y-%m"),
        "months_requested": month_count,
        "months": month_payloads,
        "ephemeris": ephemeris_status(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

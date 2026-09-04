import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from importlib import import_module
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from biodynamic_calendar import BiodynamicConfig, get_astro_payload, get_biodynamic_local_now
from biodynamic_calendar import core
from biodynamic_calendar.core import _moon_phase_name
from biodynamic_calendar_app import __main__ as server_main

app_module = import_module("biodynamic_calendar_app.app")


def test_get_biodynamic_local_now_uses_config_timezone():
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    now = get_biodynamic_local_now(cfg)
    assert now.tzinfo is not None
    assert getattr(now.tzinfo, "key", "") == "America/Denver"


def test_payload_cache_is_bounded_and_returns_defensive_copies(monkeypatch):
    monkeypatch.setattr(core, "_PAYLOAD_CACHE_MAX", 2)
    now_mono = 100.0
    today = "2026-09-04"

    def key(index):
        return (f"2026-{index:02d}-01", "39.7392", "-104.9903", "America/Denver")

    def payload(index):
        return {
            "ok": True,
            "current": {"timestamp": f"{today}T12:00:00-06:00"},
            "calendar": [{"date": f"2026-{index:02d}-01"}],
        }

    with core._PAYLOAD_CACHE_LOCK:
        core._PAYLOAD_CACHE.clear()
    try:
        core._payload_cache_set(key(1), payload(1), now_monotonic=now_mono)
        core._payload_cache_set(key(2), payload(2), now_monotonic=now_mono)
        first = core._payload_cache_get(key(1), now_monotonic=now_mono, current_date=today)
        first["calendar"][0]["date"] = "contaminated"

        clean = core._payload_cache_get(key(1), now_monotonic=now_mono, current_date=today)
        assert clean["calendar"][0]["date"] == "2026-01-01"

        core._payload_cache_set(key(3), payload(3), now_monotonic=now_mono)
        assert len(core._PAYLOAD_CACHE) == 2
        assert core._payload_cache_get(key(2), now_monotonic=now_mono, current_date=today) is None
        assert core._payload_cache_get(key(1), now_monotonic=now_mono, current_date=today) is not None

        core._payload_cache_set(key(4), payload(4), now_monotonic=now_mono)
        assert core._payload_cache_get(
            key(4),
            now_monotonic=now_mono + core._PAYLOAD_CACHE_TTL_SEC + 1,
            current_date=today,
        ) is None
    finally:
        with core._PAYLOAD_CACHE_LOCK:
            core._PAYLOAD_CACHE.clear()


def test_public_payload_cache_cannot_be_mutated_by_callers():
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    today = datetime.now(ZoneInfo(cfg.timezone_name)).date()
    anchor = today.replace(day=1)
    key = (
        anchor.isoformat(),
        str(round(float(cfg.latitude), 4)),
        str(round(float(cfg.longitude), 4)),
        cfg.timezone_name,
    )
    payload = {
        "ok": True,
        "current": {"timestamp": datetime.now(ZoneInfo(cfg.timezone_name)).isoformat()},
        "calendar": [{"date": "clean"}],
    }

    with core._PAYLOAD_CACHE_LOCK:
        core._PAYLOAD_CACHE.clear()
    try:
        core._payload_cache_set(key, payload, now_monotonic=core.time_mod.monotonic())
        first = core.get_biodynamic_payload(anchor, config=cfg)
        first["calendar"][0]["date"] = "contaminated"
        second = core.get_biodynamic_payload(anchor, config=cfg)
        assert second["calendar"][0]["date"] == "clean"
    finally:
        with core._PAYLOAD_CACHE_LOCK:
            core._PAYLOAD_CACHE.clear()


def test_payload_cache_supports_concurrent_access(monkeypatch):
    monkeypatch.setattr(core, "_PAYLOAD_CACHE_MAX", 16)
    today = "2026-09-04"

    def exercise(index):
        key = (f"2026-{(index % 12) + 1:02d}-01", str(index % 4), "0", "UTC")
        payload = {
            "current": {"timestamp": f"{today}T12:00:00+00:00"},
            "calendar": [{"index": index}],
        }
        core._payload_cache_set(key, payload, now_monotonic=100.0)
        return core._payload_cache_get(key, now_monotonic=100.0, current_date=today)

    with core._PAYLOAD_CACHE_LOCK:
        core._PAYLOAD_CACHE.clear()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(exercise, range(100)))
        assert any(result is not None for result in results)
        assert len(core._PAYLOAD_CACHE) <= 16
    finally:
        with core._PAYLOAD_CACHE_LOCK:
            core._PAYLOAD_CACHE.clear()


def test_astro_payload_includes_configured_location_now():
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    payload = get_astro_payload(config=cfg)
    assert payload["tz"] == "America/Denver"
    assert payload["timestamp"]
    assert payload["current_time"]
    assert 0 <= float(payload["current_minutes"]) <= 1440
    assert payload["next_sunrise"]
    timeline_start = datetime.fromisoformat(str(payload["timeline_start_at"]))
    timeline_sunset = datetime.fromisoformat(str(payload["timeline_sunset_at"]))
    timeline_end = datetime.fromisoformat(str(payload["timeline_end_at"]))
    assert timeline_start < timeline_sunset < timeline_end
    for event_key in ("timeline_moonrise_at", "timeline_moonset_at"):
        if payload[event_key]:
            assert timeline_start <= datetime.fromisoformat(str(payload[event_key])) <= timeline_end
    assert isinstance(payload["moon_points"], list)
    assert isinstance(payload["position_29d"], list)
    assert len(payload["position_29d"]) == 29
    assert {"date", "sun", "moon", "moon_phase_value"}.issubset(payload["position_29d"][0])
    assert 0 <= float(payload["moon_bright_limb_angle"]) < 360
    assert 0 <= float(payload["moon_disk_rotation"]) < 360
    assert isinstance(payload["moon_altitude_now"], float)
    assert len(payload["moon_phase_cycle"]) == 8
    assert all({"bright_limb_angle", "disk_rotation", "representative_date"}.issubset(item) for item in payload["moon_phase_cycle"])
    observed_date = date.fromisoformat(str(payload["date"]))
    phase_dates = [date.fromisoformat(str(item["representative_date"])) for item in payload["moon_phase_cycle"]]
    assert phase_dates == sorted(phase_dates)
    assert all(phase_date < observed_date for phase_date in phase_dates[:4])
    assert all(phase_date > observed_date for phase_date in phase_dates[4:])
    full_moons = [item for item in payload["moon_phase_cycle"] if item["index"] == 4]
    assert full_moons and all(item["name"] != "Full Moon" for item in full_moons)


def test_lunar_orientation_uses_utc_normalization_and_clockwise_from_zenith():
    local_time = datetime(2026, 8, 17, 12, 0, tzinfo=ZoneInfo("America/Denver"))

    normalized = core._astral_moon_time(local_time)
    bright_angle = core._moon_local_bright_limb_angle(140.0, 35.0, 250.0, -10.0)
    legacy_canvas_angle = core._moon_local_canvas_angle(140.0, 35.0, 250.0, -10.0)

    assert normalized == datetime(2026, 8, 17, 18, 0)
    assert normalized.tzinfo is None
    assert round(bright_angle, 3) == 86.849
    assert round((legacy_canvas_angle - bright_angle) % 360, 3) == 90.0


def test_full_moon_phase_uses_traditional_month_name():
    assert _moon_phase_name(14.0, date(2026, 1, 3)) == "Wolf Moon"
    assert _moon_phase_name(14.0, date(2026, 6, 29)) == "Strawberry Moon"
    assert _moon_phase_name(14.0, date(2026, 10, 25)) == "Hunter's Moon"
    assert _moon_phase_name(14.0) == "Full Moon"


def test_next_new_moon_uses_immediate_lunation_window():
    cfg = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")
    payload = get_astro_payload(config=cfg, target_date=date(2026, 6, 13))
    assert payload["moon_phase_label"] == "Waning Crescent"
    assert payload["moon_next_phase_label"] == "New Moon"
    assert payload["moon_next_phase_date"] == "2026-06-15"


def test_lunar_timeline_surrounds_selected_date_chronologically():
    cfg = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")
    selected = date(2026, 8, 18)
    phases = get_astro_payload(config=cfg, target_date=selected)["moon_phase_cycle"]

    phase_dates = [date.fromisoformat(str(item["representative_date"])) for item in phases]
    assert len(phase_dates) == 8
    assert phase_dates == sorted(phase_dates)
    assert all(phase_date < selected for phase_date in phase_dates[:4])
    assert all(phase_date > selected for phase_date in phase_dates[4:])
    assert any(item["name"] == "Sturgeon Moon" for item in phases)


def test_lunar_event_timeline_runs_from_sunrise_to_next_sunrise():
    cfg = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")
    payload = get_astro_payload(config=cfg, target_date=date(2026, 8, 18))

    start = datetime.fromisoformat(str(payload["timeline_start_at"]))
    sunset = datetime.fromisoformat(str(payload["timeline_sunset_at"]))
    end = datetime.fromisoformat(str(payload["timeline_end_at"]))
    moonrise = datetime.fromisoformat(str(payload["timeline_moonrise_at"]))
    moonset = datetime.fromisoformat(str(payload["timeline_moonset_at"]))

    assert start.date() == date(2026, 8, 18)
    assert end.date() == date(2026, 8, 19)
    assert start < moonrise < sunset < moonset < end
    assert payload["timeline_moonrise"] == moonrise.strftime("%H:%M")
    assert payload["timeline_moonset"] == moonset.strftime("%H:%M")


def test_ephemeris_status_uses_explicit_skyfield_dir(monkeypatch, tmp_path):
    skyfield_dir = tmp_path / "skyfield"
    monkeypatch.setenv("BIODYNAMIC_SKYFIELD_DIR", str(skyfield_dir))

    status = core.ephemeris_status()

    assert status["source"] == "env"
    assert status["data_dir"] == str(skyfield_dir.resolve())
    assert status["path"] == str((skyfield_dir / "de421.bsp").resolve())
    assert status["cache_path"] == str((skyfield_dir / "de421.bsp").resolve())
    assert status["installed"] is False


def test_ephemeris_status_prefers_user_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("BIODYNAMIC_SKYFIELD_DIR", raising=False)
    cache_dir = tmp_path / "cache" / "biodynamic_calendar" / "skyfield"
    monkeypatch.setattr(core, "_platform_cache_dir", lambda: cache_dir)
    bundled_dir = tmp_path / "bundled"
    monkeypatch.setattr(core, "_bundled_skyfield_data_dir", lambda: bundled_dir)
    cache_file = cache_dir / "de421.bsp"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cached", encoding="utf-8")

    status = core.ephemeris_status()

    assert status["source"] == "cache"
    assert status["path"] == str(cache_file.resolve())
    assert status["installed"] is True


def test_ephemeris_status_uses_bundled_file_when_cache_is_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("BIODYNAMIC_SKYFIELD_DIR", raising=False)
    cache_dir = tmp_path / "cache" / "biodynamic_calendar" / "skyfield"
    monkeypatch.setattr(core, "_platform_cache_dir", lambda: cache_dir)
    bundled_dir = tmp_path / "bundled"
    bundled_file = bundled_dir / "de421.bsp"
    bundled_dir.mkdir()
    bundled_file.write_text("bundled", encoding="utf-8")
    monkeypatch.setattr(core, "_bundled_skyfield_data_dir", lambda: bundled_dir)

    status = core.ephemeris_status()

    assert status["source"] == "bundled"
    assert status["data_dir"] == str(bundled_dir)
    assert status["path"] == str(bundled_file)
    assert status["cache_path"] == str((cache_dir / "de421.bsp").resolve())
    assert status["installed"] is True


def test_server_launcher_defaults_to_all_interfaces(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server_main.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    server_main.main([])

    assert calls == [
        (
            "biodynamic_calendar_app:app",
            {"host": "0.0.0.0", "port": 8765, "reload": False},
        )
    ]
    output = capsys.readouterr().out
    assert "BD Calendar is starting on all network interfaces." in output
    assert "Browse on this computer: http://127.0.0.1:8765" in output
    assert "Browse from another device: http://<this-computer-ip>:8765" in output


def test_server_launcher_lan_flag_binds_all_interfaces(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server_main.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    server_main.main(["--lan"])

    assert calls == [
        (
            "biodynamic_calendar_app:app",
            {"host": "0.0.0.0", "port": 8765, "reload": False},
        )
    ]
    output = capsys.readouterr().out
    assert "BD Calendar is starting on all network interfaces." in output
    assert "Browse from another device: http://<this-computer-ip>:8765" in output


def test_server_launcher_local_host_override_prints_local_browse_hint(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server_main.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    server_main.main(["--host", "127.0.0.1", "--port", "9000"])

    assert calls == [
        (
            "biodynamic_calendar_app:app",
            {"host": "127.0.0.1", "port": 9000, "reload": False},
        )
    ]
    output = capsys.readouterr().out
    assert "BD Calendar is starting locally." in output
    assert "Browse on this computer: http://127.0.0.1:9000" in output
    assert "For LAN access, restart with: biodynamic-calendar-server --lan" in output


def test_app_startup_logs_version(monkeypatch, caplog):
    async def fake_bootstrap_astral_location(**_kwargs):
        return SimpleNamespace(config=object())

    async def run_lifespan():
        async with app_module._lifespan(object()):
            pass

    monkeypatch.setattr(app_module, "_project_version", lambda: "v0.test")
    monkeypatch.setattr(app_module, "_bootstrap_astral_location", fake_bootstrap_astral_location)
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    asyncio.run(run_lifespan())

    assert "BD Calendar app version: v0.test" in caplog.text


def test_app_shutdown_cancels_location_retry(monkeypatch):
    calls = 0
    retry_cancelled = False

    async def fake_bootstrap_astral_location(**_kwargs):
        nonlocal calls, retry_cancelled
        calls += 1
        if calls == 1:
            return SimpleNamespace(config=None)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            retry_cancelled = True
            raise

    async def run_lifespan():
        async with app_module._lifespan(object()):
            await asyncio.sleep(0)

    monkeypatch.setattr(app_module, "_bootstrap_astral_location", fake_bootstrap_astral_location)

    asyncio.run(run_lifespan())

    assert calls == 2
    assert retry_cancelled is True

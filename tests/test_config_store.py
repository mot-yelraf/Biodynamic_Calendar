from pathlib import Path
import json

from biodynamic_calendar import BiodynamicConfig
from biodynamic_calendar_app import config_store


def test_system_timezone_name_uses_localtime_symlink(monkeypatch, tmp_path):
    zoneinfo_root = tmp_path / "tz" / "zoneinfo"
    denver = zoneinfo_root / "America" / "Denver"
    denver.parent.mkdir(parents=True)
    denver.write_text("", encoding="utf-8")

    localtime = tmp_path / "etc" / "localtime"
    localtime.parent.mkdir(parents=True)
    localtime.symlink_to(denver)

    monkeypatch.setenv("TZ", "")
    monkeypatch.setattr(config_store, "datetime", type("FakeDateTime", (), {"now": staticmethod(lambda: __import__("datetime").datetime(2026, 3, 17))}))
    monkeypatch.setattr(config_store, "Path", lambda value: localtime if value == "/etc/localtime" else Path(value))

    assert config_store._system_timezone_name() == "America/Denver"


def test_detect_location_from_timezone_falls_back_to_city_lookup(monkeypatch):
    monkeypatch.setattr(config_store, "_system_timezone_name", lambda: "America/Denver")

    cfg = config_store._detect_location_from_timezone()

    assert cfg is not None
    assert cfg.timezone_name == "America/Denver"
    assert round(cfg.latitude, 3) == 39.733
    assert round(cfg.longitude, 3) == -104.983


def test_detect_location_prefers_sensorius_astral_settings(monkeypatch, tmp_path):
    root = tmp_path / "system_settings"
    host_dir = root / "test-host.local"
    host_dir.mkdir(parents=True)
    (host_dir / "settings.toml").write_text(
        """
[Time]
TZ = "America/Denver"

[Astral]
AUTO_IP = true
LATITUDE = "32.790000"
LONGITUDE = "-108.274900"
TIMEZONE = "America/Denver"
ALTITUDE = "1783.00"
SOURCE = "ip"
PROVIDER = "ip-api.com"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SENSORIUS_SETTINGS_DIR", str(root))
    monkeypatch.setattr(config_store.socket, "gethostname", lambda: "test-host.local")

    detected = config_store._detect_location_from_sensorius_settings()

    assert detected is not None
    assert detected.source == "ip_cached"
    assert detected.provider == "ip-api.com"
    assert detected.altitude == 1783.0
    assert detected.config.timezone_name == "America/Denver"
    assert detected.config.latitude == 32.79
    assert detected.config.longitude == -108.2749


def test_detect_location_from_ip_uses_ipapi_payload(monkeypatch):
    monkeypatch.setattr(
        config_store,
        "probe_ip_geolocation_providers",
        lambda timeout_sec=2.5: [
            {
                "provider": "ipapi.co",
                "lat": 32.79,
                "lon": -108.2749,
                "tz": "America/Denver",
                "error": "",
            }
        ],
    )

    detected = config_store._detect_location_from_ip()

    assert detected.source == "ip"
    assert detected.provider == "ipapi.co"
    assert detected.config.latitude == 32.79
    assert detected.config.longitude == -108.2749


def test_detect_location_from_ip_falls_back_to_ip_api(monkeypatch):
    monkeypatch.setattr(
        config_store,
        "probe_ip_geolocation_providers",
        lambda timeout_sec=2.5: [
            {
                "provider": "ipapi.co",
                "lat": None,
                "lon": None,
                "tz": "",
                "error": "HTTP 429",
            },
            {
                "provider": "ip-api.com",
                "lat": 32.79,
                "lon": -108.2749,
                "tz": "America/Denver",
                "error": "",
            },
            {
                "provider": "ipwho.is",
                "lat": 39.73,
                "lon": -104.98,
                "tz": "America/Denver",
                "error": "",
            },
        ],
    )

    detected = config_store._detect_location_from_ip()

    assert detected.source == "ip"
    assert detected.provider == "ip-api.com"
    assert detected.config.latitude == 32.79
    assert detected.config.longitude == -108.2749


def test_saved_ip_location_does_not_call_providers_on_normal_load(monkeypatch, tmp_path):
    def fail_probe(timeout_sec=2.5):
        raise AssertionError("provider lookup should not run")

    monkeypatch.setattr(config_store, "probe_ip_geolocation_providers", fail_probe)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "latitude": 32.79,
                "longitude": -108.2749,
                "timezone_name": "America/Denver",
                "location_source": "ip",
                "location_provider": "ip-api.com",
                "altitude": 1783,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = config_store.ConfigStore(root=tmp_path)
    detected = store.load_location()

    assert detected is not None
    assert detected.source == "ip_cached"
    assert detected.provider == "ip-api.com"
    assert detected.altitude == 1783
    assert detected.config.latitude == 32.79


def test_reset_location_saves_detected_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_store,
        "probe_ip_geolocation_providers",
        lambda timeout_sec=2.5: [
            {
                "provider": "ip-api.com",
                "lat": 32.79,
                "lon": -108.2749,
                "tz": "America/Denver",
                "error": "",
            }
        ],
    )

    store = config_store.ConfigStore(root=tmp_path)
    detected = store.reset_location()

    assert detected.ok
    assert detected.provider == "ip-api.com"
    raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert raw["latitude"] == 32.79
    assert raw["longitude"] == -108.2749
    assert raw["timezone_name"] == "America/Denver"
    assert raw["location_source"] == "ip"
    assert raw["location_provider"] == "ip-api.com"


def test_auto_ip_disabled_without_manual_coordinates_is_unavailable(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "latitude": "",
                "longitude": "",
                "timezone_name": "America/Denver",
                "auto_ip": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = config_store.ConfigStore(root=tmp_path)
    detected = store.resolve_location(persist_if_auto=True)

    assert detected.config is None
    assert detected.source == "none"
    assert detected.error == "Astral.AUTO_IP is disabled"


def test_calendar_cache_round_trips_and_clears_on_location_change(tmp_path):
    store = config_store.ConfigStore(root=tmp_path)
    cfg = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")
    moved_cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    payload = {"ok": True, "calendar": [{"date": "2026-06-14"}], "astro": {"ok": True}}

    store.save(cfg)
    store.save_calendar_cache_entry(cfg, "calendar:2026-06:2026-06-14", payload)

    assert store.calendar_cache_path.exists()
    assert store.load_calendar_cache_entry(cfg, "calendar:2026-06:2026-06-14") == payload
    assert store.load_calendar_cache_entry(moved_cfg, "calendar:2026-06:2026-06-14") is None

    store.save(cfg)
    assert store.calendar_cache_path.exists()

    store.save(moved_cfg)
    assert not store.calendar_cache_path.exists()


def test_plantings_are_normalized_and_persisted(tmp_path):
    store = config_store.ConfigStore(root=tmp_path)

    planting = store.save_planting(
        {
            "name": "Tomato",
            "variety": "Brandywine",
            "plant_part": "fruit",
            "start_method": "seed",
            "start_date": "2026-03-01",
            "days_to_maturity": "80",
            "location": "Greenhouse bench",
            "attributes": "Needs trellis after transplant.",
        }
    )

    assert planting["id"]
    assert planting["plant_part"] == "Fruit"
    assert planting["start_method"] == "seed"
    assert planting["expected_harvest_date"] == "2026-05-20"
    assert planting["harvest_window_days"] == 3

    loaded = store.load_plantings()
    assert loaded == [planting]

    updated = dict(planting)
    updated["expected_harvest_date"] = "2026-05-25"
    updated["days_to_maturity"] = ""
    saved = store.save_planting(updated)
    assert saved["days_to_maturity"] == 85
    assert len(store.load_plantings()) == 1

    assert store.delete_planting(str(planting["id"])) is True
    assert store.load_plantings() == []

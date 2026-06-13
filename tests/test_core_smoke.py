from datetime import date

from biodynamic_calendar import BiodynamicConfig, get_astro_payload, get_biodynamic_local_now
from biodynamic_calendar.core import _moon_phase_name


def test_get_biodynamic_local_now_uses_config_timezone():
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    now = get_biodynamic_local_now(cfg)
    assert now.tzinfo is not None
    assert getattr(now.tzinfo, "key", "") == "America/Denver"


def test_astro_payload_includes_configured_location_now():
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    payload = get_astro_payload(config=cfg)
    assert payload["tz"] == "America/Denver"
    assert payload["timestamp"]
    assert payload["current_time"]
    assert 0 <= float(payload["current_minutes"]) <= 1440
    assert isinstance(payload["moon_points"], list)
    assert isinstance(payload["position_29d"], list)
    assert len(payload["position_29d"]) == 29
    assert {"date", "sun", "moon", "moon_phase_value"}.issubset(payload["position_29d"][0])


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

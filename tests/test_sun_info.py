from datetime import date

from biodynamic_calendar import BiodynamicConfig
from biodynamic_calendar_app.sun_info import selected_day_sun


def test_sun_events_follow_date_location_and_timezone():
    denver = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    october = selected_day_sun(date(2026, 10, 24), denver)
    assert october == {"sunrise": "07:20", "sunset": "18:07", "daylight_minutes": 647}
    assert selected_day_sun(date(2026, 6, 24), denver)["daylight_minutes"] > october["daylight_minutes"]
    utc = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="UTC")
    assert selected_day_sun(date(2026, 10, 24), utc)["sunrise"] == "13:20"


def test_polar_dates_have_unavailable_events():
    tromso = BiodynamicConfig(latitude=69.6492, longitude=18.9553, timezone_name="Europe/Oslo")
    for day in (date(2026, 6, 21), date(2026, 12, 21)):
        assert selected_day_sun(day, tromso) == {"sunrise": "", "sunset": "", "daylight_minutes": None}

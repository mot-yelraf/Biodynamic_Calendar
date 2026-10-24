"""Local sun events for the selected calendar date."""

from datetime import date, timezone
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sunrise, sunset

from biodynamic_calendar import BiodynamicConfig


def selected_day_sun(day: date, config: BiodynamicConfig) -> dict[str, object]:
    observer = Observer(latitude=config.latitude, longitude=config.longitude)
    tz = ZoneInfo(config.timezone_name)
    events = {}
    for name, calculate in (("sunrise", sunrise), ("sunset", sunset)):
        try:
            events[name] = calculate(observer, date=day, tzinfo=tz)
        except ValueError:
            # Some polar dates have no rise or set event.
            events[name] = None
    rise, setting = events["sunrise"], events["sunset"]
    minutes = None
    if rise is not None and setting is not None:
        minutes = round((setting.astimezone(timezone.utc) - rise.astimezone(timezone.utc)).total_seconds() / 60)
    return {
        "sunrise": rise.strftime("%H:%M") if rise is not None else "",
        "sunset": setting.strftime("%H:%M") if setting is not None else "",
        "daylight_minutes": minutes,
    }

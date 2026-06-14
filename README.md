# Biodynamic Calendar

Standalone biodynamic calendar project extracted from Sensorius.

It has two deliverables:

- `biodynamic_calendar`: an open-source Python library for generating a biodynamic month payload
- `biodynamic_calendar_app`: a local FastAPI app that renders the calendar as a standalone browser app

## Features

- Maria Thun-style 12-constellation moon-sign calendar
- day-level 24-hour transition segments
- off-period overlays for node/perigee windows
- combined Sun/Moon position graph with a clickable 29-day position view
- local note storage
- local planting plans with seed/transplant starts, plant focus, expected harvest dates, and crop attributes
- reusable Python API
- local web UI for browsing months and selected-day details
- auto-detect location from Sensorius Astral settings, IP geolocation, or system timezone city fallback

## Quick Start

### macOS / Linux

```bash
./scripts/setup_macos.sh
source .venv/bin/activate
biodynamic-calendar-server
```

or

```bash
./scripts/setup_linux.sh
source .venv/bin/activate
biodynamic-calendar-server
```

On Linux, the setup script can optionally create and start a user systemd
service for auto-start. The manual server and Linux auto-start service bind to
all network interfaces by default.

### Windows PowerShell

```powershell
./scripts/setup_windows.ps1
.\.venv\Scripts\Activate.ps1
biodynamic-calendar-server
```

Then open `http://127.0.0.1:8765` on this computer, or
`http://<this-computer-ip>:8765` from another device on the same network. The
setup scripts print the platform-specific command for finding the computer's IP
address.

## Library Usage

```python
from biodynamic_calendar import BiodynamicConfig, get_biodynamic_payload

cfg = BiodynamicConfig(
    latitude=39.7392,
    longitude=-104.9903,
    timezone_name="America/Denver",
)

payload = get_biodynamic_payload(config=cfg)
print(payload["month_label"])
print(payload["current"])
```

You can also provide config by environment variables:

- `BIODYNAMIC_LAT`
- `BIODYNAMIC_LON`
- `BIODYNAMIC_TZ`

## Project Layout

- `src/biodynamic_calendar/`: reusable library
- `src/biodynamic_calendar_app/`: standalone web app
- `templates/`: app HTML template
- `static/`: app stylesheet
- `scripts/`: setup scripts
- `docs/`: project docs

## Notes

- The first run may download the Skyfield `de421.bsp` ephemeris.
- Local app config, notes, planting plans, and the calendar/astral cache are stored in `~/.biodynamic_calendar/`.
- To use the Sensorius SQLite database for notes, plantings, daily summaries,
  and calendar cache, start the app with `SENSORIUS_DB_PATH=/path/to/sensorius_data.db`
  or `BD_CALENDAR_STORE=sensorius`.
- When Sensorius opens the app, use `/?source=sensorius` to show the calendar
  view without the top status/setup cards.
- Use **Reset Location** in the web UI to re-run auto-detection. Manually saved coordinates still take precedence until reset.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest -q
```

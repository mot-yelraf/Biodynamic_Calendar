<h1>Biodynamic Calendar <img src="static/bd-calendar-icon-512.svg" alt="" height="40"></h1>

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

![Biodynamic Calendar](docs/screenshots/Biodynamic%20Calendar.png)

## Quick Start

Internet access is required for initial setup to install Python dependencies,
including Astral and Skyfield. On first calendar generation, internet access is
also required if Skyfield's `de421.bsp` ephemeris is not already cached or
provided with `BIODYNAMIC_SKYFIELD_DIR`. After dependencies and ephemeris data
are present, normal calendar use is local-first.

### macOS / Linux

```bash
./scripts/install_macos.sh
source .venv/bin/activate
biodynamic-calendar-server --lan
```

or

```bash
./scripts/install_linux.sh
source .venv/bin/activate
biodynamic-calendar-server --lan
```

On Linux, the install script can optionally create and start a user systemd
service for auto-start. If an existing `biodynamic-calendar.service` user
service is present, the installer stops it before updating and restarts it
after installation. Manual LAN access is explicit with `--lan`; without it,
the server listens only on `127.0.0.1`. The Linux auto-start service uses its
configured `BD_CALENDAR_HOST`, which defaults to `0.0.0.0` for LAN access.

To update a Linux/rPi install after rsyncing the updated repo, run:

```bash
cd /path/to/Biodynamic_Calendar
./scripts/install_linux.sh
```

For hosts that already have the app checkout and setup in place, create
`scripts/bdca_hosts.txt` with lines like
`pi@bdca.local | /home/pi/Biodynamic_Calendar`, then preview and apply source
deploys with:

```bash
./scripts/deploy_bdca --dryrun
./scripts/deploy_bdca --apply
```

Use `BD_CALENDAR_AUTO_START=yes ./scripts/install_linux.sh` for a
non-interactive service update. Use `./scripts/uninstall_linux.sh` to stop and
remove the service and `.venv`; local JSON data is preserved unless
`--purge-data` is passed.

### Windows PowerShell

```powershell
./scripts/install_windows.ps1
.\.venv\Scripts\Activate.ps1
biodynamic-calendar-server --lan
```

Then open `http://127.0.0.1:8765` on this computer, or
`http://<this-computer-ip>:8765` from another device on the same network. The
install scripts print the platform-specific command for finding the computer's IP
address.

Each install script writes a fresh `install.log` in the project directory. The
log starts with host, OS, hardware, disk, installer, git, and tool-version
context, then records the install steps and command output.

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

- `src/biodynamic_calendar/core.py`: calendar, lunar, ephemeris, and astronomy calculations
- `src/biodynamic_calendar/hints.py`: biodynamic and planting-advice generation
- `src/biodynamic_calendar_app/app.py`: standalone FastAPI web application
- `src/biodynamic_calendar_app/config_store.py`: JSON and SQLite storage backends
- `src/biodynamic_calendar_app/storage_validation.py`: persisted-data validation and normalization
- `templates/`: app HTML template
- `static/`: app stylesheet and JavaScript module
- `scripts/`: install, uninstall, and diagnostic scripts
- `docs/`: project docs

## Notes

- Skyfield uses the `de421.bsp` ephemeris for lunar and solar calculations.
  The app looks first in `BIODYNAMIC_SKYFIELD_DIR` when set, then in the user
  cache. If no copy exists, Skyfield downloads `de421.bsp` into the user cache
  instead of writing into the installed package directory.
- Astral is installed as a Python dependency and is used locally at runtime for
  solar, lunar, and timezone-city fallback calculations.
- Local app config, notes, planting plans, and the calendar/astral cache are stored in `~/.biodynamic_calendar/`.
- Future planning ranges are cached in `calendar_cache.json` with stable keys so expensive range generation can be reused across app restarts and day changes.
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

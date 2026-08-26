# Biodynamic Calendar

<img src="static/bd-calendar-icon-512.svg" alt="Biodynamic Calendar app icon" width="256" height="256">

Standalone biodynamic calendar project that grew from the calendar originally
included with Sensorius.

It has two deliverables:

- `biodynamic_calendar`: an open-source Python library for generating a biodynamic month payload
- `biodynamic_calendar_app`: a FastAPI app presented in a native pywebview desktop window and on the trusted LAN

## Features

- Maria Thun-style 12-constellation moon-sign calendar
- day-level 24-hour transition segments
- off-period overlays for node/perigee windows
- combined Sun/Moon position graph with a clickable 29-day position view
- local note storage
- local planting plans with seed/transplant starts, plant focus, expected harvest dates, and crop attributes
- reusable Python API
- native 1600 × 1000 desktop window with the Biodynamic Calendar app icon
- local web UI for browsing months and selected-day details
- auto-detect location from saved Astral settings, IP geolocation, or system timezone city fallback
- Caelus-style Settings dialog with Location and seasonal Appearance choices
- four matching valley themes for Spring, Summer, Autumn, and Winter, with optional automatic seasonal switching
- local custom theme collections with one to five named images and Biodynamic Calendar palettes
- distraction-free Scenery view with temporary season previews and one-click return to the calendar

![Biodynamic Calendar](docs/screenshots/Biodynamic%20Calendar.png)

For an illustrated walkthrough of every dashboard panel, dialog, planning tool,
and report control, see the [Biodynamic Calendar User Guide](docs/user_guide.md).

## Quick Start

Internet access is required for initial setup to install Python dependencies,
including Astral and Skyfield. On first calendar generation, internet access is
also required if Skyfield's `de421.bsp` ephemeris is not already cached or
provided with `BIODYNAMIC_SKYFIELD_DIR`. After dependencies and ephemeris data
are present, normal calendar use is local-first.

The installers show the platform-native folder browser. On macOS, selecting an
existing `Biodynamic_Calendar` folder updates it directly; selecting another
folder creates `Biodynamic_Calendar` beneath it. The default remains
`~/Biodynamic_Calendar`, and a successful location is offered on the next
install. Set `BD_CALENDAR_INSTALL_DIR` on any platform or pass
`-InstallDir` on Windows to bypass the dialog with an exact application path.
Installer preferences are stored under the platform's user configuration
directory; user data remains in `~/.biodynamic_calendar/` across updates.

### macOS

The desktop launcher creates a minimal identity bundle under
`~/Library/Application Support/Biodynamic Calendar/` so macOS displays
“Biodynamic Calendar” and its native icon instead of the Python interpreter
identity, including in Force Quit. Set
`BD_CALENDAR_HEADLESS=1` to bypass this GUI relaunch in headless environments.

```bash
./scripts/install_macos.sh
~/Biodynamic_Calendar/run_bd_calendar_gui.sh
```

The app opens in a resizable native window whose default size is 1600 × 1000.
The window automatically fits smaller displays.

### Linux / Raspberry Pi

Install the GTK/WebKit runtime first on Debian, Ubuntu, or Raspberry Pi OS:

```bash
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

Then install and launch:

```bash
./scripts/install_linux.sh
~/Biodynamic_Calendar/run_bd_calendar_gui.sh
```

On Linux, the install script can optionally create and start a user systemd
service for auto-start. If an existing `biodynamic-calendar.service` user
service is present, the installer stops it before updating and restarts it
after installation. The server binds to `0.0.0.0` by default for LAN access.
Use `--host 127.0.0.1` to restrict a manual launch to this computer. The Linux
auto-start service uses its configured `BD_CALENDAR_HOST`, which also defaults
to `0.0.0.0`.

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
non-interactive service update. Use
`~/Biodynamic_Calendar/scripts/uninstall_linux.sh` to stop and remove the
service and installed `.venv`; local JSON data is preserved unless
`--purge-data` is passed.

### Windows PowerShell

```powershell
./scripts/install_windows.ps1
C:\Users\<name>\Biodynamic_Calendar\run_bd_calendar_gui.cmd
```

The desktop launcher starts the FastAPI server on `0.0.0.0:8765`, waits for it,
and opens `http://127.0.0.1:8765` inside pywebview. It stops that server when the
window closes, unless it attached to a server that was already running. Open
`http://127.0.0.1:8765` on this computer, or
`http://<this-computer-ip>:8765` from another device on the same network. The
install scripts print the platform-specific command for finding the computer's IP
address.

To run only the LAN server, use `run_bd_calendar_server.sh` on macOS/Linux or
`run_bd_calendar_server.cmd` on Windows. Set `BD_CALENDAR_HOST=127.0.0.1` to
restrict a desktop-owned server to the local computer.

Each install script writes a fresh `install.log` in the selected application
folder. The log starts with host, OS, hardware, disk, installer, git, and
tool-version context, then records the install steps and command output.

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
- `src/biodynamic_calendar_app/desktop.py`: cross-platform pywebview launcher
- `src/biodynamic_calendar_app/config_store.py`: JSON and SQLite storage backends
- `src/biodynamic_calendar_app/theme_manager.py`: custom theme validation, image processing, manifests, and assets
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
- Local app config, notes, planting plans, the calendar/astral cache, and custom themes are stored in `~/.biodynamic_calendar/`. Custom theme metadata is kept in `theme_settings/themes.json`; processed backgrounds and thumbnails are kept under `theme_assets/`.
- Future planning ranges are cached in `calendar_cache.json` with stable keys so expensive range generation can be reused across app restarts and day changes.
- The calendar is also included in Sensorius; this repository remains available
  as the standalone library and app.
- Use **Settings → Location → Detect Location** to re-run auto-detection. Manually saved coordinates still take precedence until detection is requested.

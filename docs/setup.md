# Setup

## Prerequisites

- Python 3.11 or newer
- internet access on first run only if the Skyfield ephemeris is not bundled or already cached

## Skyfield Ephemeris

BD Calendar uses Skyfield's `de421.bsp` ephemeris for lunar and solar
calculations. Runtime lookup order is:

1. `BIODYNAMIC_SKYFIELD_DIR/de421.bsp`, when `BIODYNAMIC_SKYFIELD_DIR` is set.
2. The user cache.
3. The bundled project copy, when present.

If no copy exists, Skyfield downloads `de421.bsp` into the user cache. The app
does not write downloaded ephemeris data into the installed Python package
directory.

Default cache locations:

- Linux/rPi: `${XDG_CACHE_HOME:-~/.cache}/biodynamic_calendar/skyfield/`
- macOS: `~/Library/Caches/biodynamic_calendar/skyfield/`
- Windows: `%LOCALAPPDATA%\biodynamic_calendar\skyfield\`

Set `BIODYNAMIC_SKYFIELD_DIR=/path/to/skyfield-cache` when you want a fixed
shared or pre-seeded ephemeris location.

## macOS

```bash
./scripts/install_macos.sh
source .venv/bin/activate
biodynamic-calendar-server
```

Browse on this Mac at `http://127.0.0.1:8765`, or open
`http://<this-Mac-IP>:8765` from another device on the same network. The server
binds to all network interfaces by default. Find the Mac's IP with:

```bash
ipconfig getifaddr en0
```

## Linux

```bash
./scripts/install_linux.sh
```

During install, the script asks whether to enable auto-start for the current Linux
user with systemd. If you answer yes and `systemctl --user` is available, it
creates and starts a service that binds to all network interfaces:

```text
~/.config/systemd/user/biodynamic-calendar.service
```

Check it with:

```bash
systemctl --user status biodynamic-calendar.service
```

Disable it with:

```bash
systemctl --user disable --now biodynamic-calendar.service
```

Uninstall the service and local virtual environment with:

```bash
./scripts/uninstall_linux.sh
```

Local JSON data in `~/.biodynamic_calendar/` is preserved by default. Pass
`--purge-data` only when you intentionally want to delete saved app state.

## Updating Linux/rPi installs

After rsyncing an updated checkout onto the Linux host, run the installer from
the updated repo:

```bash
cd /path/to/Biodynamic_Calendar
./scripts/install_linux.sh
```

If the existing user service is present, the installer stops
`biodynamic-calendar.service` before reinstalling dependencies and restarts that
same service after writing the updated unit file. This avoids leaving the old
server process bound to port 8765 while the updated service starts.

For non-interactive SSH update commands, set the desired auto-start behavior:

```bash
BD_CALENDAR_AUTO_START=yes ./scripts/install_linux.sh
```

If you previously created a different manual or system-wide service, remove it
before enabling the user service. Check for extra services or listeners with:

```bash
systemctl --user status biodynamic-calendar.service
systemctl status biodynamic-calendar.service
ps -ef | grep biodynamic-calendar-server
```

If you skip auto-start, start manually:

```bash
source .venv/bin/activate
biodynamic-calendar-server
```

Browse on this computer at `http://127.0.0.1:8765`, or open
`http://<this-computer-IP>:8765` from another device on the same network. The
manual server binds to all network interfaces by default. Find this computer's
IP with:

```bash
hostname -I
```

## Windows PowerShell

```powershell
./scripts/install_windows.ps1
.\.venv\Scripts\Activate.ps1
biodynamic-calendar-server
```

Browse on this PC at `http://127.0.0.1:8765`, or open
`http://<this-PC-IP>:8765` from another device on the same network. The server
binds to all network interfaces by default. Find this PC's IP with:

```powershell
ipconfig
```

If another device cannot connect, check the operating system firewall for Python
or the selected port.

## Uninstall

Uninstall local install artifacts with:

```bash
./scripts/uninstall_macos.sh
```

or:

```powershell
./scripts/uninstall_windows.ps1
```

Both scripts preserve `~/.biodynamic_calendar/` by default; pass `--purge-data`
on macOS or `-PurgeData` on Windows to delete saved app state.

## Local Data

The standalone app stores local runtime JSON under `~/.biodynamic_calendar/`:

- `config.json`: saved or auto-detected latitude, longitude, and timezone.
- `notes.json`: user notes.
- `plantings.json`: planting plans.
- `calendar_cache.json`: same-day calendar/astral cache entries keyed to the saved location.

## Sensorius Companion Mode

When the app runs on the same host as Sensorius, it can store shared calendar
state in the Sensorius SQLite database instead of the standalone JSON note,
planting, daily-summary, and calendar-cache files.

Set either:

```bash
SENSORIUS_DB_PATH=/path/to/sensorius_data.db
```

or:

```bash
BD_CALENDAR_STORE=sensorius
```

If `BD_CALENDAR_STORE=sensorius` is set without an explicit DB path, the app
uses `~/Sensorius/sensorius_data.db`. Existing `notes.json` and
`plantings.json` data is imported into empty Sensorius tables on first startup.
The JSON `config.json` remains available as a standalone location fallback, but
Sensorius Astral settings are preferred when present.

When launching from the Sensorius Calendar button, open the app with
`/?source=sensorius` to hide the top status/setup cards and show the calendar
workflow first.

## Location Reset

The standalone app stores its location in `~/.biodynamic_calendar/config.json`.
Use **Reset Location** in the web UI to re-run auto-detection. Detection checks
local Sensorius Astral settings first, then Sensorius-style IP geolocation, then
falls back to the system timezone's Astral city lookup.
Changing the saved latitude, longitude, or timezone clears `calendar_cache.json`.

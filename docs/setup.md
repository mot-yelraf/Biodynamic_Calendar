# Setup

## Prerequisites

- Python 3.11 or newer
- pywebview (installed automatically into the private virtual environment)
- internet access for initial dependency installation, including Astral and
  Skyfield
- internet access on first calendar generation unless the Skyfield ephemeris is
  already cached or provided with `BIODYNAMIC_SKYFIELD_DIR`

After dependencies are installed and the Skyfield ephemeris is available, normal
calendar use is local-first. Astral runs locally at runtime; Skyfield only needs
network access when it has to download missing ephemeris data.

## Skyfield Ephemeris

BD Calendar uses Skyfield's `de421.bsp` ephemeris for lunar and solar
calculations. Runtime lookup order is:

1. `BIODYNAMIC_SKYFIELD_DIR/de421.bsp`, when `BIODYNAMIC_SKYFIELD_DIR` is set.
2. The user cache.

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
~/Biodynamic_Calendar/run_bd_calendar_gui.sh
```

The installer copies the runtime to `~/Biodynamic_Calendar` and creates
`~/Biodynamic_Calendar/.venv`. The native, resizable window defaults to
1600 × 1000 and uses the Biodynamic Calendar app icon in the Dock and app
switcher.

Browse on this Mac at `http://127.0.0.1:8765`, or open
`http://<this-Mac-IP>:8765` from another device on the same network. The server
binds to all network interfaces by default. Use `--host 127.0.0.1` to make it
local-only. Find the Mac's IP with:

```bash
ipconfig getifaddr en0
```

## Linux

On Debian, Ubuntu, and Raspberry Pi OS, install the native GTK/WebKit packages
used by pywebview:

```bash
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

```bash
./scripts/install_linux.sh
~/Biodynamic_Calendar/run_bd_calendar_gui.sh
```

The installer copies the runtime to `~/Biodynamic_Calendar`, creates
`~/Biodynamic_Calendar/.venv` with access to the system GTK bindings, and adds
the per-user desktop identity and icon the first time the GUI runs.

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

Uninstall the service and installed virtual environment with:

```bash
~/Biodynamic_Calendar/scripts/uninstall_linux.sh
```

Local JSON data in `~/.biodynamic_calendar/` is preserved by default. Pass
`--purge-data` only when you intentionally want to delete saved app state.

## Updating Linux/rPi installs

For hosts that already have Biodynamic Calendar checked out and installed, use
the rsync deploy helper from your local checkout. Create a host file with one
target per line:

```text
host | /absolute/path/to/Biodynamic_Calendar
pi@bdca.local | /home/pi/Biodynamic_Calendar
```

By default the script reads `scripts/bdca_hosts.txt`; that file is ignored by
git so host-specific paths stay local. Preview changes first:

```bash
./scripts/deploy_bdca --dryrun
```

Apply the deploy:

```bash
./scripts/deploy_bdca --apply
```

The deploy syncs `src/`, `static/`, `templates/`, and `pyproject.toml`. It does
not prune remote files, and `.venv/` plus local runtime data on the remote host
are left alone. The script refuses a target entry that points back at the current
local checkout.

After rsyncing an updated checkout onto the Linux host, run the installer from
the updated repo when dependencies or service setup changed:

```bash
cd /path/to/Biodynamic_Calendar
./scripts/install_linux.sh
```

If the existing user service is present, the installer stops
`biodynamic-calendar.service` before reinstalling dependencies and restarts that
same service after writing the updated unit file. This avoids leaving the old
server process bound to port 8765 while the updated service starts.
The installer also verifies that the app entrypoint imports successfully after
dependency installation. If native Python dependencies inside `.venv` are
damaged or from the wrong platform, it rebuilds `.venv` once with a clean
dependency install.

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

If you skip auto-start, start the desktop application manually:

```bash
~/Biodynamic_Calendar/run_bd_calendar_gui.sh
```

To run only the LAN server, use:

```bash
~/Biodynamic_Calendar/run_bd_calendar_server.sh
```

Browse on this computer at `http://127.0.0.1:8765`, or open
`http://<this-computer-IP>:8765` from another device on the same network. LAN
access is enabled by default. Find this computer's IP with:

```bash
hostname -I
```

## Windows PowerShell

```powershell
./scripts/install_windows.ps1
C:\Users\<name>\Biodynamic_Calendar\run_bd_calendar_gui.cmd
```

The installer copies the runtime to `%USERPROFILE%\Biodynamic_Calendar` and
creates its private `.venv` there. The pywebview window defaults to 1600 × 1000
and uses the Biodynamic Calendar icon in the window and taskbar. Run only the
LAN server with `run_bd_calendar_server.cmd`.

Browse on this PC at `http://127.0.0.1:8765`, or open
`http://<this-PC-IP>:8765` from another device on the same network. LAN access
is enabled by default. Find this PC's IP with:

```powershell
ipconfig
```

If another device cannot connect, check the operating system firewall for Python
or the selected port.

## Uninstall

Uninstall local install artifacts with:

```bash
~/Biodynamic_Calendar/scripts/uninstall_macos.sh
```

or:

```powershell
C:\Users\<name>\Biodynamic_Calendar\scripts\uninstall_windows.ps1
```

All uninstall scripts preserve `~/.biodynamic_calendar/` by default; pass `--purge-data`
on macOS or `-PurgeData` on Windows to delete saved app state.

## Desktop launcher settings

The GUI browses the local server through `http://127.0.0.1:8765` while an owned
server binds to `0.0.0.0` for trusted-LAN access. Supported overrides are:

- `BD_CALENDAR_HOST`: owned server bind address.
- `BD_CALENDAR_PORT`: server and GUI port.
- `BD_CALENDAR_GUI_URL`: attach the window to an already-running server URL.
- `BD_CALENDAR_GUI_WIDTH` and `BD_CALENDAR_GUI_HEIGHT`: requested window size.
- `BD_CALENDAR_GUI_X` and `BD_CALENDAR_GUI_Y`: optional initial position.

The launcher stops only a server process it started. If it attaches to an
existing healthy server, that server remains running when the window closes.

## Local Data

The standalone app stores local runtime JSON under `~/.biodynamic_calendar/`:

- `config.json`: saved or auto-detected latitude, longitude, timezone, and seasonal appearance preference.
- `notes.json`: user notes.
- `plantings.json`: planting plans.
- `calendar_cache.json`: same-day calendar/astral cache entries keyed to the saved location.

## Location Reset

The standalone app stores its location in `~/.biodynamic_calendar/config.json`.
Use **Settings → Location → Detect Location** in the web UI to re-run auto-detection. Detection checks
saved local Astral settings first, then IP geolocation, and finally the system
timezone's Astral city lookup.
Changing the saved latitude, longitude, or timezone clears `calendar_cache.json`.

# Setup

## Prerequisites

- Python 3.11 or newer
- internet access on first run if the Skyfield ephemeris is not already cached

## macOS

```bash
./scripts/setup_macos.sh
source .venv/bin/activate
biodynamic-calendar-server
```

Browse on this Mac at `http://127.0.0.1:8765`.

For access from another device on the same network:

```bash
biodynamic-calendar-server --host 0.0.0.0
```

Then open `http://<this-Mac-IP>:8765` from the other device. Find the Mac's IP
with:

```bash
ipconfig getifaddr en0
```

## Linux

```bash
./scripts/setup_linux.sh
```

During setup, the script asks whether to enable auto-start for the current Linux
user with systemd. If you answer yes and `systemctl --user` is available, it
creates and starts:

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

If you skip auto-start, start manually:

```bash
source .venv/bin/activate
biodynamic-calendar-server
```

Browse on this computer at `http://127.0.0.1:8765`.

For access from another device on the same network:

```bash
biodynamic-calendar-server --host 0.0.0.0
```

Then open `http://<this-computer-IP>:8765` from the other device. Find this
computer's IP with:

```bash
hostname -I
```

## Windows PowerShell

```powershell
./scripts/setup_windows.ps1
.\.venv\Scripts\Activate.ps1
biodynamic-calendar-server
```

Browse on this PC at `http://127.0.0.1:8765`.

For access from another device on the same network:

```powershell
biodynamic-calendar-server --host 0.0.0.0
```

Then open `http://<this-PC-IP>:8765` from the other device. Find this PC's IP
with:

```powershell
ipconfig
```

If another device cannot connect, check the operating system firewall for Python
or the selected port.

## Local Data

The standalone app stores local runtime JSON under `~/.biodynamic_calendar/`:

- `config.json`: saved or auto-detected latitude, longitude, and timezone.
- `notes.json`: user notes.
- `plantings.json`: planting plans.
- `calendar_cache.json`: same-day calendar/astral cache entries keyed to the saved location.

## Location Reset

The standalone app stores its location in `~/.biodynamic_calendar/config.json`.
Use **Reset Location** in the web UI to re-run auto-detection. Detection checks
local Sensorius Astral settings first, then Sensorius-style IP geolocation, then
falls back to the system timezone's Astral city lookup.
Changing the saved latitude, longitude, or timezone clears `calendar_cache.json`.

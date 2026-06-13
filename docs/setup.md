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

## Linux

```bash
./scripts/setup_linux.sh
source .venv/bin/activate
biodynamic-calendar-server
```

## Windows PowerShell

```powershell
./scripts/setup_windows.ps1
.venv\Scripts\Activate.ps1
biodynamic-calendar-server
```

## Location Reset

The standalone app stores its location in `~/.biodynamic_calendar/config.json`.
Use **Reset Location** in the web UI to re-run auto-detection. Detection checks
local Sensorius Astral settings first, then Sensorius-style IP geolocation, then
falls back to the system timezone's Astral city lookup.

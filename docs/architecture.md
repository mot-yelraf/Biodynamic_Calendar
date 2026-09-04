# Architecture

## Components

- `biodynamic_calendar.core`
  - config dataclass
  - ephemeris bootstrap
  - moon-sign segmentation
  - off-period overlays
  - month payload generation
- `biodynamic_calendar_app`
  - local config store
  - FastAPI routes
  - standalone browser UI
  - native pywebview desktop launcher

## Runtime Model

1. The desktop launcher attaches to a healthy server or starts one in the same
   private virtual environment, binding to `0.0.0.0:8765` by default.
2. Pywebview opens the loopback URL in a native 1600 × 1000 window; browser
   clients on the trusted LAN can use the same server.
3. User stores latitude, longitude, timezone, and the seasonal appearance preference in the local config file.
4. The web app requests `/api/calendar?month=YYYY-MM`.
5. The app serves a matching same-day calendar/astral cache entry when one exists.
6. On a cache miss, the library produces the requested month or range payload and the app stores it on disk.
7. The app attaches local notes and planting plans to the payload.
8. The frontend renders the month grid, 24-hour gradients, selected-day summary, planting plan, notes, and Sun/Moon position graphics. The live Moon uses observer-local bright-limb and lunar-north rotations over the detailed lunar surface texture.

The default installed runtime is `~/Biodynamic_Calendar`, including its
`.venv`. Application data remains separate under `~/.biodynamic_calendar/`.

Runtime is local-first after setup. Internet access is needed to install Python
dependencies and, on a fresh machine, to download Skyfield's `de421.bsp`
ephemeris unless it is already cached or supplied with `BIODYNAMIC_SKYFIELD_DIR`.
Astral runs locally once installed.

## Storage

- `~/.biodynamic_calendar/config.json`
- `~/.biodynamic_calendar/notes.json`
- `~/.biodynamic_calendar/plantings.json`
- `~/.biodynamic_calendar/calendar_cache.json`
- Skyfield ephemeris cache:
  - Linux/rPi: `${XDG_CACHE_HOME:-~/.cache}/biodynamic_calendar/skyfield/`
  - macOS: `~/Library/Caches/biodynamic_calendar/skyfield/`
  - Windows: `%LOCALAPPDATA%\biodynamic_calendar\skyfield\`

The cache is keyed to rounded latitude, longitude, timezone, requested month or
range, and local date. Changing the saved location clears the cache so calendar
and astral data are regenerated for the new coordinates.

The calculation library also keeps a short-lived, bounded in-memory cache. It
returns defensive copies so callers cannot modify later results. Persistent
storage failures are logged and exposed by mutation APIs as HTTP 503 responses;
disk-cache failures remain best-effort when a fresh result can still be served.

`create_app(store=..., theme_manager=...)` accepts explicit dependencies for
isolated tests and embedded app instances. The default application continues to
use the automatically selected JSON or Sensorius SQLite store.

Skyfield data lookup checks `BIODYNAMIC_SKYFIELD_DIR` first, then the user
cache. Missing ephemeris data is downloaded into the user cache rather than the
package directory.

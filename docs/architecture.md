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

## Runtime Model

1. User stores latitude, longitude, and timezone in the local config file.
2. The web app requests `/api/calendar?month=YYYY-MM`.
3. The app serves a matching same-day calendar/astral cache entry when one exists.
4. On a cache miss, the library produces the requested month or range payload and the app stores it on disk.
5. The app attaches local notes and planting plans to the payload.
6. The frontend renders the month grid, 24-hour gradients, selected-day summary, planting plan, notes, and Sun/Moon position graphics.

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

Skyfield data lookup checks `BIODYNAMIC_SKYFIELD_DIR` first, then the user
cache. Missing ephemeris data is downloaded into the user cache rather than the
package directory.

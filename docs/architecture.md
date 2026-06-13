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
3. The library produces a month payload.
4. The app attaches local notes and planting plans to the payload.
5. The frontend renders the month grid, 24-hour gradients, selected-day summary, planting plan, notes, and Sun/Moon position graphics.

## Storage

- `~/.biodynamic_calendar/config.json`
- `~/.biodynamic_calendar/notes.json`
- `~/.biodynamic_calendar/plantings.json`

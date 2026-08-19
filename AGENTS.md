# AGENTS.md

Operational instructions for coding agents working in this repository. This
file is the repo-local source of truth for agent behavior and project-specific
requirements.

## Scope

- Applies to the entire repository unless a deeper `AGENTS.md` overrides it.
- Prefer these repo-specific instructions over generic coding-agent defaults.
- Confirm the target repository before editing when multiple project folders are
  open.
- Do not overwrite or revert user changes you did not make unless explicitly
  asked.

## Project Context

- Biodynamic Calendar is a standalone project extracted from Sensorius.
- It has two deliverables:
  - `biodynamic_calendar`: reusable Python library for biodynamic calendar and
    astral payloads.
  - `biodynamic_calendar_app`: local FastAPI browser app.
- Keep the project lightweight and local-first. Avoid introducing a database or
  service dependency unless explicitly justified.
- Local app state is stored under `~/.biodynamic_calendar/`.

## Runtime Architecture

Primary modules and assets:

- `src/biodynamic_calendar/core.py`: biodynamic calculations, ephemeris access,
  moon-sign segmentation, off-period overlays, hints, summaries, and payloads.
- `src/biodynamic_calendar/__init__.py`: public library exports only. Do not use
  this file as the version source.
- `src/biodynamic_calendar_app/app.py`: FastAPI app, routes, static/template
  mounting, and request wiring.
- `src/biodynamic_calendar_app/config_store.py`: local JSON-backed settings,
  location detection, notes, and planting storage.
- `templates/index.html`: standalone app UI and client-side behavior.
- `static/app.css`: app styling.
- `tests/`: pytest coverage for core behavior, app API compatibility, and
  config storage.

## Storage Requirements

Canonical local app files:

- `~/.biodynamic_calendar/config.json`
- `~/.biodynamic_calendar/notes.json`
- `~/.biodynamic_calendar/plantings.json`
- `~/.biodynamic_calendar/calendar_cache.json`

Rules:

- Keep local storage JSON-backed unless the user asks for a larger persistence
  change.
- Validate and normalize saved user data at the app/storage boundary.
- Preserve compatibility with existing config and notes files.
- Do not commit host-specific runtime state from `~/.biodynamic_calendar/`.

## Code Generation Rules

- Keep edits minimal, targeted, and easy to review.
- Do not reformat unrelated code.
- Prefer clear, explicit functions over abstraction for its own sake.
- Preserve the current public library API unless the user requests a breaking
  change.
- Keep FastAPI handlers thin where practical; move reusable behavior into
  supporting modules.
- Avoid blocking operations inside async handlers unless they are already part
  of the existing local-file workflow.
- Prefer the Python standard library unless a dependency is clearly justified.
- Do not upgrade major dependencies without explicit discussion.
- Add focused tests when behavior changes.
- Update docs when user-facing behavior, storage files, or setup expectations
  change.

## Frontend Rules

- Keep the app as a usable tool, not a marketing page.
- Match the existing quiet, dense, panel-based interface.
- Ensure text fits on desktop and mobile.
- Use existing HTML/CSS patterns before adding new UI structure.
- If UI behavior changes, verify the page loads locally when browser tooling is
  available; otherwise smoke test the relevant HTTP/API paths and state the
  limitation.

## Testing And Verification

Prefer focused verification first.

Common commands:

```bash
pytest -q
```

Useful local run command:

```bash
PYTHONPATH=src uvicorn biodynamic_calendar_app.app:app --host 127.0.0.1 --port 8765
```

Default local URL:

```text
http://127.0.0.1:8765
```

When changes affect runtime behavior, state which path was exercised, such as
core library tests, FastAPI route smoke tests, or local UI checks.

### Host-Side Pull Request Gate

- GitHub does not run the Playwright suite. Before committing work intended for
  a pull request, run `npm ci` when JavaScript dependencies are not current,
  install Chromium with `npx playwright install chromium` when it is not
  already available, and run `npm run test:e2e` on the development host.
- Do not create the commit until the Playwright check passes. If the check
  cannot run because of a host limitation, stop before committing and report
  the limitation explicitly.
- Keep the Playwright smoke test local to the FastAPI app; it must not depend on
  public websites or a GitHub Actions runner.

## Versioning Rule

When you make a code or repository content change, update `[project].version` in
`pyproject.toml` using:

```text
v0.<year>.<doy>.<x>
```

- `<year>`: 2-digit year.
- `<doy>`: 3-digit day of year.
- `<x>`: per-day incrementing patch counter.

Rule:

1. Read the current version from `[project].version` in `pyproject.toml`.
2. If `<year>` and `<doy>` match today, increment `<x>` by 1.
3. If the day changed, reset `<x>` to `1`.
4. If the current version does not use this format, initialize it for today with
   `<x>` set to `1`.
5. Preserve zero padding.
6. Only update the version string, not unrelated lines.

Example:

- `v0.26.057.2` becomes `v0.26.057.3` on the same day.
- `v0.26.057.2` becomes `v0.26.058.1` on the next day.

Do not store or update the project version in `src/biodynamic_calendar/__init__.py`.

## Agent Output Expectations

When making changes, summarize:

- What changed.
- What was verified.
- Any residual risk or unverified area.
- The version update in `pyproject.toml`.

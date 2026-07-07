# Contributing

Thanks for your interest in improving Biodynamic Calendar.

Biodynamic Calendar is a lightweight, local-first Python project with two
deliverables:

- `biodynamic_calendar`: a reusable library for biodynamic calendar and astral
  payloads.
- `biodynamic_calendar_app`: a local FastAPI browser app.

The project is intentionally small. Contributions are welcome when they keep the
tool reliable, understandable, and easy to run locally.

## Project Priorities

- Keep the app local-first.
- Preserve JSON-backed local storage unless a larger persistence change has
  been discussed first.
- Preserve the public library API unless a breaking change has been explicitly
  accepted.
- Prefer the Python standard library unless a dependency is clearly justified.
- Keep the browser UI quiet, dense, and tool-focused.
- Keep changes small enough to review.

## Before Opening a Pull Request

Open an issue first for:

- New features.
- Architecture changes.
- Public API changes.
- Storage format changes.
- Dependency additions or major dependency upgrades.
- UI rewrites.
- Performance-sensitive calendar or ephemeris changes.
- Anything that touches deployment or installer behavior across platforms.

Small bug fixes, documentation fixes, focused tests, and narrow compatibility
fixes may be submitted directly as pull requests.

Large pull requests without prior discussion may be closed even if the idea is
reasonable. This keeps review time focused on work that fits the project.

## Development Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest -q
```

Run the local app with:

```bash
PYTHONPATH=src uvicorn biodynamic_calendar_app.app:app --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

## Project Layout

- `src/biodynamic_calendar/core.py`: biodynamic calculations, ephemeris access,
  moon-sign segmentation, overlays, hints, summaries, and payloads.
- `src/biodynamic_calendar/__init__.py`: public library exports only.
- `src/biodynamic_calendar_app/app.py`: FastAPI routes, static/template
  mounting, and request wiring.
- `src/biodynamic_calendar_app/config_store.py`: JSON-backed settings, location
  detection, notes, and planting storage.
- `templates/index.html`: app UI and client-side behavior.
- `static/app.css`: app styling.
- `tests/`: pytest coverage.

## Local Storage

The standalone app stores runtime state under `~/.biodynamic_calendar/`:

- `config.json`
- `notes.json`
- `plantings.json`
- `calendar_cache.json`

Do not commit host-specific runtime state. Changes that read or write these
files must validate and normalize user data at the app or storage boundary and
must preserve compatibility with existing files.

## Coding Guidelines

- Keep edits minimal and targeted.
- Do not reformat unrelated code.
- Prefer clear functions over premature abstraction.
- Keep FastAPI handlers thin where practical.
- Avoid blocking operations in async handlers unless they are already part of
  the existing local-file workflow.
- Keep dependency changes rare and justified.
- Update docs when user-facing behavior, storage files, setup, or deployment
  expectations change.
- Do not use `src/biodynamic_calendar/__init__.py` as the version source.

## Frontend Guidelines

- Keep the UI a usable tool, not a marketing page.
- Match the existing panel-based interface.
- Ensure text fits on desktop and mobile.
- Use existing HTML and CSS patterns before adding new structure.
- When UI behavior changes, verify the page loads locally when practical.

## Testing

Run focused tests for the area you changed. For most changes, start with:

```bash
pytest -q
```

If you change runtime behavior, also describe the exercised path in the pull
request, such as:

- Core library tests.
- FastAPI route smoke tests.
- Local browser UI check.
- Installer or deployment script test.

## Version Updates

Code or repository-content changes must update `[project].version` in
`pyproject.toml` using this format:

```text
v0.<year>.<doy>.<x>
```

Use the two-digit year, three-digit day of year, and a per-day patch counter.
Increment `<x>` when the current version is already from today; otherwise reset
`<x>` to `1`. Only update the version string.

## Pull Request Expectations

Pull requests should include:

- A concise summary of what changed.
- The reason the change is needed.
- Tests or checks performed.
- Screenshots for visible UI changes when practical.
- Documentation updates when behavior or setup changes.

Pull requests should not include:

- Formatting-only churn mixed with functional changes.
- Broad rewrites without an accepted issue.
- Dependency churn without justification.
- Generated local runtime files.
- Unrelated cleanup.

## Maintainer Review Policy

The maintainer may close pull requests that are out of scope, too broad to
review, missing basic tests, repeatedly failing CI without follow-up, or not
aligned with the local-first goals of the project.

That is not a judgment on the contributor. It is how this project stays small
enough to maintain.

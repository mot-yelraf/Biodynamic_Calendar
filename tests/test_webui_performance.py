from __future__ import annotations

import re
import time
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path

from fastapi.testclient import TestClient

from biodynamic_calendar import BiodynamicConfig
from biodynamic_calendar_app.config_store import ConfigStore, DetectedLocation


CFG = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")


class FakeStore:
    def __init__(self) -> None:
        self.plantings = [
            {
                "id": "tomato",
                "name": "Tomato",
                "start_method": "seed",
                "start_date": "2026-06-01",
                "expected_harvest_date": "2026-08-15",
                "plant_part": "Fruit",
            }
        ]

    def load(self) -> BiodynamicConfig:
        return CFG

    def load_location(self) -> DetectedLocation:
        return DetectedLocation(config=CFG, source="manual")

    def load_notes(self) -> dict[str, str]:
        return {"2026-06-13": "Inspect beds."}

    def load_plantings(self) -> list[dict[str, object]]:
        return list(self.plantings)


def fake_month_payload(anchor: date | None = None) -> dict[str, object]:
    month_start = (anchor or date(2026, 6, 1)).replace(day=1)
    leading_days = (month_start.weekday() + 1) % 7
    days = []
    for offset in range(42):
        current = month_start + timedelta(days=offset - leading_days)
        in_month = current.month == month_start.month
        days.append(
            {
                "date": current.isoformat(),
                "day": current.day,
                "in_month": in_month,
                "is_today": current == date(2026, 6, 13),
                "dominant_sign": "Taurus",
                "dominant_sign_abbr": "Tau",
                "dominant_element": "Earth",
                "dominant_plant_part": "Root",
                "dominant_color": "#7a5417",
                "dominant_accent": "#7a5417",
                "moon_direction": "ascending",
                "segments": [
                    {
                        "start": "00:00",
                        "end": "24:00",
                        "sign": "Taurus",
                        "plant_part": "Root",
                        "accent": "#7a5417",
                    }
                ],
            }
        )
    return {
        "ok": True,
        "month_label": month_start.strftime("%B %Y"),
        "weekday_labels": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "current": {"sign": "Taurus", "element": "Earth", "plant_part": "Root"},
        "upcoming": [],
        "calendar": days,
    }


def test_future_calendar_range_endpoint_has_stable_webui_budget(monkeypatch):
    app_module = import_module("biodynamic_calendar_app.app")
    calls: list[tuple[date | None, int]] = []

    def fake_range(anchor, *, months, config):
        calls.append((anchor, months))
        return {
            "ok": True,
            "months_requested": months,
            "months": [fake_month_payload(anchor + timedelta(days=idx * 32)) for idx in range(months)],
        }

    monkeypatch.setattr(app_module, "store", FakeStore())
    monkeypatch.setattr(app_module, "get_biodynamic_calendar_range", fake_range)

    client = TestClient(app_module.create_app())
    started = time.perf_counter()
    resp = client.get("/api/calendar-range?start=2026-06&months=13")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 200
    assert resp.json()["months_requested"] == 13
    assert calls == [(date(2026, 6, 1), 13)]
    assert elapsed_ms < 250


def test_calendar_endpoints_reuse_disk_cache(monkeypatch, tmp_path):
    app_module = import_module("biodynamic_calendar_app.app")
    store = ConfigStore(root=tmp_path)
    store.save(CFG)
    calendar_calls: list[date | None] = []
    astro_calls = 0
    range_calls: list[tuple[date | None, int]] = []

    def fake_calendar(anchor, *, config):
        calendar_calls.append(anchor)
        return fake_month_payload(anchor)

    def fake_astro(*, config):
        nonlocal astro_calls
        astro_calls += 1
        return {"ok": True, "moon_phase_label": "Waning Crescent"}

    def fake_range(anchor, *, months, config):
        range_calls.append((anchor, months))
        return {
            "ok": True,
            "months_requested": months,
            "months": [fake_month_payload(anchor + timedelta(days=idx * 32)) for idx in range(months)],
        }

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "get_biodynamic_payload", fake_calendar)
    monkeypatch.setattr(app_module, "get_astro_payload", fake_astro)
    monkeypatch.setattr(app_module, "get_biodynamic_calendar_range", fake_range)

    client = TestClient(app_module.create_app())
    for _ in range(2):
        resp = client.get("/api/calendar?month=2026-06")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    for _ in range(2):
        resp = client.get("/api/calendar-range?start=2026-06&months=13")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    assert calendar_calls == [date(2026, 6, 1)]
    assert astro_calls == 1
    assert range_calls == [(date(2026, 6, 1), 13)]
    assert store.calendar_cache_path.exists()


def test_bd_hint_month_request_budget_is_bounded(monkeypatch):
    app_module = import_module("biodynamic_calendar_app.app")
    calls: list[date] = []

    def fake_summary(summary_date, *, config, crop_stage=None, plantings=None):
        calls.append(summary_date)
        assert plantings and plantings[0]["name"] == "Tomato"
        return f"Biodynamic Hints\nSuggestion: {summary_date.isoformat()}"

    monkeypatch.setattr(app_module, "store", FakeStore())
    monkeypatch.setattr(app_module, "get_daily_summary", fake_summary)

    client = TestClient(app_module.create_app())
    started = time.perf_counter()
    for day in range(1, 31):
        resp = client.get(f"/api/daily-summary?day=2026-06-{day:02d}")
        assert resp.status_code == 200
        assert resp.json()["summary"].startswith("Biodynamic Hints")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert calls == [date(2026, 6, day) for day in range(1, 31)]
    assert elapsed_ms < 500


def test_calendar_month_endpoint_has_stable_navigation_budget(monkeypatch):
    app_module = import_module("biodynamic_calendar_app.app")
    calendar_calls: list[date | None] = []
    astro_calls = 0

    def fake_calendar(anchor, *, config):
        calendar_calls.append(anchor)
        return fake_month_payload(anchor)

    def fake_astro(*, config):
        nonlocal astro_calls
        astro_calls += 1
        return {"ok": True, "moon_phase_label": "Waning Crescent"}

    monkeypatch.setattr(app_module, "store", FakeStore())
    monkeypatch.setattr(app_module, "get_biodynamic_payload", fake_calendar)
    monkeypatch.setattr(app_module, "get_astro_payload", fake_astro)

    client = TestClient(app_module.create_app())
    started = time.perf_counter()
    for month in ["2026-05", "2026-06", "2026-07"]:
        resp = client.get(f"/api/calendar?month={month}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert calendar_calls == [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]
    assert astro_calls == 3
    assert elapsed_ms < 300


def test_webui_uses_client_caches_for_future_calendar_and_bd_hints():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert "rangeCache: Object.create(null)" in template
    assert "summaryCache: Object.create(null)" in template
    assert "summaryRequests: Object.create(null)" in template
    assert "function promoteCachedMonth(monthKey" in template
    assert "async function fetchDailySummary(dayIso)" in template
    assert "state.summaryCache[dayIso]" in template
    assert "state.rangeCache[requestedMonth]" in template
    assert "const cached = !options.force && state.rangeCache[requestedMonth];" in template
    assert "const summary = await fetchDailySummary(day.date);" in template


def test_webui_navigation_tries_cached_month_before_fetching():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert re.search(
        r"function navigateCalendarMonth\(delta\).*?if \(!promoteCachedMonth\(targetMonth\)\).*?void loadCalendar\(targetMonth\);",
        template,
        re.S,
    )
    assert re.search(
        r"rangeEl\.querySelectorAll\(\"\.mini-day\"\).*?if \(!promoteCachedMonth\(month, dateIso\)\).*?void loadCalendar\(month, dateIso\);",
        template,
        re.S,
    )

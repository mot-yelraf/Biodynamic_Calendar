from datetime import date, datetime, time, timedelta
from importlib import import_module
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from biodynamic_calendar import BiodynamicConfig, get_biodynamic_calendar_range, get_hint_lines_for_day
from biodynamic_calendar import core


def test_sign_color_metadata_matches_sensorius_palette():
    expected = {
        "Ari": ("#f19707", "#d64b3b"),
        "Tau": ("#e5b172", "#644817"),
        "Gem": ("#F7E605", "#C4DCF8"),
        "Cnc": ("#277A00", "#2f6eb8"),
    }
    for abbr, colors in expected.items():
        meta = core._sign_meta(core._SIGN_INDEX_BY_ABBR[abbr])
        assert (meta["color"], meta["accent"]) == colors


def test_constellation_aliases_map_to_biodynamic_zodiac():
    assert core._biodynamic_sign_index_for_constellation("Oph") == core._SIGN_INDEX_BY_ABBR["Sco"]
    assert core._biodynamic_sign_index_for_constellation("Cet") == core._SIGN_INDEX_BY_ABBR["Psc"]
    assert core._biodynamic_sign_index_for_constellation("Aur") == core._SIGN_INDEX_BY_ABBR["Tau"]
    assert core._biodynamic_sign_index_for_constellation("Ori") == core._SIGN_INDEX_BY_ABBR["Tau"]
    assert core._biodynamic_sign_index_for_constellation("Sex") == core._SIGN_INDEX_BY_ABBR["Leo"]


def test_day_rows_include_lunar_fields_and_off_overlay_metadata(monkeypatch):
    tzinfo = ZoneInfo("America/Denver")
    start_day = date(2026, 3, 1)
    range_start = datetime.combine(start_day, time.min, tzinfo=tzinfo)

    def fake_split_segments(start_local, end_local, ts, eph, constellation_at):
        return [core._Segment(start_local, end_local, core._SIGN_INDEX_BY_ABBR["Ari"])]

    def fake_off_intervals(start_local, end_local, ts, eph):
        return [
            core._Interval(range_start + timedelta(hours=9), range_start + timedelta(hours=11), "lunar_node"),
            core._Interval(range_start + timedelta(hours=13), range_start + timedelta(hours=15), "perigee"),
            core._Interval(range_start + timedelta(hours=17), range_start + timedelta(hours=19), "apogee"),
        ]

    monkeypatch.setattr(core, "_split_segments", fake_split_segments)
    monkeypatch.setattr(core, "_build_off_intervals", fake_off_intervals)
    monkeypatch.setattr(core, "_moon_direction", lambda *args: "ascending")

    rows, _segments = core._build_day_rows(
        start_day,
        42,
        tzinfo,
        None,
        None,
        None,
        range_start,
        in_month_for=3,
    )

    assert len(rows) == 42
    first = rows[0]
    assert first["moon_direction"] == "ascending"
    assert first["lunar_node"] is True
    assert first["perigee"] is True
    assert first["apogee"] is True
    assert {event["type"] for event in first["lunar_events"]} == {"lunar_node", "perigee", "apogee"}
    off_segments = [seg for seg in first["segments"] if seg["kind"] == "off"]
    assert {seg["off_kind"] for seg in off_segments} == {"lunar_node", "perigee"}
    assert all(seg["color"] == "#5f6770" and seg["accent"] == "#d7dbe0" for seg in off_segments)


def test_day_rows_label_rest_when_off_overlay_is_the_longest_visible_segment(monkeypatch):
    tzinfo = ZoneInfo("America/Denver")
    start_day = date(2026, 3, 1)
    range_start = datetime.combine(start_day, time.min, tzinfo=tzinfo)

    monkeypatch.setattr(
        core,
        "_split_segments",
        lambda start_local, end_local, *_args: [
            core._Segment(start_local, end_local, core._SIGN_INDEX_BY_ABBR["Cnc"])
        ],
    )
    monkeypatch.setattr(
        core,
        "_build_off_intervals",
        lambda *_args: [core._Interval(range_start + timedelta(hours=5), range_start + timedelta(hours=19), "perigee")],
    )
    monkeypatch.setattr(core, "_moon_direction", lambda *_args: "ascending")

    rows, _segments = core._build_day_rows(start_day, 1, tzinfo, None, None, None, range_start)

    assert rows[0]["dominant_sign"] == "Rest"
    assert rows[0]["dominant_sign_abbr"] == ""
    assert rows[0]["dominant_element"] == "Pause"
    assert rows[0]["dominant_plant_part"] == "Rest"
    assert rows[0]["dominant_color"] == "#5f6770"
    assert rows[0]["dominant_accent"] == "#d7dbe0"


def test_calendar_range_returns_13_month_anchors(monkeypatch):
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")
    calls = []

    def fake_day_rows(start_day, day_count, tzinfo, ts, eph, constellation_at, now_local, *, in_month_for=None):
        rows = [
            {
                "date": (start_day + timedelta(days=offset)).isoformat(),
                "day": (start_day + timedelta(days=offset)).day,
                "in_month": True,
                "segments": [],
            }
            for offset in range(day_count)
        ]
        return rows, []

    def fake_payload_from_days(target_date, month_days, **kwargs):
        calls.append(target_date)
        return {
            "ok": True,
            "month_label": target_date.strftime("%B %Y"),
            "calendar": [{"date": target_date.isoformat(), "in_month": True}],
        }

    monkeypatch.setattr(core, "_skyfield_runtime", lambda: (None, None, None, None))
    monkeypatch.setattr(core, "_build_day_rows", fake_day_rows)
    monkeypatch.setattr(core, "_build_current_segment_timeline", lambda *args: [])
    monkeypatch.setattr(core, "_calendar_payload_from_days", fake_payload_from_days)

    payload = get_biodynamic_calendar_range(date(2026, 5, 1), months=13, config=cfg)

    assert payload["ok"] is True
    assert payload["start_month"] == "2026-05"
    assert payload["months_requested"] == 13
    assert len(payload["months"]) == 13
    assert calls == [date(2026, month, 1) for month in range(5, 13)] + [date(2027, month, 1) for month in range(1, 6)]
    assert payload["months"][12]["calendar"][0]["date"] == "2027-05-01"


def test_hint_lines_cover_plant_parts_timing_and_state_overrides():
    expected_terms = {
        "Root": "root",
        "Leaf": "leaf",
        "Flower": "flower",
        "Fruit": "fruit",
    }
    for part, term in expected_terms.items():
        lines = get_hint_lines_for_day(
            {
                "dominant_plant_part": part,
                "dominant_sign": "Aries",
                "moon_direction": "ascending",
                "lunar_node": True,
                "perigee": True,
                "apogee": True,
            },
            crop_stage="harvest",
            plant_state={"stress": True, "vpd": 2.1},
        )
        body = "\n".join(lines).lower()
        assert term in body
        assert "ascending moon" in body
        assert "lunar node" in body
        assert "perigee" in body
        assert "apogee" in body
        assert "vpd is above 1.8" in body
        assert core._GROUNDING_REMINDER.lower() in body


def test_hint_lines_use_configured_plantings():
    planting = {
        "name": "Tomato",
        "variety": "Brandywine",
        "plant_part": "Fruit",
        "start_method": "seed",
        "start_date": "2026-03-01",
        "expected_harvest_date": "2026-05-20",
        "attributes": "Trellis after transplant.",
    }

    start_lines = get_hint_lines_for_day(
        {
            "date": "2026-03-01",
            "dominant_plant_part": "Fruit",
            "dominant_sign": "Aries",
        },
        plantings=[planting],
    )
    start_body = "\n".join(start_lines)
    assert "Sow Tomato (Brandywine)" in start_body
    assert "Fruit focus aligns" in start_body
    assert "Plant Attributes" in start_body

    harvest_lines = get_hint_lines_for_day(
        {
            "date": "2026-05-20",
            "dominant_plant_part": "Leaf",
            "dominant_sign": "Cancer",
        },
        plantings=[planting],
    )
    harvest_body = "\n".join(harvest_lines)
    assert "expected harvest date" in harvest_body
    assert "Fruit focus does not match this Leaf day" in harvest_body


def test_hint_lines_use_cannabis_immature_mature_harvest_stages():
    planting = {
        "name": "Cannabis",
        "variety": "Blue Dream",
        "plant_type": "Cannabis",
        "plant_part": "Flower",
        "start_method": "transplant",
        "start_date": "2026-06-01",
        "expected_harvest_date": "2026-08-01",
    }

    immature_lines = get_hint_lines_for_day(
        {
            "date": "2026-06-10",
            "dominant_plant_part": "Flower",
            "dominant_sign": "Libra",
        },
        plantings=[planting],
    )
    immature_body = "\n".join(immature_lines)
    assert "immature" in immature_body
    assert "forcing flower-stage decisions too early" in immature_body

    mature_lines = get_hint_lines_for_day(
        {
            "date": "2026-06-20",
            "dominant_plant_part": "Flower",
            "dominant_sign": "Libra",
        },
        plantings=[planting],
    )
    mature_body = "\n".join(mature_lines)
    assert "mature stage" in mature_body
    assert "flower harvest, aroma checks" in mature_body

    harvest_lines = get_hint_lines_for_day(
        {
            "date": "2026-08-01",
            "dominant_plant_part": "Flower",
            "dominant_sign": "Libra",
        },
        plantings=[planting],
    )
    assert "expected harvest date" in "\n".join(harvest_lines)


def test_template_includes_sun_moon_position_overlay():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    javascript = Path("static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("static/app.css").read_text(encoding="utf-8")

    assert "Sun/Moon Position" in template
    assert "Sun Position" in template
    assert "Moon Position" in template
    assert "id=\"sunMoonPositionPanel\"" in template
    assert "id=\"moonPhasePanel\"" in template
    assert "class=\"moon-body\" title=\"29 day Sun/Moon position and phase\"" in template
    assert "id=\"sunMoon29Canvas\" width=\"1120\" height=\"220\"" in template
    assert "id=\"moonAxisRiseStat\"" in template
    assert "id=\"moonAxisSetStat\"" in template
    assert "function updateSunMoonPositionTimes(astro)" in javascript
    assert "function drawSunMoon29Day(astro)" in javascript
    assert "function openSunMoon29Day()" in javascript
    assert "function isSunMoon29Trigger(target)" in javascript
    assert "target.closest(\"#sunMoonPositionPanel\") || target.closest(\"#moonPhasePanel\")" in javascript
    assert "target.closest(\"[data-moon-view]\")" in javascript
    assert "29 Day Sun/Moon Position/Phase" in template
    assert "moonPositionRiseStat" not in template
    assert "moonPositionSetStat" not in template
    assert "drawTimeLabel(astro.sunrise" not in template
    assert "bezierCurveTo" in javascript
    assert "class=\"app-version\"" in template
    assert "Version {{ app_version }}" in template
    assert 'class="title-version">{{ app_version }}</span>' in template
    assert ".bio-day.out .day-number" in stylesheet
    assert "filter: saturate(0.42)" not in stylesheet
    assert "const yBase = yForElev(0);" in javascript
    assert "const elevRange = Math.max(1, elevMax - elevMin);" in javascript
    assert "const sinusoidalScale = (ratio) => 0.5 - (0.5 * Math.cos" in javascript
    assert "ctx.fillRect(0, 0, w, Math.max(1, yBase));" in javascript
    assert "ctx.fillRect(0, pad.top, cw, Math.max(1, yBase - pad.top));" in javascript
    assert "class=\"calendar-plan\"" in template
    assert "Twelve-Month Overview" in template
    assert 'class="standalone-app-header"' in template
    assert 'class="calendar-legend"' in template
    assert 'class="calendar-legend range-legend" aria-label="Twelve-month calendar legend"' in template
    assert 'class="panel day-inspector"' in template
    assert 'id="plantingEditor"' in template
    assert "class=\"loading-spinner\"" in javascript
    assert "const futureMonths = months.slice(1, 13);" in javascript
    assert "class=\"note-actions\"" in template
    assert "id=\"printBtn\"" in template
    assert "id=\"printReport\"" in template
    assert "function printCurrentMonthReport()" in javascript
    assert "function buildPrintReport(payload, hints)" in javascript
    assert "function monthlyPrintHints(payload)" in javascript
    assert "BD Hints for ${esc(selectedMonth)}" in javascript
    assert "Plantings" in template
    assert "All Saved Plantings" in javascript
    assert "class=\"planting-scroll\"" in javascript
    assert "class=\"planting-relevant\"" not in javascript
    assert "function plantingsForDate" not in javascript
    assert ">Note</summary>" in template
    assert "window.print();" in javascript

    css = Path("static/app.css").read_text(encoding="utf-8")
    assert ".planting-scroll" in css
    assert ".details {" in css
    assert "position: sticky;" in css
    assert "body.sensorius-launch .standalone-app-header" in css
    assert ".guidance-group.warning" in css
    assert ".moon-phase-panel .moon-body" in css
    assert "align-items: flex-start;" in css


def test_calendar_daily_summary_and_range_api_stay_backward_compatible(monkeypatch):
    app_module = import_module("biodynamic_calendar_app.app")
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")

    class FakeStore:
        def __init__(self):
            self.plantings = [
                {
                    "id": "tomato",
                    "name": "Tomato",
                    "plant_part": "Fruit",
                    "start_method": "seed",
                    "start_date": "2026-05-01",
                }
            ]

        def load(self):
            return cfg

        def load_notes(self):
            return {"2026-05-01": "local note"}

        def load_plantings(self):
            return list(self.plantings)

        def save(self, config):
            return None

        def save_note(self, day_iso, note):
            return None

        def save_planting(self, planting):
            row = dict(planting)
            row.setdefault("id", "saved")
            self.plantings = [row]
            return row

        def delete_planting(self, planting_id):
            before = len(self.plantings)
            self.plantings = [row for row in self.plantings if row.get("id") != planting_id]
            return len(self.plantings) != before

    calendar_payload = {
        "ok": True,
        "month_label": "May 2026",
        "weekday_labels": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "current": {},
        "upcoming": [],
        "calendar": [{"date": "2026-05-01", "day": 1, "in_month": True, "segments": []}],
    }

    monkeypatch.setattr(app_module, "store", FakeStore())
    monkeypatch.setattr(app_module, "get_biodynamic_payload", lambda anchor, *, config: dict(calendar_payload))
    monkeypatch.setattr(app_module, "get_astro_payload", lambda *, config: {"ok": True})
    monkeypatch.setattr(
        app_module,
        "get_biodynamic_calendar_range",
        lambda anchor, *, months, config: {"ok": True, "months_requested": months, "months": [dict(calendar_payload) for _ in range(months)]},
    )
    monkeypatch.setattr(
        app_module,
        "get_daily_summary",
        lambda summary_date, *, config, crop_stage=None, plantings=None: "Biodynamic Hints\nSuggestion: test",
    )

    client = TestClient(app_module.create_app())

    calendar_resp = client.get("/api/calendar?month=2026-05")
    assert calendar_resp.status_code == 200
    calendar_json = calendar_resp.json()
    assert calendar_json["ok"] is True
    assert calendar_json["notes"]["2026-05-01"] == "local note"
    assert calendar_json["plantings"][0]["name"] == "Tomato"
    assert calendar_json["astro"]["ok"] is True

    summary_resp = client.get("/api/daily-summary?day=2026-05-01")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["summary"].startswith("Biodynamic Hints")

    range_resp = client.get("/api/calendar-range?start=2026-05&months=13")
    assert range_resp.status_code == 200
    range_json = range_resp.json()
    assert range_json["ok"] is True
    assert range_json["months_requested"] == 13
    assert len(range_json["months"]) == 13

    plantings_resp = client.get("/api/plantings")
    assert plantings_resp.status_code == 200
    assert plantings_resp.json()["plantings"][0]["id"] == "tomato"

    save_resp = client.post(
        "/api/planting",
        json={"name": "Lettuce", "plant_part": "Leaf", "start_method": "transplant", "start_date": "2026-05-02"},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["plantings"][0]["name"] == "Lettuce"

    delete_resp = client.delete("/api/planting/saved")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


def test_sensorius_launch_mode_hides_top_row_cards(monkeypatch):
    app_module = import_module("biodynamic_calendar_app.app")
    cfg = BiodynamicConfig(latitude=39.7392, longitude=-104.9903, timezone_name="America/Denver")

    class FakeStore:
        def load(self):
            return cfg

        def load_notes(self):
            return {}

        def load_plantings(self):
            return []

    monkeypatch.setattr(app_module, "store", FakeStore())
    client = TestClient(app_module.create_app())

    direct_resp = client.get("/")
    sensorius_resp = client.get("/?source=sensorius")

    assert direct_resp.status_code == 200
    assert 'class=""' in direct_resp.text
    assert sensorius_resp.status_code == 200
    assert 'class="sensorius-launch"' in sensorius_resp.text

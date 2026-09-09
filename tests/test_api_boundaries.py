from importlib import import_module
from io import BytesIO
import sqlite3

from fastapi.testclient import TestClient
from PIL import Image

from biodynamic_calendar_app import config_store
from biodynamic_calendar_app.config_store import ConfigStore, MAX_NOTE_LENGTH, SensoriusSQLiteStore


app_module = import_module("biodynamic_calendar_app.app")


def _client(monkeypatch, tmp_path) -> tuple[TestClient, ConfigStore]:
    store = ConfigStore(root=tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    return TestClient(app_module.create_app()), store


def test_mutation_endpoints_reject_malformed_json_and_non_objects(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    for path in ("/api/config", "/api/note", "/api/planting"):
        malformed = client.post(path, content="{", headers={"Content-Type": "application/json"})
        non_object = client.post(path, json=[])
        assert malformed.status_code == 422
        assert non_object.status_code == 422


def test_config_endpoint_rejects_nan_without_persisting_it(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/config",
        content='{"latitude": NaN, "longitude": -108.2, "timezone_name": "America/Denver"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_config"
    assert not store.config_path.exists()


def test_note_endpoint_validates_date_and_size(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    invalid_date = client.post("/api/note", json={"date": "tomorrow", "note": "hello"})
    oversized = client.post("/api/note", json={"date": "2026-07-09", "note": "x" * (MAX_NOTE_LENGTH + 1)})
    valid = client.post("/api/note", json={"date": "2026-07-09", "note": "Inspect beds."})

    assert invalid_date.status_code == 422
    assert oversized.status_code == 422
    assert valid.status_code == 200
    assert store.load_notes() == {"2026-07-09": "Inspect beds."}


def test_json_note_failure_returns_503(monkeypatch, tmp_path):
    store = ConfigStore(root=tmp_path)

    def fail_write(*_args, **_kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(config_store, "_write_json_atomic", fail_write)
    client = TestClient(app_module.create_app(store=store))

    response = client.post("/api/note", json={"date": "2026-07-09", "note": "Inspect beds."})

    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "storage_unavailable"}


def test_sqlite_note_failure_returns_503(monkeypatch, tmp_path):
    store = SensoriusSQLiteStore(
        tmp_path / "sensorius_data.db",
        root=tmp_path / "json",
        import_local_json=False,
    )

    def fail_open():
        raise sqlite3.OperationalError("injected database failure")

    monkeypatch.setattr(store, "_open_conn", fail_open)
    client = TestClient(app_module.create_app(store=store))

    response = client.post("/api/note", json={"date": "2026-07-09", "note": "Inspect beds."})

    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "storage_unavailable"}


def test_appearance_endpoint_persists_manual_and_automatic_themes(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    manual = client.post("/api/appearance", json={"theme": "winter"})
    automatic = client.post("/api/appearance", json={"theme": "auto"})
    invalid = client.post("/api/appearance", json={"theme": "monsoon"})

    assert manual.status_code == 200
    assert manual.json()["resolved_theme"] == "winter"
    assert automatic.status_code == 200
    assert automatic.json()["theme"] == "auto"
    assert automatic.json()["resolved_theme"] in {"spring", "summer", "autumn", "winter"}
    assert invalid.status_code == 422
    assert store.load_appearance_theme() == "auto"


def test_index_loads_static_javascript_module(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    page = client.get("/")
    javascript = client.get("/static/app.js")
    favicon = client.get("/bd-calendar-favicon.svg")
    brand_icon = client.get("/static/bd-calendar-icon-512.svg")
    brand_icon_png = client.get("/static/bd-calendar-icon-512.png")
    moon_surface = client.get("/static/moon-surface.png")

    assert page.status_code == 200
    assert 'id="bd-calendar-bootstrap" type="application/json"' in page.text
    assert (
        '<link rel="icon" href="/bd-calendar-favicon.svg" type="image/svg+xml">'
        in page.text
    )
    assert page.text.count('rel="icon"') == 2
    assert (
        '<link rel="icon" href="/static/bd-calendar-icon-512.png" type="image/png" sizes="512x512">'
        in page.text
    )
    assert (
        '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v='
        in page.text
    )
    assert 'rel="stylesheet" href="/static/app.css?v=' in page.text
    assert 'type="module" src="/static/app.js?v=' in page.text
    assert "function loadCalendar" not in page.text
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert "Biodynamic Calendar app icon" in favicon.text
    assert 'viewBox="61 61 390 390"' in favicon.text
    assert brand_icon.status_code == 200
    assert brand_icon.headers["content-type"].startswith("image/svg+xml")
    assert brand_icon_png.status_code == 200
    assert brand_icon_png.headers["content-type"] == "image/png"
    with Image.open(BytesIO(brand_icon_png.content)) as icon:
        assert icon.format == "PNG"
        assert icon.size == (512, 512)
        icon.verify()
    assert moon_surface.status_code == 200
    assert moon_surface.headers["content-type"] == "image/png"
    assert 'document.getElementById("bd-calendar-bootstrap")' in javascript.text
    assert 'loadCalendar("")' in javascript.text


def test_apple_touch_icon_discovery_and_versioned_link(monkeypatch, tmp_path):
    from html.parser import HTMLParser

    class IconParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hrefs = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "link" and attrs.get("rel") == "apple-touch-icon":
                self.hrefs.append(attrs["href"])

    client, _store = _client(monkeypatch, tmp_path)
    parser = IconParser()
    parser.feed(client.get("/").text)
    assert len(parser.hrefs) == 1
    assert parser.hrefs[0].startswith("/apple-touch-icon.png?v=v0.")
    canonical = client.get(parser.hrefs[0]).content
    with Image.open(BytesIO(canonical)) as icon:
        assert icon.format == "PNG"
        assert icon.size == (180, 180)
        assert icon.mode == "RGB"
        # The artwork is present, with transparency flattened onto white.
        assert icon.getpixel((0, 0)) == (255, 255, 255)
        assert icon.getpixel((90, 90)) != (255, 255, 255)
    for path in (*parser.hrefs, "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-cache"
        assert response.content == canonical
        head = client.head(path)
        assert head.status_code == 200
        assert head.headers["content-type"] == "image/png"
        assert head.headers["content-length"] == str(len(canonical))
        assert head.content == b""


def test_android_manifest_and_icon_are_served(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)
    page = client.get("/")
    assert '<link rel="manifest" href="/static/manifest.json">' in page.text

    response = client.get("/static/manifest.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    manifest = response.json()
    assert manifest["name"] == "Biodynamic Calendar"
    assert manifest["short_name"] == "BD Calendar"
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert client.get(manifest["start_url"]).status_code == 200
    assert manifest["icons"]
    for entry in manifest["icons"]:
        icon_response = client.get(entry["src"])
        assert icon_response.status_code == 200
        assert icon_response.headers["content-type"] == entry["type"] == "image/png"
        assert entry["purpose"] == "any"
        with Image.open(BytesIO(icon_response.content)) as icon:
            assert entry["sizes"] == f"{icon.width}x{icon.height}"
            assert icon.width == icon.height == 512
            icon.verify()


def test_favicon_routes_serve_canonical_svg_for_get_and_head(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)
    report = client.get("/report")

    assert report.status_code == 200
    assert (
        '<link rel="icon" href="/bd-calendar-favicon.svg" type="image/svg+xml">'
        in report.text
    )

    for favicon_path in ("/favicon.svg", "/bd-calendar-favicon.svg"):
        response = client.get(favicon_path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.text == app_module.FAVICON_SVG
        assert "Biodynamic Calendar app icon" in response.text
        assert "<image" not in response.text
        assert "data:image" not in response.text

        response = client.head(favicon_path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.content == b""

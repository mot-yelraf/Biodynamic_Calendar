from importlib import import_module

from fastapi.testclient import TestClient

from biodynamic_calendar_app.config_store import ConfigStore, MAX_NOTE_LENGTH


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


def test_index_loads_static_javascript_module(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    page = client.get("/")
    javascript = client.get("/static/app.js")

    assert page.status_code == 200
    assert 'id="bd-calendar-bootstrap" type="application/json"' in page.text
    assert 'rel="stylesheet" href="/static/app.css?v=' in page.text
    assert 'type="module" src="/static/app.js?v=' in page.text
    assert "function loadCalendar" not in page.text
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert 'document.getElementById("bd-calendar-bootstrap")' in javascript.text
    assert 'loadCalendar("")' in javascript.text

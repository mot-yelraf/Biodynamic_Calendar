from __future__ import annotations

import io
import json
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from biodynamic_calendar import BiodynamicConfig
from biodynamic_calendar_app.config_store import ConfigStore
from biodynamic_calendar_app.theme_manager import ThemeManager, ThemeValidationError


app_module = import_module("biodynamic_calendar_app.app")


def _image_bytes(*, size: tuple[int, int] = (640, 360), color: str = "#497a50") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def test_theme_manager_creates_resolves_and_deletes_collection(tmp_path):
    manager = ThemeManager(tmp_path)

    created = manager.create_theme(
        name="My Farm",
        images=[
            {
                "name": "North Beds",
                "palette": "pale_sage",
                "content": _image_bytes(),
            }
        ],
    )

    assert created["name"] == "My Farm"
    assert created["images"][0]["name"] == "North Beds"
    assert created["images"][0]["selection"].startswith("custom:")
    assert manager.resolve(created["images"][0]["selection"])["palette"]["name"] == "Pale Sage"
    assert manager.style_values(created["images"][0]["selection"])["--theme-panel"] == "#e4f1e4"
    assert list((tmp_path / "theme_assets").glob("*/*.webp"))
    assert (tmp_path / "theme_settings" / "themes.json").is_file()
    assert (tmp_path / "theme_settings" / "themes.json.bak").is_file()

    assert manager.delete_theme(created["id"]) is True
    assert manager.list_themes() == []
    assert manager.delete_theme(created["id"]) is False


def test_theme_manager_rejects_unsafe_images_and_metadata(tmp_path):
    manager = ThemeManager(tmp_path)

    with pytest.raises(ThemeValidationError, match="at least 320 x 180"):
        manager.create_theme(
            name="Small",
            images=[{"name": "Tiny", "palette": "pale_sage", "content": _image_bytes(size=(100, 100))}],
        )

    with pytest.raises(ThemeValidationError, match="predefined palettes"):
        manager.create_theme(
            name="Unknown Palette",
            images=[{"name": "Beds", "palette": "neon", "content": _image_bytes()}],
        )

    assert manager.list_themes() == []
    assert list((tmp_path / "theme_assets").glob("*")) == []


def test_custom_selection_survives_config_save(tmp_path):
    store = ConfigStore(root=tmp_path)
    selection = f"custom:{'a' * 32}:{'b' * 32}"
    config = BiodynamicConfig(latitude=32.79, longitude=-108.2749, timezone_name="America/Denver")

    assert store.save_appearance_theme(selection) == selection
    store.save(config, source="manual")

    assert store.load_appearance_theme() == selection
    assert json.loads(store.config_path.read_text(encoding="utf-8"))["appearance_theme"] == selection


def test_custom_theme_api_and_read_only_builtin_options(monkeypatch, tmp_path):
    store = ConfigStore(root=tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    client = TestClient(app_module.create_app())

    created_response = client.post(
        "/api/themes",
        data={"name": "Kitchen Garden", "image_names": "Herb Beds", "palettes": "pale_earth"},
        files={"images": ("beds.png", _image_bytes(color="#8b704b"), "image/png")},
    )
    assert created_response.status_code == 200
    created = created_response.json()["theme"]
    selection = created["images"][0]["selection"]

    listed = client.get("/api/themes")
    assert listed.status_code == 200
    assert listed.json()["themes"][0]["name"] == "Kitchen Garden"
    assert any(item["id"] == "pale_earth" for item in listed.json()["palettes"])

    page = client.get("/")
    builtin_markup = page.text.split('id="customThemeCollections"', 1)[0]
    assert page.status_code == 200
    assert "Kitchen Garden" in page.text
    assert selection in page.text
    assert "custom-theme-delete" not in builtin_markup
    assert page.text.count("custom-theme-delete") == 1

    selected = client.post("/api/appearance", json={"theme": selection})
    assert selected.status_code == 200
    assert selected.json()["resolved_theme"] == "custom"
    assert selected.json()["style"]["--theme-panel"] == "#efe2c6"
    assert store.load_appearance_theme() == selection

    asset = client.get(created["images"][0]["thumbnail_url"])
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "image/webp"

    deleted = client.delete(f"/api/themes/{created['id']}")
    assert deleted.status_code == 200
    assert store.load_appearance_theme() == "auto"
    assert client.get("/api/themes").json()["themes"] == []


def test_custom_theme_api_rejects_invalid_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "store", ConfigStore(root=tmp_path))
    client = TestClient(app_module.create_app())

    response = client.post(
        "/api/themes",
        data={"name": "Broken", "image_names": "Not an image", "palettes": "pale_sage"},
        files={"images": ("broken.png", b"not an image", "image/png")},
    )

    assert response.status_code == 400
    assert "valid WebP, JPEG, or PNG" in response.json()["error"]

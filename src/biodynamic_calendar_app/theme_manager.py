"""Persist and resolve user-created Biodynamic Calendar themes."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_THEME_IMAGES = 5
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
OUTPUT_SIZE = (1920, 1080)
THUMBNAIL_SIZE = (480, 270)
CUSTOM_THEME_PREFIX = "custom:"

THEME_PALETTES = {
    "pale_sage": {
        "name": "Pale Sage",
        "panel": "#e4f1e4",
        "strong": "#f7fcf7",
        "soft": "#cfe2cf",
        "border": "#668366",
        "text": "#1d301f",
        "muted": "#49604c",
        "accent": "#477a50",
    },
    "pale_earth": {
        "name": "Pale Earth",
        "panel": "#efe2c6",
        "strong": "#fffaf1",
        "soft": "#dcc8a4",
        "border": "#8b704b",
        "text": "#2f2114",
        "muted": "#65513c",
        "accent": "#73522f",
    },
    "pale_water": {
        "name": "Pale Water",
        "panel": "#dcebf3",
        "strong": "#f8fcff",
        "soft": "#bfd8e6",
        "border": "#5f8298",
        "text": "#122633",
        "muted": "#385569",
        "accent": "#22658c",
    },
    "pale_sky": {
        "name": "Pale Sky",
        "panel": "#dfeaf8",
        "strong": "#f8fbff",
        "soft": "#c5d8ef",
        "border": "#6687ad",
        "text": "#142b43",
        "muted": "#425d79",
        "accent": "#356ea3",
    },
    "pale_blossom": {
        "name": "Pale Blossom",
        "panel": "#f1e1ed",
        "strong": "#fff8fd",
        "soft": "#dfc4d8",
        "border": "#95708b",
        "text": "#382033",
        "muted": "#6b4a62",
        "accent": "#8b4776",
    },
    "pale_fruit": {
        "name": "Pale Fruit",
        "panel": "#fde1d3",
        "strong": "#fff8f3",
        "soft": "#efc6b2",
        "border": "#a96d53",
        "text": "#3b1c12",
        "muted": "#704739",
        "accent": "#a64f31",
    },
    "warm_neutral": {
        "name": "Warm Neutral",
        "panel": "#ece7df",
        "strong": "#fffdf9",
        "soft": "#d8d0c4",
        "border": "#80766a",
        "text": "#302b25",
        "muted": "#5e574f",
        "accent": "#6d5d49",
    },
    "cool_neutral": {
        "name": "Cool Neutral",
        "panel": "#e4eaec",
        "strong": "#fbfdfe",
        "soft": "#cad5d9",
        "border": "#687b82",
        "text": "#203035",
        "muted": "#4b5e64",
        "accent": "#496f78",
    },
}


class ThemeValidationError(ValueError):
    """Report invalid custom-theme metadata or image content."""


def _clean_name(value: object, *, field: str) -> str:
    name = " ".join(str(value or "").strip().split())
    if not name:
        raise ThemeValidationError(f"{field} is required.")
    if len(name) > 60:
        raise ThemeValidationError(f"{field} must be 60 characters or fewer.")
    return name


def custom_theme_selection(theme_id: str, image_id: str) -> str:
    return f"{CUSTOM_THEME_PREFIX}{theme_id}:{image_id}"


def is_custom_theme_selection(value: object) -> bool:
    parts = str(value or "").split(":")
    return (
        len(parts) == 3
        and parts[0] == "custom"
        and all(
            len(part) == 32
            and all(character in "0123456789abcdef" for character in part)
            for part in parts[1:]
        )
    )


class ThemeManager:
    """Store custom collections beneath the app's local data directory."""

    _lock = threading.RLock()

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.settings_dir = self.root / "theme_settings"
        self.assets_dir = self.root / "theme_assets"
        self.manifest_path = self.settings_dir / "themes.json"

    def _load(self) -> dict:
        candidates = (self.manifest_path, self.manifest_path.with_suffix(".json.bak"))
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                if candidate.stat().st_size > 1024 * 1024:
                    continue
                document = json.loads(candidate.read_text(encoding="utf-8"))
                themes = document.get("themes") if isinstance(document, dict) else None
                if isinstance(themes, list):
                    return {"version": 1, "themes": themes}
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        return {"version": 1, "themes": []}

    def _write(self, document: dict) -> None:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.settings_dir,
                prefix=".themes.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            had_manifest = self.manifest_path.exists()
            if had_manifest:
                shutil.copy2(self.manifest_path, self.manifest_path.with_suffix(".json.bak"))
            os.replace(temporary_path, self.manifest_path)
            temporary_path = None
            if not had_manifest:
                shutil.copy2(self.manifest_path, self.manifest_path.with_suffix(".json.bak"))
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def palettes() -> list[dict[str, str]]:
        return [
            {"id": palette_id, **values}
            for palette_id, values in THEME_PALETTES.items()
        ]

    def list_themes(self) -> list[dict]:
        result = []
        for raw_theme in self._load().get("themes", []):
            if not isinstance(raw_theme, dict):
                continue
            theme_id = str(raw_theme.get("id") or "")
            if not _valid_id(theme_id):
                continue
            images = []
            for raw_image in raw_theme.get("images", []):
                if not isinstance(raw_image, dict):
                    continue
                image_id = str(raw_image.get("id") or "")
                filename = str(raw_image.get("file") or "")
                thumbnail = str(raw_image.get("thumbnail") or "")
                palette = str(raw_image.get("palette") or "")
                if not _valid_id(image_id) or palette not in THEME_PALETTES:
                    continue
                if Path(filename).name != filename or Path(thumbnail).name != thumbnail:
                    continue
                if not (self.assets_dir / theme_id / filename).is_file():
                    continue
                if not (self.assets_dir / theme_id / thumbnail).is_file():
                    continue
                images.append(
                    {
                        "id": image_id,
                        "name": str(raw_image.get("name") or "Custom Theme"),
                        "palette": palette,
                        "palette_name": THEME_PALETTES[palette]["name"],
                        "asset_url": f"/theme-assets/{theme_id}/{filename}",
                        "thumbnail_url": f"/theme-assets/{theme_id}/{thumbnail}",
                        "selection": custom_theme_selection(theme_id, image_id),
                    }
                )
            if images:
                result.append(
                    {
                        "id": theme_id,
                        "name": str(raw_theme.get("name") or "Custom Theme"),
                        "images": images,
                        "custom": True,
                    }
                )
        return result

    def resolve(self, selection: object) -> dict | None:
        raw = str(selection or "")
        if not is_custom_theme_selection(raw):
            return None
        _prefix, theme_id, image_id = raw.split(":")
        for theme in self.list_themes():
            if theme["id"] != theme_id:
                continue
            for image in theme["images"]:
                if image["id"] == image_id:
                    return {
                        "selection": raw,
                        "theme": theme,
                        "image": image,
                        "palette": dict(THEME_PALETTES[image["palette"]]),
                    }
        return None

    def normalize_selection(self, value: object, default: str = "auto") -> str:
        raw = str(value or "").strip().lower()
        if is_custom_theme_selection(raw):
            return raw if self.resolve(raw) else default
        return raw

    def style_values(self, selection: object) -> dict[str, str]:
        resolved = self.resolve(selection)
        if not resolved:
            return {}
        palette = resolved["palette"]
        image_url = resolved["image"]["asset_url"]
        return {
            "background-image": f"url('{image_url}')",
            "background-position": "center",
            "background-repeat": "no-repeat",
            "background-size": "cover",
            "background-attachment": "fixed",
            "--theme-panel": palette["panel"],
            "--theme-panel-strong": palette["strong"],
            "--theme-panel-soft": palette["soft"],
            "--theme-border": palette["border"],
            "--theme-ink": palette["text"],
            "--theme-muted": palette["muted"],
            "--theme-accent": palette["accent"],
            "--theme-button": palette["soft"],
            "--theme-lunar": palette["text"],
            "--theme-lunar-edge": palette["border"],
        }

    @staticmethod
    def style_attribute(values: dict[str, str]) -> str:
        return ";".join(f"{key}:{value}" for key, value in values.items())

    @staticmethod
    def _process_image(content: bytes, output_path: Path, thumbnail_path: Path) -> None:
        if not content:
            raise ThemeValidationError("Uploaded image is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ThemeValidationError("Each image must be 5 MB or smaller.")
        try:
            with Image.open(io.BytesIO(content)) as probe:
                if str(probe.format or "").upper() not in {"WEBP", "JPEG", "PNG"}:
                    raise ThemeValidationError("Only valid WebP, JPEG, or PNG images are supported.")
                width, height = probe.size
                if width < 320 or height < 180:
                    raise ThemeValidationError("Images must be at least 320 x 180 pixels.")
                if width * height > MAX_IMAGE_PIXELS:
                    raise ThemeValidationError("Image dimensions are too large.")
                if bool(getattr(probe, "is_animated", False)):
                    raise ThemeValidationError("Animated images are not supported.")
                probe.verify()
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                fitted = ImageOps.fit(image, OUTPUT_SIZE, method=Image.Resampling.LANCZOS)
                fitted.save(output_path, "WEBP", quality=84, method=4)
                thumbnail = ImageOps.fit(image, THUMBNAIL_SIZE, method=Image.Resampling.LANCZOS)
                thumbnail.save(thumbnail_path, "WEBP", quality=78, method=4)
        except ThemeValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ThemeValidationError("Only valid WebP, JPEG, or PNG images are supported.") from exc

    def create_theme(self, *, name: object, images: list[dict]) -> dict:
        theme_name = _clean_name(name, field="Theme name")
        if not 1 <= len(images) <= MAX_THEME_IMAGES:
            raise ThemeValidationError("Choose between one and five images.")
        theme_id = uuid4().hex
        theme_dir = self.assets_dir / theme_id
        created_images = []
        try:
            theme_dir.mkdir(parents=True, exist_ok=False)
            for upload in images:
                image_id = uuid4().hex
                image_name = _clean_name(upload.get("name"), field="Image name")
                palette = str(upload.get("palette") or "").strip().lower()
                if palette not in THEME_PALETTES:
                    raise ThemeValidationError("Choose one of the predefined palettes.")
                output_name = f"{image_id}.webp"
                thumbnail_name = f"{image_id}-thumb.webp"
                self._process_image(
                    bytes(upload.get("content") or b""),
                    theme_dir / output_name,
                    theme_dir / thumbnail_name,
                )
                created_images.append(
                    {
                        "id": image_id,
                        "name": image_name,
                        "palette": palette,
                        "file": output_name,
                        "thumbnail": thumbnail_name,
                    }
                )
            with self._lock:
                document = self._load()
                document["themes"].append(
                    {"id": theme_id, "name": theme_name, "images": created_images}
                )
                self._write(document)
        except Exception:
            shutil.rmtree(theme_dir, ignore_errors=True)
            raise
        return next(theme for theme in self.list_themes() if theme["id"] == theme_id)

    def delete_theme(self, theme_id: str) -> bool:
        safe_id = str(theme_id or "").strip().lower()
        if not _valid_id(safe_id):
            raise ThemeValidationError("Custom theme ID is invalid.")
        with self._lock:
            document = self._load()
            themes = document.get("themes", [])
            kept = [theme for theme in themes if str(theme.get("id") or "") != safe_id]
            if len(kept) == len(themes):
                return False
            document["themes"] = kept
            self._write(document)
        shutil.rmtree(self.assets_dir / safe_id, ignore_errors=True)
        return True


def _valid_id(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdef" for character in value)

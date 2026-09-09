"""Browser icon representations derived from the canonical app artwork."""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image


@lru_cache(maxsize=1)
def apple_touch_icon_png() -> bytes:
    """Return an opaque 180px Apple touch icon without duplicating the artwork."""
    source = Path(__file__).resolve().parents[2] / "static" / "bd-calendar-icon-512.png"
    with Image.open(source) as image:
        artwork = image.convert("RGBA").resize((180, 180), Image.Resampling.LANCZOS)
    icon = Image.new("RGB", artwork.size, "white")
    icon.paste(artwork, mask=artwork.getchannel("A"))
    output = BytesIO()
    icon.save(output, format="PNG")
    return output.getvalue()

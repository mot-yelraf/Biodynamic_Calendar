from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import biodynamic_calendar_app.desktop as desktop


def _png_alpha_bbox(png: bytes) -> tuple[int, int, int, int] | None:
    width, height = struct.unpack(">II", png[16:24])
    offset = 8
    compressed = bytearray()
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        if png[offset + 4 : offset + 8] == b"IDAT":
            compressed.extend(png[offset + 8 : offset + 8 + length])
        offset += length + 12

    encoded = zlib.decompress(compressed)
    stride = width * 4
    previous = bytearray(stride)
    alpha_points: list[tuple[int, int]] = []
    cursor = 0
    for y in range(height):
        filter_type = encoded[cursor]
        cursor += 1
        filtered = encoded[cursor : cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for index, value in enumerate(filtered):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                base = left + above - upper_left
                distances = (
                    abs(base - left),
                    abs(base - above),
                    abs(base - upper_left),
                )
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            row[index] = (value + predictor) & 0xFF
        for x in range(width):
            if row[x * 4 + 3]:
                alpha_points.append((x, y))
        previous = row
    if not alpha_points:
        return None
    xs, ys = zip(*alpha_points)
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


class FakeEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def _fake_webview(calls: list) -> tuple[SimpleNamespace, SimpleNamespace]:
    window = SimpleNamespace(
        events=SimpleNamespace(shown=FakeEvent()),
        native=SimpleNamespace(Icon=None),
    )

    def create_window(*args, **kwargs):
        calls.append(("create", args, kwargs))
        return window

    webview = SimpleNamespace(
        create_window=create_window,
        start=lambda *args, **kwargs: calls.append(("start", args, kwargs)),
    )
    return webview, window


def test_desktop_icons_are_present() -> None:
    assert desktop.DESKTOP_ICON_PATH.is_file()
    assert desktop.WINDOWS_ICON_PATH.is_file()
    png = desktop.DESKTOP_ICON_PATH.read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png[25] == 6
    assert _png_alpha_bbox(png) == (25, 25, 486, 486)
    assert desktop.WINDOWS_ICON_PATH.read_bytes()[:4] == b"\x00\x00\x01\x00"
    icon_count = struct.unpack("<H", desktop.WINDOWS_ICON_PATH.read_bytes()[4:6])[0]
    assert icon_count >= 7


def test_default_window_is_1600_by_1000(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BD_CALENDAR_GUI_WIDTH",
        "BD_CALENDAR_GUI_HEIGHT",
        "BD_CALENDAR_GUI_X",
        "BD_CALENDAR_GUI_Y",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop._window_geometry() == {
        "width": 1600,
        "height": 1000,
        "x": None,
        "y": None,
    }


def test_geometry_overrides_are_clamped_to_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BD_CALENDAR_GUI_WIDTH", "1800")
    monkeypatch.setenv("BD_CALENDAR_GUI_HEIGHT", "1200")
    monkeypatch.setenv("BD_CALENDAR_GUI_X", "12")
    monkeypatch.setenv("BD_CALENDAR_GUI_Y", "40")
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: (1366, 768))

    assert desktop._window_geometry() == {
        "width": 1366,
        "height": 768,
        "x": 12,
        "y": 40,
    }


def test_start_server_uses_current_venv_and_lan_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setenv("BD_CALENDAR_HOST", "0.0.0.0")
    monkeypatch.setenv("BD_CALENDAR_PORT", "8877")
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or FakeProcess(),
    )

    desktop._start_server()

    assert calls[0][0] == [
        sys.executable,
        "-m",
        "biodynamic_calendar_app",
        "--host",
        "0.0.0.0",
        "--port",
        "8877",
    ]
    assert calls[0][1]["cwd"] == desktop.PROJECT_ROOT
    assert calls[0][1]["env"]["PYTHONPATH"].split(desktop.os.pathsep)[0] == str(
        desktop.PROJECT_ROOT / "src"
    )


def test_health_probe_uses_direct_no_proxy_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    opener = SimpleNamespace(
        open=lambda url, timeout: (calls.append((url, timeout)), Response())[1]
    )
    monkeypatch.setattr(desktop, "_direct_opener", opener)

    assert desktop._is_healthy("http://127.0.0.1:8765/", timeout=2.5) is True
    assert calls == [("http://127.0.0.1:8765/healthz", 2.5)]


def test_gui_starts_and_stops_only_server_it_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    fake_webview, _ = _fake_webview(calls)
    process = FakeProcess()
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: False)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, _process: True)
    monkeypatch.setattr(desktop, "_start_server", lambda: process)
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)
    monkeypatch.delenv("BD_CALENDAR_GUI_URL", raising=False)

    assert desktop.main() == 0
    assert process.terminated is True
    assert calls[0][0] == "create"
    assert calls[0][1] == ("Biodynamic Calendar", "http://127.0.0.1:8765/")
    assert calls[0][2]["width"] == 1600
    assert calls[0][2]["height"] == 1000
    assert calls[0][2]["min_size"] == (1100, 700)
    assert calls[1] == ("start", (), {})


def test_gui_attaches_without_stopping_existing_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    fake_webview, _ = _fake_webview(calls)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: True)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, process: process is None)
    monkeypatch.setattr(
        desktop,
        "_start_server",
        lambda: pytest.fail("an existing server must not be replaced"),
    )
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop.main() == 0
    assert calls[-1] == ("start", (), {})


def test_linux_installs_matching_desktop_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    identity_calls = []
    fake_glib = SimpleNamespace(
        set_prgname=lambda value: identity_calls.append(("prgname", value)),
        set_application_name=lambda value: identity_calls.append(("name", value)),
    )
    fake_gi = ModuleType("gi")
    fake_gi.__path__ = []
    fake_repository = ModuleType("gi.repository")
    fake_repository.GLib = fake_glib
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", fake_repository)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    desktop_path = desktop.configure_linux_app_identity()

    assert identity_calls == [
        ("prgname", desktop.LINUX_APP_ID),
        ("name", "Biodynamic Calendar"),
    ]
    assert desktop_path == tmp_path / "applications" / f"{desktop.LINUX_APP_ID}.desktop"
    text = desktop_path.read_text(encoding="utf-8")
    assert "Name=Biodynamic Calendar\n" in text
    assert f"Icon={desktop.DESKTOP_ICON_PATH}\n" in text
    assert f"StartupWMClass={desktop.LINUX_APP_ID}\n" in text


def test_linux_launcher_passes_icon_to_gtk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    fake_webview, _ = _fake_webview(calls)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(desktop, "configure_linux_app_identity", lambda: None)
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: True)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, _process: True)
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop.main() == 0
    assert calls[-1] == (
        "start",
        (),
        {"gui": "gtk", "icon": str(desktop.DESKTOP_ICON_PATH)},
    )


def test_windows_launcher_applies_ico(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    fake_webview, window = _fake_webview(calls)
    icon_instances = []

    class FakeIcon:
        def __init__(self, path: str) -> None:
            icon_instances.append(path)

    drawing = ModuleType("System.Drawing")
    drawing.Icon = FakeIcon
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "System.Drawing", drawing)
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: True)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, _process: True)
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop.main() == 0
    window.events.shown.handlers[0]()
    assert icon_instances == [str(desktop.WINDOWS_ICON_PATH)]
    assert isinstance(window.native.Icon, FakeIcon)


def test_macos_icon_callback_sets_application_icon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    icon = object()

    class FakeNSImage:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithContentsOfFile_(self, path: str):
            calls.append(("load", path))
            return icon

    fake_application = SimpleNamespace(
        setApplicationIconImage_=lambda value: calls.append(("set", value))
    )
    appkit = ModuleType("AppKit")
    appkit.NSApplication = SimpleNamespace(
        sharedApplication=lambda: fake_application
    )
    appkit.NSImage = FakeNSImage
    pyobjc_tools = ModuleType("PyObjCTools")
    pyobjc_tools.AppHelper = SimpleNamespace(callAfter=lambda callback: callback())
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc_tools)

    desktop.set_macos_app_icon()

    assert calls == [("load", str(desktop.DESKTOP_ICON_PATH)), ("set", icon)]

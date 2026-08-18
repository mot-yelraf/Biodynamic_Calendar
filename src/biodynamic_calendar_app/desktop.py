"""Launch Biodynamic Calendar in a native pywebview desktop window."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ICON_PATH = PROJECT_ROOT / "static" / "bd-calendar-icon-512.png"
WINDOWS_ICON_PATH = PROJECT_ROOT / "static" / "bd-calendar-icon.ico"
LINUX_APP_ID = "calendar.biodynamic.BiodynamicCalendar"

DEFAULT_WINDOW_WIDTH = 1600
DEFAULT_WINDOW_HEIGHT = 1000
DEFAULT_MIN_WIDTH = 1100
DEFAULT_MIN_HEIGHT = 700
DEFAULT_PORT = 8765

_windows_icon: Any = None
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _base_url() -> str:
    configured = os.environ.get("BD_CALENDAR_GUI_URL")
    if configured:
        return configured.rstrip("/") + "/"
    port = os.environ.get("BD_CALENDAR_PORT", str(DEFAULT_PORT))
    return f"http://127.0.0.1:{port}/"


def _int_env(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _available_screen_size() -> tuple[int, int] | None:
    """Return the primary display's usable size when the platform exposes it."""
    try:
        if sys.platform == "darwin":
            from AppKit import NSScreen

            screen = NSScreen.mainScreen()
            if screen is not None:
                size = screen.visibleFrame().size
                return int(size.width), int(size.height)
        elif sys.platform == "win32":
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        elif sys.platform.startswith("linux"):
            import gi

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk

            display = Gdk.Display.get_default()
            if display is not None:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor is not None:
                    workarea = monitor.get_workarea()
                    return int(workarea.width), int(workarea.height)
    except Exception:
        pass
    return None


def _window_geometry() -> dict[str, int | None]:
    width = max(
        640,
        _int_env("BD_CALENDAR_GUI_WIDTH", DEFAULT_WINDOW_WIDTH)
        or DEFAULT_WINDOW_WIDTH,
    )
    height = max(
        480,
        _int_env("BD_CALENDAR_GUI_HEIGHT", DEFAULT_WINDOW_HEIGHT)
        or DEFAULT_WINDOW_HEIGHT,
    )
    screen_size = _available_screen_size()
    if screen_size is not None:
        width = min(width, screen_size[0])
        height = min(height, screen_size[1])
    return {
        "width": width,
        "height": height,
        "x": _int_env("BD_CALENDAR_GUI_X", None),
        "y": _int_env("BD_CALENDAR_GUI_Y", None),
    }


def _is_healthy(base_url: str, timeout: float = 1.0) -> bool:
    health_url = base_url.rstrip("/") + "/healthz"
    try:
        with _direct_opener.open(health_url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_health(base_url: str, process: subprocess.Popen[Any] | None) -> bool:
    retries = max(1, _int_env("BD_CALENDAR_GUI_RETRIES", 120) or 120)
    delay = max(0.0, _float_env("BD_CALENDAR_GUI_RETRY_DELAY", 0.25))
    for _ in range(retries):
        if _is_healthy(base_url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(delay)
    return False


def _start_server() -> subprocess.Popen[Any]:
    """Start the LAN server with the current interpreter and venv."""
    host = os.environ.get("BD_CALENDAR_HOST", "0.0.0.0")
    port = os.environ.get("BD_CALENDAR_PORT", str(DEFAULT_PORT))
    child_env = os.environ.copy()
    source_root = PROJECT_ROOT / "src"
    if source_root.is_dir():
        existing_path = child_env.get("PYTHONPATH")
        child_env["PYTHONPATH"] = (
            str(source_root)
            if not existing_path
            else str(source_root) + os.pathsep + existing_path
        )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "biodynamic_calendar_app",
            "--host",
            host,
            "--port",
            port,
        ],
        cwd=PROJECT_ROOT,
        env=child_env,
    )


def _stop_owned_server(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _desktop_exec_arg(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def configure_linux_app_identity() -> Path | None:
    """Install the per-user Linux desktop identity used by GTK and Wayland."""
    if not sys.platform.startswith("linux"):
        return None

    try:
        from gi.repository import GLib

        GLib.set_prgname(LINUX_APP_ID)
        GLib.set_application_name("Biodynamic Calendar")
    except Exception as exc:
        print(
            f"BD Calendar could not set its Linux application ID: {exc}",
            file=sys.stderr,
        )

    data_root = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ).expanduser()
    applications_dir = data_root / "applications"
    icons_dir = data_root / "icons" / "hicolor" / "512x512" / "apps"
    desktop_path = applications_dir / f"{LINUX_APP_ID}.desktop"
    themed_icon_path = icons_dir / f"{LINUX_APP_ID}.png"
    launcher_path = PROJECT_ROOT / "run_bd_calendar_gui.sh"
    desktop_text = "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=Biodynamic Calendar",
            "Comment=Open the Biodynamic Calendar",
            f"Exec={_desktop_exec_arg(str(launcher_path))}",
            f"Path={PROJECT_ROOT}",
            f"Icon={DESKTOP_ICON_PATH}",
            "Terminal=false",
            "StartupNotify=true",
            f"StartupWMClass={LINUX_APP_ID}",
            "",
        )
    )

    try:
        applications_dir.mkdir(parents=True, exist_ok=True)
        icons_dir.mkdir(parents=True, exist_ok=True)
        if (
            not themed_icon_path.is_file()
            or themed_icon_path.read_bytes() != DESKTOP_ICON_PATH.read_bytes()
        ):
            temporary_icon = themed_icon_path.with_suffix(".png.tmp")
            shutil.copyfile(DESKTOP_ICON_PATH, temporary_icon)
            temporary_icon.replace(themed_icon_path)
        if (
            not desktop_path.is_file()
            or desktop_path.read_text(encoding="utf-8") != desktop_text
        ):
            temporary_desktop = desktop_path.with_suffix(".desktop.tmp")
            temporary_desktop.write_text(desktop_text, encoding="utf-8")
            temporary_desktop.replace(desktop_path)
    except OSError as exc:
        print(
            f"BD Calendar could not install its Linux desktop entry: {exc}",
            file=sys.stderr,
        )
        return None
    return desktop_path


def set_macos_app_icon() -> None:
    """Set the running Cocoa application's Dock and app-switcher icon."""
    if not DESKTOP_ICON_PATH.is_file():
        return
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper

        def apply_icon() -> None:
            icon = NSImage.alloc().initWithContentsOfFile_(str(DESKTOP_ICON_PATH))
            if icon is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(icon)

        AppHelper.callAfter(apply_icon)
    except Exception as exc:
        print(f"BD Calendar could not set its macOS app icon: {exc}", file=sys.stderr)


def set_windows_app_icon(window: Any) -> None:
    """Set the WinForms window and taskbar icon after native creation."""
    global _windows_icon
    if not WINDOWS_ICON_PATH.is_file() or window.native is None:
        return
    try:
        from System.Drawing import Icon

        _windows_icon = Icon(str(WINDOWS_ICON_PATH))
        window.native.Icon = _windows_icon
    except Exception as exc:
        print(f"BD Calendar could not set its Windows app icon: {exc}", file=sys.stderr)


def main() -> int:
    """Start or attach to BD Calendar and open its native desktop window."""
    base_url = _base_url()
    owned_server: subprocess.Popen[Any] | None = None
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

    if sys.platform.startswith("linux"):
        os.environ.setdefault("GDK_BACKEND", "wayland,x11")
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            print(
                "BD Calendar GUI not started: no DISPLAY or WAYLAND_DISPLAY is set.",
                file=sys.stderr,
            )
            return 1
        configure_linux_app_identity()

    try:
        import webview
    except Exception as exc:
        print(f"BD Calendar GUI not started: pywebview import failed: {exc}", file=sys.stderr)
        return 1

    if not _is_healthy(base_url):
        if os.environ.get("BD_CALENDAR_GUI_URL"):
            print(
                f"BD Calendar GUI not started: {base_url.rstrip('/')} is not ready.",
                file=sys.stderr,
            )
            return 1
        try:
            owned_server = _start_server()
        except OSError as exc:
            print(f"BD Calendar GUI could not start its server: {exc}", file=sys.stderr)
            return 1

    if not _wait_for_health(base_url, owned_server):
        _stop_owned_server(owned_server)
        print(
            f"BD Calendar GUI not started: {base_url.rstrip('/')} did not become ready.",
            file=sys.stderr,
        )
        return 1

    try:
        geometry = _window_geometry()
        window = webview.create_window(
            "Biodynamic Calendar",
            base_url,
            width=geometry["width"],
            height=geometry["height"],
            x=geometry["x"],
            y=geometry["y"],
            min_size=(
                min(DEFAULT_MIN_WIDTH, int(geometry["width"])),
                min(DEFAULT_MIN_HEIGHT, int(geometry["height"])),
            ),
            resizable=True,
            frameless=False,
            confirm_close=True,
        )
        if sys.platform == "darwin":
            window.events.shown += set_macos_app_icon
            webview.start()
        elif sys.platform == "win32":
            window.events.shown += lambda: set_windows_app_icon(window)
            webview.start()
        elif sys.platform.startswith("linux"):
            webview.start(gui="gtk", icon=str(DESKTOP_ICON_PATH))
        else:
            webview.start()
    finally:
        _stop_owned_server(owned_server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

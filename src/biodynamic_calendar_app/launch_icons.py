"""Install a native click-to-launch icon without starting the desktop app or server."""

import argparse
from importlib.metadata import version
from pathlib import Path
import os
import plistlib
import shlex
import shutil
import sys

from .desktop import MACOS_APP_NAME, MACOS_BUNDLE_ID, MACOS_ICON_PATH, LINUX_APP_ID, _desktop_exec_arg, write_linux_app_launcher

MACOS_LAUNCHER_ID = f"{MACOS_BUNDLE_ID}.launcher"
INSTALL_DIRECTORY_KEY = "BiodynamicCalendarInstallDirectory"


def _launcher_path() -> Path:
    return Path.home() / "Applications" / f"{MACOS_APP_NAME}.app"


def write_macos_app_launcher(runtime_dir: Path) -> Path:
    """Create or repair our launcher, preserving unrelated applications."""
    runtime_dir = runtime_dir.resolve()
    launcher = runtime_dir / "run_bd_calendar_gui.sh"
    if not launcher.is_file():
        raise FileNotFoundError(f"Installed GUI launcher is missing: {launcher}")
    bundle = _launcher_path()
    info = bundle / "Contents" / "Info.plist"
    if bundle.exists():
        if not info.is_file() or plistlib.loads(info.read_bytes()).get(
            "CFBundleIdentifier"
        ) != MACOS_LAUNCHER_ID:
            raise FileExistsError(f"Refusing to overwrite another application: {bundle}")
    executable_dir = bundle / "Contents" / "MacOS"
    resources = bundle / "Contents" / "Resources"
    executable_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    bundle_version = version("biodynamic-calendar").removeprefix("v0.").removeprefix("0.")
    info.write_bytes(plistlib.dumps({
        "CFBundleDisplayName": MACOS_APP_NAME,
        "CFBundleName": MACOS_APP_NAME,
        "CFBundleExecutable": MACOS_APP_NAME,
        "CFBundleIdentifier": MACOS_LAUNCHER_ID,
        "CFBundleIconFile": MACOS_ICON_PATH.stem,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "CFBundleShortVersionString": bundle_version,
        "CFBundleVersion": bundle_version,
        INSTALL_DIRECTORY_KEY: str(runtime_dir),
    }))
    shutil.copyfile(MACOS_ICON_PATH, resources / MACOS_ICON_PATH.name)
    executable = executable_dir / MACOS_APP_NAME
    executable.write_text(
        "#!/bin/bash\n"
        f"runtime_dir={shlex.quote(str(runtime_dir))}\n"
        'data_dir="${BD_CALENDAR_DATA_DIR:-$HOME/.biodynamic_calendar}"\n'
        'log_file="$data_dir/desktop-launch.log"\n'
        'if mkdir -p "$data_dir" && "$runtime_dir/run_bd_calendar_gui.sh" "$@" >>"$log_file" 2>&1; then\n'
        '  exit 0\n'
        'fi\n'
        '/usr/bin/osascript - "$log_file" <<\'APPLESCRIPT\'\n'
        'on run argv\n'
        '  display alert "Biodynamic Calendar could not start" message '
        '("Run the installer again to repair the application. Details: " & item 1 of argv) as critical\n'
        'end run\n'
        'APPLESCRIPT\n'
        'exit 1\n', encoding="utf-8",
    )
    executable.chmod(0o755)
    return bundle


def remove_macos_app_launcher(runtime_dir: Path) -> None:
    """Remove only the launcher belonging to this installation."""
    bundle = _launcher_path()
    info = bundle / "Contents" / "Info.plist"
    if info.is_file():
        document = plistlib.loads(info.read_bytes())
        if (document.get("CFBundleIdentifier") == MACOS_LAUNCHER_ID
                and document.get(INSTALL_DIRECTORY_KEY) == str(runtime_dir.resolve())):
            shutil.rmtree(bundle)


def remove_linux_app_launcher(runtime_dir: Path) -> None:
    """Remove only the menu entry pointing to this installation."""
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser()
    entry = root / "applications" / f"{LINUX_APP_ID}.desktop"
    expected = f"Exec={_desktop_exec_arg(str(runtime_dir.resolve() / 'run_bd_calendar_gui.sh'))}"
    if entry.is_file() and expected in entry.read_text(encoding="utf-8").splitlines():
        entry.unlink()
        (root / "icons/hicolor/512x512/apps" / f"{LINUX_APP_ID}.png").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        parser.error("Use the Windows installer to create Windows shortcuts.")
    try:
        if args.remove:
            if sys.platform == "darwin":
                remove_macos_app_launcher(args.runtime_dir)
            else:
                remove_linux_app_launcher(args.runtime_dir)
        else:
            if not (args.runtime_dir / "run_bd_calendar_gui.sh").is_file():
                raise FileNotFoundError(f"Installed GUI launcher is missing: {args.runtime_dir}")
            path = (write_macos_app_launcher(args.runtime_dir) if sys.platform == "darwin"
                    else write_linux_app_launcher(args.runtime_dir))
            if path is None:
                return 1
            print(f"Click-to-launch icon: {path}")
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        print(f"Biodynamic Calendar launch icon could not be updated: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

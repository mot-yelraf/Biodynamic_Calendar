"""Exercise Finder launchers with disposable homes and fake desktop runtimes."""

import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from biodynamic_calendar_app import launch_icons


@pytest.fixture
def launcher_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(launch_icons, "version", lambda name: "0.26.279.1")
    return home


def make_runtime(path):
    path.mkdir()
    launcher = path / "run_bd_calendar_gui.sh"
    launcher.write_text('#!/bin/bash\nprintf "runtime:%s arg:%s\\n" "$PWD" "$1"\n')
    launcher.chmod(0o755)
    return path


@pytest.mark.skipif(os.name == "nt", reason="POSIX Finder launcher")
def test_launcher_executes_selected_runtime_and_preserves_arguments(tmp_path, launcher_home):
    runtime = make_runtime(tmp_path / "runtime with 'quotes' and $spaces")
    bundle = launch_icons.write_macos_app_launcher(runtime)
    document = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    assert document["CFBundleIdentifier"] == launch_icons.MACOS_LAUNCHER_ID
    assert document["CFBundleVersion"] == "26.279.1"
    assert document[launch_icons.INSTALL_DIRECTORY_KEY] == str(runtime)
    assert (bundle / "Contents/Resources" / launch_icons.MACOS_ICON_PATH.name).read_bytes() == launch_icons.MACOS_ICON_PATH.read_bytes()
    result = subprocess.run([str(bundle / "Contents/MacOS/Biodynamic Calendar"), "argument with spaces"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    log = launcher_home / ".biodynamic_calendar/desktop-launch.log"
    assert "arg:argument with spaces" in log.read_text()
    other = make_runtime(tmp_path / "other runtime")
    assert launch_icons.write_macos_app_launcher(other) == bundle
    launch_icons.remove_macos_app_launcher(runtime)
    assert bundle.exists()
    launch_icons.remove_macos_app_launcher(other)
    assert not bundle.exists()
    assert log.exists()


@pytest.mark.parametrize("plist", [None, {"CFBundleIdentifier": "other.app"}])
def test_preserves_unrelated_app(tmp_path, launcher_home, plist):
    bundle = launcher_home / "Applications/Biodynamic Calendar.app"
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    if plist is not None:
        (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
    marker = contents / "keep.txt"
    marker.write_text("keep")
    runtime = make_runtime(tmp_path / "runtime")
    with pytest.raises(FileExistsError):
        launch_icons.write_macos_app_launcher(runtime)
    launch_icons.remove_macos_app_launcher(runtime)
    assert marker.read_text() == "keep"


def test_missing_runtime_does_not_create_app(tmp_path, launcher_home):
    with pytest.raises(FileNotFoundError):
        launch_icons.write_macos_app_launcher(tmp_path / "missing")
    assert not (launcher_home / "Applications").exists()


def test_installer_creates_launcher_and_uninstaller_removes_before_venv():
    installer = Path("scripts/install_macos.sh").read_text()
    assert installer.index('chmod +x "$APP_DIR/run_bd_calendar_gui.sh"') < installer.index("-m biodynamic_calendar_app.launch_icons")
    uninstaller = Path("scripts/uninstall_macos.sh").read_text()
    assert uninstaller.index("-m biodynamic_calendar_app.launch_icons") < uninstaller.index('rm -rf "$APP_DIR/.venv"')


def test_linux_menu_icon_created_without_gui_and_removed_by_owner(tmp_path, monkeypatch):
    from biodynamic_calendar_app import desktop
    root = tmp_path / "xdg data"
    monkeypatch.setenv("XDG_DATA_HOME", str(root))
    monkeypatch.setattr(launch_icons.sys, "platform", "linux")
    runtime = make_runtime(tmp_path / "installed runtime")
    (runtime / "static").mkdir()
    (runtime / "static/bd-calendar-icon-512.png").write_bytes(b"icon")
    monkeypatch.setattr(launch_icons.sys, "argv", ["launch_icons", str(runtime)])
    assert launch_icons.main() == 0
    entry = root / "applications" / f"{desktop.LINUX_APP_ID}.desktop"
    text = entry.read_text()
    assert f'Exec="{runtime}/run_bd_calendar_gui.sh"\n' in text
    assert f"Path={runtime}\n" in text
    assert "Terminal=false" in text
    icon = root / "icons/hicolor/512x512/apps" / f"{desktop.LINUX_APP_ID}.png"
    assert icon.read_bytes() == b"icon"
    assert launch_icons.main() == 0
    launch_icons.remove_linux_app_launcher(tmp_path / "other")
    assert entry.exists()
    launch_icons.remove_linux_app_launcher(runtime)
    assert not entry.exists()
    assert not icon.exists()


def test_linux_preserves_unrelated_menu_entry(tmp_path, monkeypatch):
    from biodynamic_calendar_app import desktop
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry = tmp_path / "applications" / f"{desktop.LINUX_APP_ID}.desktop"
    entry.parent.mkdir()
    entry.write_text("[Desktop Entry]\nName=Other app\n")
    assert desktop.write_linux_app_launcher(tmp_path / "runtime") is None
    assert entry.read_text() == "[Desktop Entry]\nName=Other app\n"


def test_linux_exec_escapes_desktop_entry_reserved_characters():
    from biodynamic_calendar_app.desktop import _desktop_exec_arg
    assert _desktop_exec_arg('a$b`c"d\\e%f') == '"a\\\\$b\\\\`c\\\\"d\\\\\\\\e%%f"'


def test_other_installers_create_icons_and_remove_before_runtime():
    installer = Path("scripts/install_linux.sh").read_text()
    assert installer.index("-m biodynamic_calendar_app.launch_icons") < installer.index('if prompt_auto_start "$EXISTING_AUTO_START"; then')
    uninstaller = Path("scripts/uninstall_linux.sh").read_text()
    assert uninstaller.index("-m biodynamic_calendar_app.launch_icons") < uninstaller.index("\nremove_virtualenv\n")
    installer = Path("scripts/install_windows.ps1").read_text()
    assert "Update-CalendarLaunchIcons -RuntimeDir $AppDir" in installer
    uninstaller = Path("scripts/uninstall_windows.ps1").read_text()
    assert uninstaller.index("Update-CalendarLaunchIcons -RuntimeDir $AppDir -Remove") < uninstaller.index("Remove-Item -Recurse -Force $VenvPath")


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell and WScript.Shell")
def test_windows_native_shortcuts_update_and_remove_by_owner(tmp_path):
    import shutil
    runtime = tmp_path / "runtime with spaces"
    runtime.mkdir()
    (runtime / "run_bd_calendar_gui.ps1").write_text("# fake runtime; never launched\n")
    (runtime / "static").mkdir()
    shutil.copyfile("static/bd-calendar-icon.ico", runtime / "static/bd-calendar-icon.ico")
    helper = Path("scripts/windows_launch_icons.ps1").resolve()
    # Single-quoted PowerShell literals keep paths out of expression expansion.
    def literal(path):
        return "'" + str(path).replace("'", "''") + "'"
    body = f'''
$ErrorActionPreference = "Stop"
. {literal(helper)}
$Runtime = {literal(runtime)}
$Directories = @({literal(tmp_path / 'Desktop')}, {literal(tmp_path / 'Programs')})
Update-CalendarLaunchIcons -RuntimeDir $Runtime -ShortcutDirectories $Directories
$Shell = New-Object -ComObject WScript.Shell
foreach ($Directory in $Directories) {{
    $Path = Join-Path $Directory "Biodynamic Calendar.lnk"
    $Shortcut = $Shell.CreateShortcut($Path)
    if ($Shortcut.WorkingDirectory -ne $Runtime) {{ throw "Wrong runtime" }}
    if ($Shortcut.Arguments -notlike '*-File "*runtime with spaces*run_bd_calendar_gui.ps1"') {{ throw "Wrong arguments" }}
    if ($Shortcut.IconLocation -ne ((Join-Path $Runtime "static\\bd-calendar-icon.ico") + ",0")) {{ throw "Wrong icon" }}
}}
Update-CalendarLaunchIcons -RuntimeDir $Runtime -ShortcutDirectories $Directories
Update-CalendarLaunchIcons -RuntimeDir ($Runtime + "-other") -ShortcutDirectories $Directories -Remove
foreach ($Directory in $Directories) {{
    if (-not (Test-Path -LiteralPath (Join-Path $Directory "Biodynamic Calendar.lnk"))) {{ throw "Removed another installation" }}
}}
$OtherPath = Join-Path $Directories[1] "Biodynamic Calendar.lnk"
$Other = $Shell.CreateShortcut($OtherPath)
$Other.Description = "Unrelated shortcut"
$Other.Save()
Update-CalendarLaunchIcons -RuntimeDir $Runtime -ShortcutDirectories $Directories -Remove
if (Test-Path -LiteralPath (Join-Path $Directories[0] "Biodynamic Calendar.lnk")) {{ throw "Owned shortcut remains" }}
if (-not (Test-Path -LiteralPath $OtherPath)) {{ throw "Removed unrelated shortcut" }}
try {{
    Update-CalendarLaunchIcons -RuntimeDir $Runtime -ShortcutDirectories @($Directories[1])
    throw "Expected collision rejection"
}} catch {{
    if ($_.Exception.Message -notlike 'Refusing to overwrite another shortcut:*') {{ throw }}
}}
'''
    script = tmp_path / "test_shortcuts.ps1"
    script.write_text(body, encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

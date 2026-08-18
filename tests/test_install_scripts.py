from pathlib import Path


def test_bash_install_scripts_write_install_log_with_required_context():
    helper = Path("scripts/install_logging.sh").read_text(encoding="utf-8")
    linux_script = Path("scripts/install_linux.sh").read_text(encoding="utf-8")
    macos_script = Path("scripts/install_macos.sh").read_text(encoding="utf-8")

    assert "install.log" in helper
    assert "Hostname:" in helper
    assert "User:" in helper
    assert "Working dir:" in helper
    assert "OS name/version:" in helper
    assert "Kernel:" in helper
    assert "Platform/arch:" in helper
    assert "Hardware model:" in helper
    assert "CPU:" in helper
    assert "Memory:" in helper
    assert "Free disk space:" in helper
    assert "Target PROJECT_DIR:" in helper
    assert "Git branch/revision/worktree state" in helper
    assert "Key tool versions" in helper
    assert "install_log_step" in linux_script
    assert "init_install_log" in linux_script
    assert "init_install_log" in macos_script


def test_windows_install_script_writes_install_log_with_required_context():
    script = Path("scripts/install_windows.ps1").read_text(encoding="utf-8")

    assert "install.log" in script
    assert "Start-Transcript" in script
    assert "Hostname:" in script
    assert "User:" in script
    assert "Working dir:" in script
    assert "OS name/version:" in script
    assert "Kernel:" in script
    assert "Platform/arch:" in script
    assert "Hardware model:" in script
    assert "CPU:" in script
    assert "Memory:" in script
    assert "Free disk space:" in script
    assert "Target PROJECT_DIR:" in script
    assert "Git branch/revision/worktree state" in script
    assert "Key tool versions" in script
    assert "Write-Step" in script


def test_installers_target_user_runtime_and_include_desktop_launcher():
    macos_script = Path("scripts/install_macos.sh").read_text(encoding="utf-8")
    linux_script = Path("scripts/install_linux.sh").read_text(encoding="utf-8")
    windows_script = Path("scripts/install_windows.ps1").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    for script in (macos_script, linux_script):
        assert '${HOME}/Biodynamic_Calendar' in script
        assert 'run_bd_calendar_gui.sh' in script
        assert "import webview" in script

    assert 'Join-Path $env:USERPROFILE "Biodynamic_Calendar"' in windows_script
    assert "run_bd_calendar_gui.cmd" in windows_script
    assert "import webview" in windows_script
    assert '"pywebview==5.4"' in pyproject
    assert 'biodynamic-calendar = "biodynamic_calendar_app.desktop:main"' in pyproject


def test_linux_desktop_install_uses_system_gtk_and_webkit():
    script = Path("scripts/install_linux.sh").read_text(encoding="utf-8")

    assert 'python3 -m venv --system-site-packages "$VENV_DIR"' in script
    assert 'gi.require_version("Gtk", "3.0")' in script
    assert 'gi.require_version("WebKit2", "4.1")' in script


def test_checkout_gui_launchers_can_use_installed_runtime():
    shell_launcher = Path("run_bd_calendar_gui.sh").read_text(encoding="utf-8")
    powershell_launcher = Path("run_bd_calendar_gui.ps1").read_text(encoding="utf-8")
    cmd_launcher = Path("run_bd_calendar_gui.cmd").read_text(encoding="utf-8")

    assert '${BD_CALENDAR_INSTALL_DIR:-${HOME}/Biodynamic_Calendar}' in shell_launcher
    assert "Using installed Biodynamic Calendar runtime" in shell_launcher
    assert 'Join-Path $env:USERPROFILE "Biodynamic_Calendar"' in powershell_launcher
    assert "Using installed Biodynamic Calendar runtime" in powershell_launcher
    assert "%USERPROFILE%\\Biodynamic_Calendar\\" in cmd_launcher
    assert "Using installed Biodynamic Calendar runtime" in cmd_launcher


def test_linux_install_can_offer_systemd_user_autostart():
    script = Path("scripts/install_linux.sh").read_text(encoding="utf-8")

    assert "Enable BD Calendar auto-start for this Linux user with systemd?" in script
    assert "systemctl --user show-environment" in script
    assert "biodynamic-calendar.service" in script
    assert "ExecStart=$APP_DIR/.venv/bin/biodynamic-calendar-server --host $SERVICE_HOST --port $SERVICE_PORT" in script
    assert "The service binds to $SERVICE_HOST on port $SERVICE_PORT." in script
    assert "stop_existing_systemd_user_service" in script
    assert "systemctl --user enable \"$SERVICE_NAME\"" in script
    assert "systemctl --user restart \"$SERVICE_NAME\"" in script


def test_linux_uninstall_removes_systemd_services_and_preserves_data_by_default():
    script = Path("scripts/uninstall_linux.sh").read_text(encoding="utf-8")

    assert "systemctl --user disable --now \"$SERVICE_NAME\"" in script
    assert "rm -f \"$SERVICE_PATH\"" in script
    assert "SYSTEM_SERVICE_PATH=\"/etc/systemd/system/$SERVICE_NAME\"" in script
    assert "sudo systemctl disable --now $SERVICE_NAME" in script
    assert "Preserved local data in $DATA_DIR." in script
    assert "--purge-data" in script

from pathlib import Path


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

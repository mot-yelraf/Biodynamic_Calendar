from pathlib import Path


def test_linux_setup_can_offer_systemd_user_autostart():
    script = Path("scripts/setup_linux.sh").read_text(encoding="utf-8")

    assert "Enable BD Calendar auto-start for this Linux user with systemd? [y/N]" in script
    assert "systemctl --user show-environment" in script
    assert "biodynamic-calendar.service" in script
    assert "ExecStart=$APP_DIR/.venv/bin/biodynamic-calendar-server --host 0.0.0.0 --port 8765" in script
    assert "The service binds to all network interfaces on port 8765." in script
    assert "systemctl --user enable --now \"$SERVICE_NAME\"" in script

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_deploy_module():
    path = Path("scripts/deploy_bdca.py")
    spec = importlib.util.spec_from_file_location("deploy_bdca", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_host_file_accepts_comments_and_pipe_format(tmp_path):
    deploy = load_deploy_module()
    hosts = tmp_path / "hosts.txt"
    hosts.write_text(
        "\n# comment\npi@bdca.local | /home/pi/Biodynamic_Calendar\nuser@example.test | /srv/bdca\n",
        encoding="utf-8",
    )

    targets = deploy.parse_host_file(hosts)

    assert [(target.host, target.path) for target in targets] == [
        ("pi@bdca.local", "/home/pi/Biodynamic_Calendar"),
        ("user@example.test", "/srv/bdca"),
    ]


def test_parse_host_file_rejects_missing_pipe(tmp_path):
    deploy = load_deploy_module()
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("pi@bdca.local /home/pi/Biodynamic_Calendar\n", encoding="utf-8")

    try:
        deploy.parse_host_file(hosts)
    except ValueError as exc:
        assert "expected '<host> | <path_to_Biodynamic_Calendar>'" in str(exc)
    else:
        raise AssertionError("expected invalid host file to raise ValueError")


def test_directory_rsync_command_does_not_prune_remote_files():
    deploy = load_deploy_module()
    target = deploy.HostTarget("pi@bdca.local", "/home/pi/Biodynamic_Calendar", 1)
    item = deploy.SyncItem(Path("static"), "static", True)

    command = deploy.build_rsync_command(
        root=Path("/repo"),
        target=target,
        item=item,
        dry_run=True,
        rsync_bin="rsync",
        ssh_command=None,
    )

    assert "--dry-run" in command
    prune_flag = "--" + "delete"
    assert prune_flag not in command
    assert "/repo/static/" in command
    assert command[-1] == "pi@bdca.local:/home/pi/Biodynamic_Calendar/static/"


def test_file_rsync_command_does_not_prune_remote_root():
    deploy = load_deploy_module()
    target = deploy.HostTarget("pi@bdca.local", "/home/pi/Biodynamic_Calendar", 1)
    item = deploy.SyncItem(Path("pyproject.toml"), "pyproject.toml", False)

    command = deploy.build_rsync_command(
        root=Path("/repo"),
        target=target,
        item=item,
        dry_run=False,
        rsync_bin="rsync",
        ssh_command="ssh -p 2222",
    )

    assert "--dry-run" not in command
    prune_flag = "--" + "delete"
    assert prune_flag not in command
    assert command[-2] == "/repo/pyproject.toml"
    assert command[-1] == "pi@bdca.local:/home/pi/Biodynamic_Calendar/pyproject.toml"
    assert command[command.index("-e") + 1] == "ssh -p 2222"


def test_self_target_is_rejected():
    deploy = load_deploy_module()
    root = Path.cwd()
    targets = [deploy.HostTarget("localhost", str(root), 1)]

    try:
        deploy.validate_not_self_targets(targets, root)
    except ValueError as exc:
        assert "targets this checkout" in str(exc)
    else:
        raise AssertionError("expected local self target to raise ValueError")


def test_deploy_wrapper_invokes_python_script():
    wrapper = Path("scripts/deploy_bdca").read_text(encoding="utf-8")

    assert "deploy_bdca.py" in wrapper
    assert 'exec python3 "$SCRIPT_DIR/deploy_bdca.py" "$@"' in wrapper

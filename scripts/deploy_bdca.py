#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_HOST_FILE = Path("scripts/bdca_hosts.txt")
RSYNC_EXCLUDES = (
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
)


@dataclass(frozen=True)
class HostTarget:
    host: str
    path: str
    line_number: int


@dataclass(frozen=True)
class SyncItem:
    source: Path
    remote_path: str
    is_dir: bool


SYNC_ITEMS = (
    SyncItem(Path("src"), "src", True),
    SyncItem(Path("static"), "static", True),
    SyncItem(Path("templates"), "templates", True),
    SyncItem(Path("pyproject.toml"), "pyproject.toml", False),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_host_file(path: Path) -> list[HostTarget]:
    targets: list[HostTarget] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        pieces = [piece.strip() for piece in line.split("|", maxsplit=1)]
        if len(pieces) != 2:
            raise ValueError(f"{path}:{line_number}: expected '<host> | <path_to_Biodynamic_Calendar>'")

        host, remote_path = pieces
        if not host or not remote_path:
            raise ValueError(f"{path}:{line_number}: host and path are required")
        if any(char.isspace() for char in host):
            raise ValueError(f"{path}:{line_number}: host must not contain whitespace")

        targets.append(HostTarget(host=host, path=remote_path, line_number=line_number))

    if not targets:
        raise ValueError(f"{path}: no deployment targets found")
    return targets


def host_file_path(value: str | None, root: Path) -> Path:
    path = Path(value) if value else DEFAULT_HOST_FILE
    if not path.is_absolute():
        path = root / path
    return path


def validate_sources(root: Path) -> None:
    missing = [str(item.source) for item in SYNC_ITEMS if not (root / item.source).exists()]
    if missing:
        raise ValueError(f"missing deploy source(s): {', '.join(missing)}")


def host_name(target_host: str) -> str:
    host = target_host.rsplit("@", maxsplit=1)[-1]
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif host.count(":") == 1:
        host = host.split(":", maxsplit=1)[0]
    return host.rstrip(".").lower()


def local_host_names() -> set[str]:
    names = {"localhost", "127.0.0.1", "::1"}
    for name in {socket.gethostname(), socket.getfqdn()}:
        if not name:
            continue
        normalized = name.rstrip(".").lower()
        names.add(normalized)
        short_name = normalized.split(".", maxsplit=1)[0]
        names.add(short_name)
        names.add(f"{short_name}.local")
    return names


def validate_not_self_targets(targets: Sequence[HostTarget], root: Path) -> None:
    local_names = local_host_names()
    root_path = root.expanduser().resolve()
    for target in targets:
        if host_name(target.host) not in local_names:
            continue
        target_path = Path(target.path).expanduser()
        if not target_path.is_absolute():
            continue
        if target_path.resolve() == root_path:
            raise ValueError(
                f"host file line {target.line_number} targets this checkout ({target.host} | {target.path}); "
                "remove that entry before deploying"
            )


def remote_destination(target: HostTarget, item: SyncItem) -> str:
    root = target.path.rstrip("/")
    remote_path = f"{root}/{item.remote_path}" if root else item.remote_path
    if item.is_dir:
        remote_path = f"{remote_path.rstrip('/')}/"
    return f"{target.host}:{shlex.quote(remote_path)}"


def build_rsync_command(
    *,
    root: Path,
    target: HostTarget,
    item: SyncItem,
    dry_run: bool,
    rsync_bin: str,
    ssh_command: str | None,
) -> list[str]:
    cmd = [rsync_bin, "-az", "--itemize-changes"]
    if dry_run:
        cmd.append("--dry-run")
    for pattern in RSYNC_EXCLUDES:
        cmd.extend(["--exclude", pattern])
    if ssh_command:
        cmd.extend(["-e", ssh_command])

    source = root / item.source
    source_arg = f"{source}/" if item.is_dir else str(source)
    cmd.extend([source_arg, remote_destination(target, item)])
    return cmd


def run_rsync_commands(
    *,
    targets: Sequence[HostTarget],
    root: Path,
    dry_run: bool,
    rsync_bin: str,
    ssh_command: str | None,
) -> int:
    failures = 0
    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"BD Calendar deploy mode: {mode}", flush=True)
    print("Syncing: src/, static/, templates/, pyproject.toml", flush=True)

    for target in targets:
        print(f"\n==> {target.host} | {target.path}", flush=True)
        for item in SYNC_ITEMS:
            cmd = build_rsync_command(
                root=root,
                target=target,
                item=item,
                dry_run=dry_run,
                rsync_bin=rsync_bin,
                ssh_command=ssh_command,
            )
            print(f"+ {shlex.join(cmd)}", flush=True)
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                failures += 1
                print(f"rsync failed for {target.host}:{item.remote_path} ({result.returncode})", file=sys.stderr)

    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deploy_bdca",
        description="Deploy Biodynamic Calendar source, static assets, templates, and pyproject.toml with rsync.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply changes to remote hosts.")
    mode.add_argument("--dry-run", "--dryrun", dest="dry_run", action="store_true", help="Preview rsync changes.")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("apply", "dryrun", "dry-run"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--hosts",
        default=None,
        help=f"Host file path. Defaults to {DEFAULT_HOST_FILE}.",
    )
    parser.add_argument("--rsync", default="rsync", help="rsync executable to use.")
    parser.add_argument("--ssh", default=None, help="Optional remote shell command, such as 'ssh -p 2222'.")
    return parser


def resolve_dry_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> bool:
    if args.apply and args.mode in {"dryrun", "dry-run"}:
        parser.error("--apply cannot be combined with dryrun")
    if args.dry_run and args.mode == "apply":
        parser.error("--dry-run cannot be combined with apply")
    return not (args.apply or args.mode == "apply")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = repo_root()
    dry_run = resolve_dry_run(args, parser)

    try:
        validate_sources(root)
        hosts_path = host_file_path(args.hosts, root)
        targets = parse_host_file(hosts_path)
        validate_not_self_targets(targets, root)
    except OSError as exc:
        parser.exit(2, f"{exc}\n")
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")

    return run_rsync_commands(
        targets=targets,
        root=root,
        dry_run=dry_run,
        rsync_bin=args.rsync,
        ssh_command=args.ssh,
    )


if __name__ == "__main__":
    raise SystemExit(main())

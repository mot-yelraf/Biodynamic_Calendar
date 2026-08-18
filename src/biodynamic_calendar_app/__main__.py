from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="biodynamic-calendar-server")
    binding = parser.add_mutually_exclusive_group()
    binding.add_argument(
        "--host",
        default=None,
        help="Network interface to bind. Defaults to 0.0.0.0 for LAN access.",
    )
    binding.add_argument(
        "--lan",
        action="store_true",
        help="Bind to 0.0.0.0 for LAN access (the default; retained for compatibility).",
    )
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Port to listen on.")
    return parser


def _print_browse_hint(host: str, port: int) -> None:
    local_url = f"http://127.0.0.1:{port}"
    if host == "0.0.0.0":
        lines = [
            "BD Calendar is starting on all network interfaces.",
            f"Browse on this computer: {local_url}",
            f"Browse from another device: http://<this-computer-ip>:{port}",
        ]
    elif host in {"127.0.0.1", "localhost", "::1"}:
        lines = [
            "BD Calendar is starting locally.",
            f"Browse on this computer: {local_url}",
            "For LAN access, restart with: biodynamic-calendar-server --lan",
        ]
    else:
        lines = [
            f"BD Calendar is starting on {host}.",
            f"Browse to: http://{host}:{port}",
        ]
    print("\n".join(lines), flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    host = "0.0.0.0" if args.lan else (args.host or DEFAULT_HOST)
    _print_browse_hint(host, args.port)
    uvicorn.run("biodynamic_calendar_app:app", host=host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

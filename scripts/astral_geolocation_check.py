#!/usr/bin/env python3
"""Live Astral geolocation diagnostic for the standalone calendar app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biodynamic_calendar_app.config_store import ConfigStore, probe_ip_geolocation_providers


def _text(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "--"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report live Astral location resolution for the standalone Biodynamic Calendar host."
    )
    parser.add_argument(
        "--force-auto",
        action="store_true",
        help="Ignore saved lat/lon and test automatic IP geolocation.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist a successful IP-geolocation result to ~/.biodynamic_calendar/config.json.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request provider timeout in seconds.",
    )
    parser.add_argument(
        "--all-providers",
        action="store_true",
        help="Print each configured provider response for comparison.",
    )
    args = parser.parse_args()

    store = ConfigStore()
    raw = store._read_raw_config() or {}
    resolved = store.resolve_location(
        persist_if_auto=bool(args.persist),
        force_auto=bool(args.force_auto),
        timeout_sec=float(args.timeout),
    )
    payload = resolved.as_payload()

    print(f"Active config: {store.config_path}")
    print("Saved Astral:")
    print(f"  latitude:  {_text(raw.get('latitude') or raw.get('LATITUDE'))}")
    print(f"  longitude: {_text(raw.get('longitude') or raw.get('LONGITUDE'))}")
    print(f"  timezone:  {_text(raw.get('timezone_name') or raw.get('TIMEZONE'))}")
    print(f"  source:    {_text(raw.get('location_source') or raw.get('SOURCE'))}")
    print(f"  provider:  {_text(raw.get('location_provider') or raw.get('PROVIDER'))}")
    if (raw.get("latitude") or raw.get("LATITUDE")) and (raw.get("longitude") or raw.get("LONGITUDE")) and not args.force_auto:
        print("  note: saved coordinates are present; use --force-auto to test IP geolocation.")

    print("Resolved Astral:")
    print(f"  source:    {_text(payload.get('source'))}")
    print(f"  provider:  {_text(payload.get('provider'))}")
    print(f"  latitude:  {_text(payload.get('lat'))}")
    print(f"  longitude: {_text(payload.get('lon'))}")
    print(f"  timezone:  {_text(payload.get('tz'))}")
    print(f"  altitude:  {_text(payload.get('altitude'))}")
    if payload.get("error"):
        print(f"  error:     {payload.get('error')}")
    if args.persist:
        persisted = payload.get("source") == "ip" and payload.get("lat") is not None and payload.get("lon") is not None
        print(f"Persisted: {'yes' if persisted else 'no'}")

    if args.all_providers:
        print("Provider Details:")
        for row in probe_ip_geolocation_providers(timeout_sec=float(args.timeout)):
            print(f"  {row['provider']}:")
            print(f"    status:    {_text(row.get('status'))}")
            print(f"    latitude:  {_text(row.get('lat'))}")
            print(f"    longitude: {_text(row.get('lon'))}")
            print(f"    timezone:  {_text(row.get('tz'))}")
            print(f"    city:      {_text(row.get('city'))}")
            print(f"    region:    {_text(row.get('region'))}")
            print(f"    ip:        {_text(row.get('ip'))}")
            if row.get("error"):
                print(f"    error:     {row.get('error')}")

    ok = payload.get("lat") is not None and payload.get("lon") is not None and bool(str(payload.get("tz") or "").strip())
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

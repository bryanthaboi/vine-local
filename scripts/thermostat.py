#!/usr/bin/env python3
"""Discover and read the Vine thermostat. No device-write operations exist here."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components/vine_local"))
from schema import ST300, from_data
from transport import ConnectionFailed, TuyaClient

if sys.platform == "darwin":
    default_private_dir = Path.home() / "Library/Application Support/VineLocal"
elif sys.platform == "win32":
    default_private_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VineLocal"
else:
    default_private_dir = (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vine-local"
    )
PRIVATE_DIR = Path(os.environ.get("VINE_LOCAL_CONFIG_DIR", str(default_private_dir)))
CONFIG = PRIVATE_DIR / "device.json"


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        if hasattr(os, "fchmod"):
            os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover", help="UDP metadata discovery; no key needed")
    discover.add_argument("--host", required=True)
    configure = commands.add_parser("configure", help="Enter local key privately in a terminal")
    configure.add_argument("--host", required=True)
    configure.add_argument("--device-id", required=True)
    configure.add_argument("--version", choices=["3.3", "3.4", "3.5"], default="3.5")
    configure.add_argument(
        "--schema-file", type=Path, help="Product schema for a model other than the ST300"
    )
    for name in ("status", "watch"):
        sub = commands.add_parser(name)
        sub.add_argument(
            "--raw-file",
            type=Path,
            help="Save full datapoints privately; may contain location/schedule information",
        )
        if name == "watch":
            sub.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if args.command == "discover":
        from tinytuya.scanner import devices

        with socket.socket() as sock:
            sock.settimeout(3)
            reachable = sock.connect_ex((args.host, 6668)) == 0
        results = devices(
            scantime=12,
            poll=False,
            forcescan=False,
            verbose=False,
            wantips=[args.host],
            tuyadevices=[],
        )
        record = next((r for r in results.values() if r.get("ip") == args.host), {})
        print(
            json.dumps(
                {
                    "ip": args.host,
                    "tcp_6668_open": reachable,
                    "device_id": record.get("gwId", record.get("id")),
                    "protocol_version": record.get("version"),
                    "product_id": record.get("productKey"),
                },
                indent=2,
            )
        )
        return 0 if record else 2
    if args.command == "configure":
        if not sys.stdin.isatty():
            parser.error(
                "Run configure in an interactive terminal; keys are never command arguments"
            )
        key = getpass.getpass("Thermostat local key (hidden): ")
        if len(key.encode()) != 16:
            parser.error("The local key must contain exactly 16 UTF-8 bytes")
        private_write(
            CONFIG,
            {
                "host": args.host,
                "device_id": args.device_id,
                "local_key": key,
                "protocol_version": args.version,
                "profile": from_data(json.loads(args.schema_file.read_text())).to_data()
                if args.schema_file
                else ST300.to_data(),
            },
        )
        print(f"Saved private connection settings to {CONFIG}")
        return 0
    if not CONFIG.exists():
        print(
            "Local key is missing. Run configure in an interactive terminal after obtaining it.",
            file=sys.stderr,
        )
        return 2
    if os.name != "nt" and CONFIG.stat().st_mode & 0o077:
        parser.error("Private device.json permissions are too broad; run chmod 600 on that file")
    if args.command == "watch" and args.interval < 10:
        parser.error("Use a polling interval of at least 10 seconds")
    config = json.loads(CONFIG.read_text())
    profile = from_data(config.get("profile", ST300.to_data()))
    client = TuyaClient(
        config["device_id"], config["host"], config["local_key"], config["protocol_version"]
    )
    with (PRIVATE_DIR / "device.lock").open("a") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                lock.write("0")
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            parser.error("Another thermostat script is connected")
        while True:
            try:
                dps = client.status()
            except ConnectionFailed as err:
                print(str(err), file=sys.stderr)
                if args.command == "status":
                    return 1
            else:
                if args.raw_file:
                    private_write(args.raw_file.expanduser(), dps)
                print(json.dumps(profile.decode(dps)), flush=True)
            if args.command == "status":
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)

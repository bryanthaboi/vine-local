#!/usr/bin/env python3
"""Bootstrap LAN access from a Vine account on Linux, Windows or macOS.

Prompts locally for email/password, fetches device keys through the signed Tuya
OEM API, verifies LAN access, and persists only the selected LAN credentials.
"""

import argparse
import getpass
import importlib
import json
import sys
import types
from pathlib import Path

from thermostat import CONFIG, private_write

package = types.ModuleType("vine_standalone")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/vine_local")]
sys.modules[package.__name__] = package
cloud = importlib.import_module("vine_standalone.cloud")
transport = importlib.import_module("vine_standalone.transport")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=cloud.REGIONS, default="us")
    parser.add_argument("--country-code", default="1")
    parser.add_argument("--host", help="Thermostat LAN IP; prompted when omitted")
    parser.add_argument(
        "--device-id", help="Select a specific thermostat when the account has several"
    )
    parser.add_argument(
        "--schema-file",
        type=Path,
        help="Export product metadata only, then exit without saving credentials",
    )
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("Use an interactive terminal so the password can be entered privately")
    email = input("Vine account email: ").strip()
    print(
        "Login goes directly to Tuya's Vine authentication servers over HTTPS. Passwords and sessions are not saved."
    )
    password = getpass.getpass("Vine password (hidden, not saved): ")
    try:
        devices = cloud.fetch_devices(email, password, args.region, args.country_code)
    except cloud.CloudError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        password = None
    if not devices:
        print("No Vine Wi-Fi thermostat with a local key was found in this account.")
        return 2
    identifier = args.device_id
    if identifier is None:
        if len(devices) == 1:
            identifier = next(iter(devices))
        else:
            for identifier, device in devices.items():
                print(identifier, device["name"])
            identifier = input("Device ID to connect: ").strip()
    if identifier not in devices:
        print("That thermostat was not found in the signed-in account.")
        return 2
    device = devices[identifier]
    if args.schema_file:
        args.schema_file.write_text(json.dumps(device["schema_export"], indent=2) + "\n")
        print(
            "Exported product metadata only. No credentials, account data or device state were written."
        )
        return 0
    if device["profile"] is None:
        print(
            "Unsupported product schema. Use --schema-file to export product metadata for a support report."
        )
        return 2
    host = args.host or input("Thermostat LAN IP: ").strip()
    try:
        client = transport.TuyaClient(identifier, host, device["local_key"], "auto")
        client.status()
    except transport.ConnectionFailed as error:
        print(str(error), file=sys.stderr)
        return 1
    private_write(
        CONFIG,
        {
            "host": host,
            "device_id": identifier,
            "local_key": device["local_key"],
            "protocol_version": client.version,
            "profile": device["profile"],
        },
    )
    print(
        "Signed in, retrieved the local key, verified LAN access, and saved private connection settings."
    )
    print(
        "The Vine password and cloud session were not saved. Use thermostat.py status for local reads."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# standalone tools

Python 3.13 or newer:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/vine_account.py
.venv/bin/python scripts/thermostat.py status
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe`.

The account tool prompts locally for email/password with hidden password input.
It retrieves the selected device's key and profile, verifies a LAN read and saves
only connection settings. `--region` and `--country-code` select the account region.
`--host` supplies an IP instead of prompting. Normal CLI output contains only
allowlisted thermostat readings.

```sh
python scripts/thermostat.py discover --host 192.0.2.21
python scripts/vine_account.py --schema-file product-schema.json
```

`--schema-file` exports product metadata and exits without writing credentials or
contacting the thermostat. It can export an unsupported model's schema for a
support report.

For manual ST300 setup:

```sh
python scripts/thermostat.py configure --host 192.0.2.21 --device-id YOUR_DEVICE_ID
```

The key is entered privately, never as a command argument. Another model requires
`--schema-file product-schema.json` on `configure`.

| Platform | Private settings file |
| --- | --- |
| macOS | `~/Library/Application Support/VineLocal/device.json` |
| Linux | `~/.config/vine-local/device.json` |
| Windows | `%LOCALAPPDATA%/VineLocal/device.json` |

`VINE_LOCAL_CONFIG_DIR` overrides the directory. POSIX file permissions are 0600.
On Windows, use a private user directory and its normal account access controls.

`watch --interval 30` polls until stopped. Stop it before enabling Home Assistant
for the same thermostat. The CLI exposes no device-write command.

`status --raw-file /private/path/status.json` saves every datapoint. These values
may include schedules or location information. Keep that file private.

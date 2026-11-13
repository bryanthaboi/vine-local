# device support

The Vine account API supplies a product ID and full product schema for each
thermostat. A schema describes datapoint codes, IDs, data types, read/write access,
units, scales, steps, bounds and enum values. It does not by itself prove that a
model's firmware behaves correctly on the LAN.

Vine Local compiles those fields into a thermostat profile during setup and stores
only the profile needed for local operation. It does not need a hardcoded product
ID for every compatible model. `schema.py` is the source of truth for accepted
codes and capability checks.

| Capability | Required schema fields |
| --- | --- |
| Power | Writable boolean `switch` |
| Mode | Writable enum `mode` with explicit `heat` or `cool` |
| Current temperature | `temp_current` and/or `temp_current_f`, with declared units and scale |
| Target temperature | Writable `temp_set` and/or `temp_set_f`, with bounds, step and scale |
| Unit selection | `temp_unit_convert` when both Celsius and Fahrenheit fields exist |
| Heat/cool range | `auto` mode plus `heat_temp_set`/`heat_temp_set_f` and `cool_set_temp`/`cool_set_temp_f` for every supported unit |
| Fan | Writable `fan_mode` enum |
| Hold | Writable `run_mode` enum containing recognized hold values |
| Humidity | Numeric `humidity` |
| Running activity | `work_state`, never inferred from the selected mode |

The compiler rejects duplicate IDs/codes, read-only targets, missing temperature
bounds and ambiguous unit selection. It never interprets a generic `auto` mode as
heat/cool without separate heat and cool targets.

The bundled ST300 profile comes from its full manufacturer schema. It is used for
manual ST300 setup and upgrades from the ST300-only integration. Its fan mode is
DP64. DP28 controls display brightness, and DP108/109 are historical averages.
They are not fan mode or temperature targets.

## adding another model

Try normal Vine account setup first. A compatible schema is used automatically.
Only the ST300 has been tested on hardware, so other models remain unverified.

If setup rejects the schema, export product metadata:

```sh
python scripts/vine_account.py --schema-file product-schema.json
```

Attach that file to a device-support issue with the model and firmware version.
The export excludes account data, local keys and current datapoint values. It is
safe to inspect before sharing. Do not attach files created with `--raw-file`.

A change to the compiler needs a product-only fixture and tests for decoding,
units, bounds and generated commands. Physical verification should start with
reads, then a target write retaining the current setting. State clearly which
controls have actually been tested.

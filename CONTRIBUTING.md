# contributing

Use Python 3.14 for the Home Assistant test environment:

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/core_smoke.py
.venv/bin/python scripts/build_release.py
```

These commands match the Python CI job. The integration is also checked by
hassfest and HACS validation on GitHub. Tests use fixtures and mocked transports;
they do not log in to a real account or control a thermostat.

For a new model, include product metadata and tests with different datapoint IDs
and scales. Do not assume another model shares the ST300 layout. See
[device support](docs/devices.md).

Do not commit passwords, account sessions, local keys, raw device responses,
private Home Assistant configuration or machine-specific paths. Do not enable
provider debug logs. Diagnostics and schema exports have separate allowlists.

"""Run in a temporary Core subprocess, never in the live HA event loop."""

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path


async def main():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "vine_test_component",
        root / "custom_components/vine_local/__init__.py",
        submodule_search_locations=[str(root / "custom_components/vine_local")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    modules = {
        name: importlib.import_module(f"vine_test_component.{name}")
        for name in ("climate", "sensor", "binary_sensor", "config_flow", "diagnostics")
    }
    from unittest.mock import patch

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import UpdateFailed

    hass = HomeAssistant(str(root / "unused-config"))
    from vine_test_component.schema import ST300

    entry = ConfigEntry(
        version=2,
        minor_version=1,
        domain="vine_local",
        title="Test ST300",
        data={
            "device_id": "test-device",
            "host": "192.0.2.1",
            "local_key": "example-key-1234",
            "protocol_version": "3.5",
            "profile": ST300.to_data(),
        },
        source="user",
        unique_id="test-device",
        options={},
        discovery_keys={},
        subentries_data=[],
    )
    coordinator = module.VineCoordinator(hass, entry)
    coordinator.async_set_updated_data({"23": "f", "29": 62, "17": 620, "1": True})
    entry.runtime_data = coordinator
    entities = []
    await modules["sensor"].async_setup_entry(hass, entry, lambda values: entities.extend(values))
    await modules["binary_sensor"].async_setup_entry(
        hass, entry, lambda values: entities.extend(values)
    )
    assert len(entities) == 8
    assert entities[0].native_value == 62
    assert entities[0].native_unit_of_measurement == "°F"
    assert entities[-1].is_on is True
    climate_entities = []
    await modules["climate"].async_setup_entry(
        hass, entry, lambda values: climate_entities.extend(values)
    )
    climate = climate_entities[0]
    from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode

    coordinator.async_set_updated_data(
        {
            "23": "f",
            "29": 69,
            "17": 690,
            "1": True,
            "2": "heat",
            "3": "idle",
            "64": "auto",
            "58": "short",
        }
    )
    assert climate.hvac_mode == HVACMode.HEAT
    assert climate.hvac_action == HVACAction.IDLE
    assert climate.target_temperature == 69
    assert climate.fan_mode == "auto"
    assert climate.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    coordinator.async_set_updated_data({"23": "f", "1": True, "2": "auto", "55": 68, "59": 72})
    assert climate.hvac_mode == HVACMode.HEAT_COOL
    assert climate.target_temperature is None
    assert climate.target_temperature_low == 68 and climate.target_temperature_high == 72
    assert climate.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    fresh_c = {"23": "c", "2": "heat", "1": True, "16": 225, "24": 21}
    from homeassistant.exceptions import HomeAssistantError

    with (
        patch.object(coordinator.client, "status", return_value=fresh_c),
        patch.object(coordinator.client, "command", return_value=fresh_c) as command,
    ):
        await climate.async_set_temperature(temperature=22.5)
        assert command.call_args.args[0] == {"16": 225}
        try:
            await climate.async_set_temperature(temperature=99)
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("Out-of-range temperatures must be rejected")
        assert command.call_count == 1
        assert coordinator.last_update_success is True
    coordinator._remember_mode({"2": "cool"})
    coordinator._remember_mode({"2": "off"})
    assert coordinator.last_active_mode == "cool"
    assert entities[0].available is True
    coordinator.last_update_success = False
    assert entities[0].available is False
    with patch.object(
        coordinator.client, "status", side_effect=module.ConnectionFailed("Read failed")
    ):
        try:
            await coordinator._async_update_data()
        except UpdateFailed:
            pass
        else:
            raise AssertionError("Polling failures must make entities unavailable")
    diagnostics = await modules["diagnostics"].async_get_config_entry_diagnostics(hass, entry)
    assert "example-key-1234" not in str(diagnostics)
    assert "test-device" not in str(diagnostics)
    flow = modules["config_flow"].VineConfigFlow()
    flow.hass = hass
    form = await flow.async_step_user()
    assert form["type"] == "menu" and form["step_id"] == "user"
    form = await flow.async_step_local()
    valid = form["data_schema"](
        {
            "device_id": "test-device",
            "host": "192.0.2.1",
            "local_key": "example-key-1234",
            "name": entry.title,
        }
    )
    assert valid["local_key"] == "example-key-1234"
    account_flow = modules["config_flow"].VineConfigFlow()
    account_flow.hass = hass
    selected = {
        "test-st300": {
            "device_id": "test-st300",
            "name": "ST300",
            "host": "",
            "local_key": "example-key-1234",
            "protocol_version": "auto",
            "product_id": ST300.product_id,
            "profile": ST300.to_data(),
        }
    }
    with (
        patch.object(modules["config_flow"], "fetch_devices", return_value=selected),
        patch.object(modules["config_flow"], "discover_devices", return_value={}),
    ):
        device_form = await account_flow.async_step_account(
            {
                "email": "owner@example.invalid",
                "password": "private-test-password",
                "country_code": "1",
                "region": "us",
            }
        )
    assert device_form["step_id"] == "device"
    assert "private-test-password" not in str(account_flow.__dict__)
    connect_form = await account_flow.async_step_device({"device_id": "test-st300"})
    assert connect_form["step_id"] == "connect"
    from unittest.mock import AsyncMock

    with (
        patch.object(account_flow, "async_set_unique_id", new=AsyncMock()),
        patch.object(account_flow, "_abort_if_unique_id_configured"),
        patch.object(modules["config_flow"], "TuyaClient") as client,
    ):
        client.return_value.status.return_value = {"23": "f", "29": 69, "1": True, "2": "heat"}
        client.return_value.version = "3.5"
        result = await account_flow.async_step_connect({"name": "ST300", "host": "192.0.2.1"})
    assert result["type"] == "create_entry"
    assert set(result["data"]) == {"device_id", "host", "local_key", "protocol_version", "profile"}
    assert result["data"]["protocol_version"] == "3.5"
    assert "protocol_version" not in [str(key) for key in connect_form["data_schema"].schema]
    assert "private-test-password" not in str(result)
    print(
        "Core smoke passed: flow form, climate + 8 sensors, heat/auto, units, unavailability and redacted diagnostics"
    )


if __name__ == "__main__":
    asyncio.run(main())

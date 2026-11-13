"""Only allowlisted non-secret device state enters diagnostics."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "model": coordinator.profile.model,
        "profile": coordinator.profile.to_data(),
        "protocol_version": entry.data["protocol_version"],
        "last_update_success": coordinator.last_update_success,
        "values": coordinator.profile.decode(coordinator.data or {}),
    }

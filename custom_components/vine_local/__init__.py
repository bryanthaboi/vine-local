"""Local ST300 control and monitoring. No cloud calls."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY, CONF_PROTOCOL
from .schema import ST300, from_data
from .transport import ConnectionFailed, TuyaClient

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR]
_LOGGER = logging.getLogger(__name__)


class VineCoordinator(DataUpdateCoordinator[dict]):
    """One off-loop LAN query shared by all entities every 30 seconds."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name="Vine Local",
            config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self.profile = from_data(entry.data["profile"])
        self.client = TuyaClient(
            entry.data[CONF_DEVICE_ID],
            entry.data[CONF_HOST],
            entry.data[CONF_LOCAL_KEY],
            entry.data[CONF_PROTOCOL],
            controls=self.profile.controls,
        )
        self.command_lock = asyncio.Lock()
        self.last_active_mode = None

    def _remember_mode(self, dps):
        mode = self.profile.mode.read(dps)
        if mode in ("heat", "cool", "auto", "emheat"):
            self.last_active_mode = mode
        return dps

    async def _async_update_data(self):
        try:
            async with self.command_lock:
                return self._remember_mode(
                    await self.hass.async_add_executor_job(self.client.status)
                )
        except ConnectionFailed as err:
            raise UpdateFailed(str(err)) from None

    async def async_command(self, build_command):
        """Refresh before building writes so an app-side unit change is respected."""
        async with self.command_lock:
            try:
                fresh = await self.hass.async_add_executor_job(self.client.status)
                self._remember_mode(fresh)
                command = build_command(fresh)
                result = await self.hass.async_add_executor_job(self.client.command, command)
            except ValueError as err:
                self.async_set_updated_data(fresh)
                raise HomeAssistantError(str(err)) from None
            except ConnectionFailed as err:
                self.async_set_update_error(UpdateFailed(str(err)))
                raise HomeAssistantError(str(err)) from None
            self.async_set_updated_data(self._remember_mode(result))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = VineCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, version=2, data={**entry.data, "profile": ST300.to_data()}
        )
    return entry.version == 2

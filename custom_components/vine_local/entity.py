"""Shared device metadata."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN


class VineEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, key, name):
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{key}"
        self._attr_name = name
        self.key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            manufacturer="Vine",
            model=self.coordinator.profile.model,
            name=entry.title,
        )

    @property
    def values(self):
        return self.coordinator.profile.decode(self.coordinator.data)

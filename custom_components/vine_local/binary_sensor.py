"""Power setting, not an inferred heat/cool activity indicator."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import VineEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VinePower(entry, "power", "Power")])


class VinePower(VineEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.values["power"]

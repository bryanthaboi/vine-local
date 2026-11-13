"""Read-only temperature, humidity and raw operating mode sensors."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .entity import VineEntity

SENSORS = (
    ("current_temperature", "Temperature", SensorDeviceClass.TEMPERATURE),
    ("target_temperature", "Target temperature", SensorDeviceClass.TEMPERATURE),
    ("humidity", "Humidity", SensorDeviceClass.HUMIDITY),
    ("mode", "Mode", None),
    ("fan_mode", "Fan mode", None),
    ("display_brightness", "Screen brightness", None),
    ("fault", "Fault code", None),
)


async def async_setup_entry(hass, entry, async_add_entities):
    profile = entry.runtime_data.profile
    optional = {
        "humidity": profile.humidity,
        "fan_mode": profile.fan,
        "display_brightness": profile.brightness,
        "fault": profile.fault,
    }
    async_add_entities(
        VineSensor(entry, key, name, device_class)
        for key, name, device_class in SENSORS
        if key not in optional or optional[key]
    )


class VineSensor(VineEntity, SensorEntity):
    def __init__(self, entry, key, name, device_class):
        super().__init__(entry, key, name)
        self._attr_device_class = device_class
        if key in ("current_temperature", "humidity"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if key == "fault":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.values[self.key]

    @property
    def native_unit_of_measurement(self):
        if self.device_class == SensorDeviceClass.TEMPERATURE:
            return self.values["unit"]
        if self.device_class == SensorDeviceClass.HUMIDITY:
            return PERCENTAGE
        return None

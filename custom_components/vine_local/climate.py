"""Climate controls selected from the thermostat's product profile."""

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .entity import VineEntity
from .schema import PRESETS

MODES = {
    HVACMode.OFF: "off",
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
    HVACMode.HEAT_COOL: "auto",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VineClimate(entry, "climate", None)])


class VineClimate(VineEntity, ClimateEntity):
    _enable_turn_on_off_backwards_compatibility = False

    @property
    def hvac_modes(self):
        return [key for key, value in MODES.items() if value in self.coordinator.profile.modes]

    @property
    def fan_modes(self):
        field = self.coordinator.profile.fan
        return field.choices if field else None

    @property
    def preset_modes(self):
        field = self.coordinator.profile.hold
        return [key for key, value in PRESETS.items() if value in field.choices] if field else None

    @property
    def available(self):
        return super().available and self.values["unit"] is not None

    @property
    def supported_features(self):
        temperature = (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            if self.hvac_mode == HVACMode.HEAT_COOL
            else ClimateEntityFeature.TARGET_TEMPERATURE
        )
        features = temperature | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if self.coordinator.profile.fan:
            features |= ClimateEntityFeature.FAN_MODE
        if self.coordinator.profile.hold:
            features |= ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def temperature_unit(self):
        return (
            UnitOfTemperature.FAHRENHEIT
            if self.values["unit"] == "°F"
            else UnitOfTemperature.CELSIUS
        )

    @property
    def current_temperature(self):
        return self.values["current_temperature"]

    @property
    def current_humidity(self):
        return self.values["humidity"]

    @property
    def target_temperature(self):
        return None if self.hvac_mode == HVACMode.HEAT_COOL else self.values["target_temperature"]

    @property
    def target_temperature_low(self):
        return self.values["heat_target"] if self.hvac_mode == HVACMode.HEAT_COOL else None

    @property
    def target_temperature_high(self):
        return self.values["cool_target"] if self.hvac_mode == HVACMode.HEAT_COOL else None

    @property
    def target_temperature_step(self):
        profile = self.coordinator.profile
        field = (profile.heat if self.hvac_mode == HVACMode.HEAT_COOL else profile.target).get(
            profile.active_unit(self.coordinator.data)
        )
        return field.step if field else None

    @property
    def min_temp(self):
        try:
            return self.coordinator.profile.limits(self.coordinator.data)[0]
        except ValueError:
            return None

    @property
    def max_temp(self):
        try:
            return self.coordinator.profile.limits(self.coordinator.data)[1]
        except ValueError:
            return None

    @property
    def hvac_mode(self):
        if self.values["power"] is False:
            return HVACMode.OFF
        mode = self.values["mode"]
        return (
            HVACMode.HEAT
            if mode == "emheat"
            else next((k for k, v in MODES.items() if v == mode and k in self.hvac_modes), None)
        )

    @property
    def hvac_action(self):
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return {
            "idle": HVACAction.IDLE,
            "heating": HVACAction.HEATING,
            "cooling": HVACAction.COOLING,
            "em_heating": HVACAction.HEATING,
            "aux_heating": HVACAction.HEATING,
            "dehumidifier": HVACAction.DRYING,
        }.get(self.values["action"])

    @property
    def fan_mode(self):
        return self.values["fan_mode"]

    @property
    def preset_mode(self):
        return next((k for k, v in PRESETS.items() if v == self.values["hold"]), None)

    async def async_set_temperature(self, **kwargs):
        def build(dps):
            return self.coordinator.profile.temperature_command(
                dps,
                temperature=kwargs.get(ATTR_TEMPERATURE),
                low=kwargs.get("target_temp_low"),
                high=kwargs.get("target_temp_high"),
            )

        await self.coordinator.async_command(build)

    async def async_set_hvac_mode(self, hvac_mode):
        def build(dps):
            if hvac_mode not in MODES:
                raise ValueError("Unsupported HVAC mode")
            return self.coordinator.profile.mode_command(MODES[hvac_mode])

        await self.coordinator.async_command(build)

    async def async_set_fan_mode(self, fan_mode):
        def build(dps):
            field = self.coordinator.profile.fan
            if field is None or fan_mode not in field.choices:
                raise ValueError("Unsupported fan mode")
            return field.write(fan_mode)

        await self.coordinator.async_command(build)

    async def async_set_preset_mode(self, preset_mode):
        def build(dps):
            field = self.coordinator.profile.hold
            if field is None or preset_mode not in self.preset_modes:
                raise ValueError("Unsupported hold preset")
            return field.write(PRESETS[preset_mode])

        await self.coordinator.async_command(build)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self):
        def build(dps):
            mode = self.coordinator.last_active_mode
            if mode is None:
                raise ValueError(
                    "Select Heat, Cool or Heat/Cool to turn on; no previous mode is known"
                )
            profile = self.coordinator.profile
            return profile.power.write(True) | profile.mode.write(mode)

        await self.coordinator.async_command(build)

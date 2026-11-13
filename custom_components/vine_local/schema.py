"""Thermostat controls compiled from the manufacturer's product schema."""

from __future__ import annotations

import json
import math
from pathlib import Path

PRODUCT_ID = "qn4upx5kzja3rg1l"
PRESETS = {"none": "close", "temporary_hold": "short", "permanent_hold": "permanent"}
UNIT_NAMES = {"c": "°C", "f": "°F"}


def numeric(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


class UnsupportedProfile(ValueError):
    pass


class Field:
    def __init__(self, data):
        self.id = str(data["id"])
        self.code = data["code"]
        self.mode = data["mode"]
        self.property = data["property"]
        self.type = self.property["type"]
        self.scale = self.property.get("scale", 0)
        if (
            not self.id.isdecimal()
            or not isinstance(self.scale, int)
            or isinstance(self.scale, bool)
            or not 0 <= self.scale <= 6
        ):
            raise UnsupportedProfile("Invalid datapoint definition")

    @property
    def writable(self):
        return self.mode == "rw"

    @property
    def choices(self):
        return [
            v for v in self.property.get("range", []) if isinstance(v, str) and 0 < len(v) <= 32
        ]

    def read(self, dps):
        value = dps.get(self.id)
        if self.type == "value":
            value = numeric(value)
            return value / 10**self.scale if value is not None else None
        if self.type == "bool":
            return value if isinstance(value, bool) else None
        if self.type == "enum":
            return value if value in self.choices else None
        if self.type == "bitmap":
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        return None

    def bounds(self):
        minimum, maximum = numeric(self.property.get("min")), numeric(self.property.get("max"))
        if minimum is None or maximum is None or minimum >= maximum:
            raise UnsupportedProfile("Missing temperature bounds")
        return minimum / 10**self.scale, maximum / 10**self.scale

    @property
    def step(self):
        step = numeric(self.property.get("step"))
        if step is None or step <= 0:
            raise UnsupportedProfile("Missing temperature step")
        return step / 10**self.scale

    def write(self, value):
        if not self.writable:
            raise ValueError("This datapoint is read-only")
        if self.type == "value":
            value = numeric(value)
            minimum, maximum = self.bounds()
            if value is None or not minimum <= value <= maximum:
                raise ValueError(f"Temperature must be between {minimum} and {maximum}")
            raw = value * 10**self.scale
            step = self.property["step"]
            offset = (raw - self.property["min"]) / step
            if not math.isclose(offset, round(offset), abs_tol=1e-6):
                raise ValueError(f"Temperature must use increments of {self.step}")
            return {self.id: round(raw)}
        if self.type == "bool" and isinstance(value, bool):
            return {self.id: value}
        if self.type == "enum" and value in self.choices:
            return {self.id: value}
        raise ValueError("Unsupported thermostat value")


class ThermostatProfile:
    def __init__(self, product_id, schema):
        if not isinstance(schema, list) or len(schema) > 256:
            raise UnsupportedProfile("Invalid product schema")
        self.product_id = str(product_id)[:80]
        self.model = "ST300" if product_id == PRODUCT_ID else "Thermostat"
        self.fields = {}
        self.records = {}
        ids = set()
        for record in schema:
            try:
                field = Field(record)
            except (KeyError, TypeError, AttributeError):
                raise UnsupportedProfile("Invalid datapoint definition") from None
            if field.code in self.fields or field.id in ids:
                raise UnsupportedProfile("Duplicate datapoint definition")
            self.fields[field.code] = field
            self.records[field.code] = {
                "id": int(field.id),
                "code": field.code,
                "mode": field.mode,
                "property": field.property,
            }
            ids.add(field.id)
        self.power = self._field("switch", "bool", writable=True)
        self.mode = self._field("mode", "enum", writable=True)
        self.unit = self._field("temp_unit_convert", "enum")
        self.current = self._temperatures("temp_current", "temp_current_f")
        self.target = self._temperatures("temp_set", "temp_set_f", writable=True)
        self.heat = self._temperatures("heat_temp_set", "heat_temp_set_f", writable=True)
        self.cool = self._temperatures("cool_set_temp", "cool_set_temp_f", writable=True)
        self.minimum = self._temperatures("lower_temp", "lower_temp_f")
        self.maximum = self._temperatures("upper_temp", "upper_temp_f")
        self.units = set(self.current) & set(self.target)
        if (
            not self.power
            or not self.mode
            or not self.units
            or not {"heat", "cool"} & set(self.mode.choices)
        ):
            raise UnsupportedProfile(
                "The schema does not describe a supported heat/cool thermostat"
            )
        if len(self.units) > 1 and (not self.unit or not self.units <= set(self.unit.choices)):
            raise UnsupportedProfile("The active temperature unit cannot be determined")
        for unit in self.units:
            self.target[unit].bounds()
            _ = self.target[unit].step
        self.has_range = self.units <= set(self.heat) & set(self.cool)
        if self.has_range:
            for field in (*self.heat.values(), *self.cool.values()):
                field.bounds()
                _ = field.step
        self.modes = [
            m
            for m in ("off", "heat", "cool", "auto")
            if m == "off" or m in self.mode.choices and (m != "auto" or self.has_range)
        ]
        self.fan = self._field("fan_mode", "enum", writable=True)
        self.hold = self._field("run_mode", "enum", writable=True)
        if self.hold and not set(self.hold.choices) <= set(PRESETS.values()):
            self.hold = None
        self.action = self._field("work_state", "enum")
        self.humidity = self._field("humidity", "value")
        self.fault = self._field("fault", "bitmap")
        self.brightness = self._field("level", "enum") if product_id == PRODUCT_ID else None
        self.controls = {
            f.id
            for f in (
                self.power,
                self.mode,
                self.fan,
                self.hold,
                *self.target.values(),
                *self.heat.values(),
                *self.cool.values(),
            )
            if f
        }

    def _field(self, code, kind, writable=False):
        field = self.fields.get(code)
        return (
            field
            if field
            and field.type == kind
            and "r" in field.mode
            and (not writable or field.writable)
            else None
        )

    def _temperatures(self, c_code, f_code, writable=False):
        result = {}
        units = {"c": ("℃", "°C", "C", "c"), "f": ("℉", "°F", "F", "f")}
        for unit, code in (("c", c_code), ("f", f_code)):
            field = self._field(code, "value", writable)
            if field and field.property.get("unit") in units[unit]:
                result[unit] = field
        return result

    def active_unit(self, dps):
        unit = self.unit.read(dps) if self.unit else next(iter(self.units))
        return unit if unit in self.units else None

    def decode(self, dps):
        unit = self.active_unit(dps)

        def read(field):
            return field.read(dps) if field else None

        humidity = read(self.humidity)
        return {
            "unit": UNIT_NAMES.get(unit),
            "current_temperature": read(self.current.get(unit)),
            "target_temperature": read(self.target.get(unit)),
            "heat_target": read(self.heat.get(unit)),
            "cool_target": read(self.cool.get(unit)),
            "humidity": humidity if humidity is not None and 0 <= humidity <= 100 else None,
            "power": read(self.power),
            "mode": read(self.mode),
            "action": read(self.action),
            "fan_mode": read(self.fan),
            "hold": read(self.hold),
            "fault": read(self.fault),
            "display_brightness": read(self.brightness),
        }

    def limits(self, dps):
        unit = self.active_unit(dps)
        if unit is None:
            raise ValueError("The thermostat's temperature unit is unknown")
        low, high = self.target[unit].bounds()
        minimum, maximum = self.minimum.get(unit), self.maximum.get(unit)
        configured_low = minimum.read(dps) if minimum else None
        configured_high = maximum.read(dps) if maximum else None
        low = max(low, configured_low) if configured_low is not None else low
        high = min(high, configured_high) if configured_high is not None else high
        if low >= high:
            raise ValueError("The thermostat's temperature limits are invalid")
        return low, high

    def temperature_command(self, dps, temperature=None, low=None, high=None):
        unit = self.active_unit(dps)
        minimum, maximum = self.limits(dps)

        def write(field, value):
            if numeric(value) is None or not minimum <= value <= maximum:
                raise ValueError(f"Temperature must be between {minimum} and {maximum}")
            return field.write(value)

        mode = self.mode.read(dps)
        if mode == "auto" and self.has_range:
            if temperature is not None:
                raise ValueError("Heat/cool mode requires separate low and high targets")
            heat, cool = self.heat[unit], self.cool[unit]
            new_low = low if low is not None else heat.read(dps)
            new_high = high if high is not None else cool.read(dps)
            heat_write, cool_write = write(heat, new_low), write(cool, new_high)
            if new_low >= new_high:
                raise ValueError("Heating target must be below cooling target")
            if low is None and high is None:
                raise ValueError("Supply at least one target temperature")
            return (heat_write if low is not None else {}) | (
                cool_write if high is not None else {}
            )
        if (
            mode not in ("heat", "cool", "emheat")
            or low is not None
            or high is not None
            or temperature is None
        ):
            raise ValueError("Select heat or cool and supply a single target temperature")
        return write(self.target[unit], temperature)

    def mode_command(self, mode):
        if mode not in self.modes:
            raise ValueError("Unsupported HVAC mode")
        command = self.power.write(mode != "off")
        if mode != "off" or "off" in self.mode.choices:
            command |= self.mode.write(mode)
        return command

    def to_data(self):
        used = {
            f.code
            for f in (
                self.power,
                self.mode,
                self.unit,
                self.fan,
                self.hold,
                self.action,
                self.humidity,
                self.fault,
                self.brightness,
                *self.current.values(),
                *self.target.values(),
                *self.heat.values(),
                *self.cool.values(),
                *self.minimum.values(),
                *self.maximum.values(),
            )
            if f
        }
        return {
            "product_id": self.product_id,
            "schema": [self.records[code] for code in sorted(used)],
        }


def from_data(data):
    try:
        return ThermostatProfile(data["product_id"], data["schema"])
    except (KeyError, TypeError, AttributeError):
        raise UnsupportedProfile("Invalid saved product profile") from None


ST300_DATA = json.loads((Path(__file__).parent / "profiles/st300.json").read_text())
ST300 = from_data(ST300_DATA)

"""Product schemas control datapoint selection and command bounds."""

import copy
import importlib.util
import os
import unittest
from pathlib import Path

COMPONENT = Path(
    os.environ.get(
        "VINE_COMPONENT_PATH", Path(__file__).resolve().parents[1] / "custom_components/vine_local"
    )
)
spec = importlib.util.spec_from_file_location("product_schema_tests", COMPONENT / "schema.py")
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)


def different_product():
    fields = copy.deepcopy(schema.ST300_DATA["schema"])
    for field in fields:
        field["id"] += 200
        if field["code"] == "temp_current":
            field["property"].update(scale=1, min=0, max=500)
        if field["code"] == "temp_set":
            field["property"].update(scale=2, min=500, max=3700, step=25)
    return schema.ThermostatProfile("another-vine-product", fields)


class SchemaTests(unittest.TestCase):
    def test_other_product_uses_its_own_ids_and_scales(self):
        profile = different_product()
        state = {"223": "c", "202": "heat", "224": 213, "216": 2250, "201": True}
        self.assertEqual(profile.decode(state)["current_temperature"], 21.3)
        self.assertEqual(profile.decode(state)["target_temperature"], 22.5)
        self.assertEqual(profile.temperature_command(state, temperature=22.75), {"216": 2275})
        self.assertEqual(profile.mode_command("cool"), {"201": True, "202": "cool"})
        self.assertNotIn("17", profile.controls)
        self.assertEqual(profile.model, "Thermostat")

    def test_new_scale_step_and_bounds_are_enforced(self):
        profile = different_product()
        state = {"223": "c", "202": "heat"}
        for value in (22.6, 38, True, float("inf")):
            with self.assertRaises(ValueError):
                profile.temperature_command(state, temperature=value)

    def test_single_unit_heating_model_has_no_fan_hold_or_heat_cool(self):
        fields = [
            copy.deepcopy(f)
            for f in schema.ST300_DATA["schema"]
            if f["code"] in ("switch", "mode", "temp_current", "temp_set")
        ]
        next(f for f in fields if f["code"] == "mode")["property"]["range"] = ["heat", "auto"]
        profile = schema.ThermostatProfile("heating-only", fields)
        self.assertEqual(profile.decode({"24": 21, "16": 225})["unit"], "°C")
        self.assertEqual(profile.modes, ["off", "heat"])
        self.assertIsNone(profile.fan)
        self.assertIsNone(profile.hold)
        self.assertEqual(profile.mode_command("off"), {"1": False})
        with self.assertRaises(ValueError):
            profile.mode_command("auto")

    def test_read_only_target_is_never_treated_as_a_control(self):
        fields = copy.deepcopy(schema.ST300_DATA["schema"])
        for field in fields:
            if field["code"] in ("temp_set", "temp_set_f"):
                field["mode"] = "ro"
        with self.assertRaises(schema.UnsupportedProfile):
            schema.ThermostatProfile("read-only", fields)

    def test_unknown_unit_and_invalid_dynamic_limits_block_commands(self):
        profile = different_product()
        for state in ({"202": "heat"}, {"202": "heat", "223": "f", "220": 90, "218": 60}):
            with self.assertRaises(ValueError):
                profile.temperature_command(state, temperature=70)

    def test_round_trip_profile_contains_no_schedule_or_geofence_fields(self):
        exported = different_product().to_data()
        codes = {field["code"] for field in exported["schema"]}
        self.assertFalse(codes & {"geo_location", "change_week_program", "vacation", "EnergyData"})
        restored = schema.from_data(exported)
        self.assertEqual(
            restored.temperature_command({"223": "f", "202": "heat"}, temperature=69), {"217": 690}
        )

    def test_ambiguous_duplicate_datapoints_are_rejected(self):
        fields = copy.deepcopy(schema.ST300_DATA["schema"])
        fields.append(fields[0])
        with self.assertRaises(schema.UnsupportedProfile):
            schema.ThermostatProfile("ambiguous", fields)

    def test_missing_bounds_or_step_cannot_enable_a_write(self):
        for key in ("min", "max", "step"):
            fields = copy.deepcopy(schema.ST300_DATA["schema"])
            for field in fields:
                if field["code"] == "temp_set":
                    field["property"].pop(key)
            with self.assertRaises(schema.UnsupportedProfile):
                schema.ThermostatProfile("incomplete", fields)

    def test_product_schema_never_infers_heating_from_heat_mode(self):
        self.assertIsNone(schema.ST300.decode({"23": "f", "2": "heat"})["action"])


if __name__ == "__main__":
    unittest.main()

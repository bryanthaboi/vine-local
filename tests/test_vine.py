"""Tests for unit selection, protocol failure handling and connection ownership."""

import concurrent.futures
import importlib.util
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/vine_local"


def load(name):
    spec = importlib.util.spec_from_file_location(f"vine_{name}", COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile = load("schema").ST300
transport = load("transport")


class ProfileTests(unittest.TestCase):
    def test_actual_fan_dp_is_not_the_display_brightness_dp(self):
        values = profile.decode({"28": "middle", "64": "auto", "108": 68, "109": 72})
        self.assertEqual(values["fan_mode"], "auto")
        self.assertEqual(values["display_brightness"], "middle")
        self.assertIsNone(values["heat_target"])
        self.assertIsNone(values["cool_target"])

    def test_control_range_and_temperature_units(self):
        state = {"23": "f", "2": "heat", "20": 50, "18": 96}
        self.assertEqual(profile.temperature_command(state, temperature=69), {"17": 690})
        for target in (49, 97, 69.25, True, float("nan")):
            with self.assertRaises(ValueError):
                profile.temperature_command(state, temperature=target)
        state["23"] = "c"
        self.assertEqual(profile.temperature_command(state, temperature=22.5), {"16": 225})

    def test_auto_targets_do_not_write_historical_averages_or_limits(self):
        state = {"23": "f", "2": "auto", "55": 68, "59": 72}
        self.assertEqual(profile.temperature_command(state, low=67, high=73), {"55": 67, "59": 73})
        with self.assertRaises(ValueError):
            profile.temperature_command(state, low=75)
        with self.assertRaises(ValueError):
            profile.temperature_command(state, temperature=69)

    def test_fahrenheit_uses_active_values_and_tenths_only_for_target(self):
        values = profile.decode(
            {"23": "f", "24": 0, "29": 62, "16": 50, "17": 620, "1": True, "2": "heat", "34": 70}
        )
        self.assertEqual(values["current_temperature"], 62)
        self.assertEqual(values["target_temperature"], 62)
        self.assertEqual(values["unit"], "°F")
        self.assertEqual(values["mode"], "heat")
        self.assertNotIn("hvac_action", values)

    def test_celsius_ignores_stale_fahrenheit(self):
        values = profile.decode({"23": "c", "24": 21, "29": 0, "16": 225, "17": 0})
        self.assertEqual(values["current_temperature"], 21)
        self.assertEqual(values["target_temperature"], 22.5)

    def test_unknown_unit_does_not_fabricate_temperatures(self):
        values = profile.decode({"24": 21, "29": 70, "34": 101})
        self.assertIsNone(values["unit"])
        self.assertIsNone(values["current_temperature"])
        self.assertIsNone(values["humidity"])

    def test_boolean_is_not_a_temperature_and_unknown_data_is_private(self):
        values = profile.decode({"23": "f", "29": True, "117": "private-location"})
        self.assertIsNone(values["current_temperature"])
        self.assertNotIn("private-location", str(values))


class TransportTests(unittest.TestCase):
    @patch.object(transport.tinytuya, "Device")
    def test_protocol_is_detected_with_reads_only(self, factory):
        factory.return_value.status.side_effect = [{"Error": "wrong protocol"}, {"dps": {"29": 69}}]
        client = transport.TuyaClient("device-id", "192.0.2.1", "example-key-1234")
        self.assertEqual(client.status(), {"29": 69})
        self.assertEqual(client.version, "3.4")
        self.assertEqual([call.kwargs["version"] for call in factory.call_args_list], [3.5, 3.4])
        factory.return_value.set_multiple_values.assert_not_called()
        with self.assertRaises(ValueError):
            client.command({"17": 690})

    @patch.object(transport.tinytuya, "Device")
    def test_protocol_detection_stops_after_supported_versions(self, factory):
        factory.return_value.status.return_value = {"Error": "failed"}
        client = transport.TuyaClient("device-id", "192.0.2.1", "example-key-1234")
        with self.assertRaises(transport.ConnectionFailed):
            client.status()
        self.assertEqual(factory.return_value.close.call_count, 3)

    @patch.object(transport.tinytuya, "Device")
    def test_control_requires_actual_readback(self, factory):
        device = factory.return_value
        device.set_multiple_values.return_value = {}
        device.status.return_value = {"dps": {"17": 690}}
        self.assertEqual(self.client().command({"17": 690}), {"17": 690})
        with self.assertRaises(transport.ConnectionFailed):
            self.client().command({"17": 700})
        with self.assertRaises(ValueError):
            self.client().command({"117": "must-not-write-geolocation"})

    def client(self):
        return transport.TuyaClient(
            "device-id", "192.0.2.1", "example-key-1234", "3.5", controls=profile.controls
        )

    @patch.object(transport.tinytuya, "Device")
    def test_read_uses_v35_short_socket_and_closes(self, factory):
        device = factory.return_value
        device.status.return_value = {"dps": {"29": 62}}
        self.assertEqual(self.client().status(), {"29": 62})
        self.assertFalse(factory.call_args.kwargs["persist"])
        self.assertEqual(factory.call_args.kwargs["version"], 3.5)
        device.close.assert_called_once()
        device.set_value.assert_not_called()
        device.set_multiple_values.assert_not_called()

    @patch.object(transport.tinytuya, "Device")
    def test_error_payloads_and_exceptions_do_not_leak(self, factory):
        device = factory.return_value
        for response in (
            None,
            {"Error": "secret"},
            {"Err": "secret"},
            {"dps": {}},
            {"dps": {"bad": 1}},
        ):
            device.status.return_value = response
            with self.assertRaises(transport.ConnectionFailed) as caught:
                self.client().status()
            self.assertNotIn("secret", str(caught.exception))
        device.status.side_effect = ValueError("secret key and decrypted data")
        with self.assertRaises(transport.ConnectionFailed) as caught:
            self.client().status()
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(device.close.call_count, 6)

    @patch.object(transport.tinytuya, "Device")
    def test_parallel_readers_never_share_an_open_device(self, factory):
        active = 0
        highest = 0
        lock = threading.Lock()

        def make_device(*args, **kwargs):
            nonlocal active, highest
            with lock:
                active += 1
                highest = max(highest, active)
            device = MagicMock()

            def status():
                time.sleep(0.01)
                return {"dps": {"29": 62}}

            def close():
                nonlocal active
                with lock:
                    active -= 1

            device.status.side_effect = status
            device.close.side_effect = close
            return device

        factory.side_effect = make_device
        client = self.client()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: client.status(), range(3)))
        self.assertEqual(highest, 1)
        self.assertEqual(active, 0)


if __name__ == "__main__":
    unittest.main()

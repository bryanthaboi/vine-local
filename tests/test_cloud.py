"""Portable account bootstrap checks; never contacts a real server."""

import hashlib
import hmac
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

package = types.ModuleType("vine_test_library")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/vine_local")]
sys.modules[package.__name__] = package
cloud = importlib.import_module("vine_test_library.cloud")
schema = importlib.import_module("vine_test_library.schema")


class CloudTests(unittest.TestCase):
    def test_requests_have_unique_ids_and_keep_tls_validation(self):
        account = cloud.VineAccount()
        try:
            response = MagicMock()
            response.json.return_value = {"success": True, "result": []}
            with patch.object(account.session, "post", return_value=response) as post:
                account.request("test.action", authenticated=False)
                account.request("test.action", authenticated=False)
            first, second = post.call_args_list
            self.assertNotEqual(
                first.kwargs["data"]["requestId"], second.kwargs["data"]["requestId"]
            )
            self.assertTrue(first.args[0].startswith("https://a1.tuyaus.com/"))
            self.assertNotIn("verify", first.kwargs)
        finally:
            account.close()

    def test_other_thermostats_are_selected_by_schema_not_product_id(self):
        account = cloud.VineAccount()
        try:
            with patch.object(
                account,
                "request",
                side_effect=[
                    [{"groupId": 10}],
                    [
                        {
                            "devId": "other-thermostat",
                            "productId": "different-product",
                            "localKey": "example-key-1234",
                        },
                        {
                            "devId": "unknown-thermostat",
                            "productId": "unknown-product",
                            "localKey": "example-key-1234",
                        },
                    ],
                    [
                        {
                            "id": "different-product",
                            "category": "wk",
                            "schemaInfo": {"schema": schema.ST300_DATA["schema"]},
                        },
                        {"id": "unknown-product", "category": "wk", "schemaInfo": {"schema": []}},
                    ],
                ],
            ):
                devices = account.devices()
            self.assertIsNotNone(devices["other-thermostat"]["profile"])
            self.assertIsNone(devices["unknown-thermostat"]["profile"])
            self.assertNotIn("localKey", str(devices["unknown-thermostat"]["schema_export"]))
        finally:
            account.close()

    def test_mobile_hash_uses_sdk_word_order(self):
        self.assertEqual(cloud.mobile_hash("abc"), "3cd24fb09001509828e17f72d6963f7d")

    def test_signing_allowlist_and_empty_fields(self):
        params = {
            "v": "1.0",
            "a": "test.action",
            "time": "123",
            "gid": "not-signed",
            "lat": "",
            "sign": "ignored",
        }
        key = b"test.bundle_test-bitmap_test-secret"
        expected = hmac.new(key, b"a=test.action||time=123||v=1.0", hashlib.sha256).hexdigest()
        self.assertEqual(cloud.sign(params, "test-secret", "test-bitmap", "test.bundle"), expected)

    def test_login_uses_rsa_challenge_instead_of_plain_password(self):
        account = cloud.VineAccount()
        try:
            with patch.object(
                account,
                "request",
                side_effect=[
                    {
                        "publicKey": str(2**2048 - 159),
                        "exponent": "65537",
                        "token": "test-challenge",
                    },
                    {"sid": "test-session"},
                ],
            ) as request:
                account.login("owner@example.invalid", "private-test-password")
                payload = request.call_args_list[1].args[1]
                self.assertNotIn("private-test-password", str(payload))
                self.assertEqual(len(payload["passwd"]), 512)
                self.assertEqual(account.sid, "test-session")
        finally:
            account.close()
        self.assertIsNone(account.sid)

    def test_device_list_uses_product_schemas_and_excludes_account_data(self):
        account = cloud.VineAccount()
        try:
            with patch.object(
                account,
                "request",
                side_effect=[
                    [{"groupId": 10}],
                    [
                        {
                            "devId": "supported",
                            "productId": cloud.PRODUCT_ID,
                            "name": "ST300",
                            "localKey": "example-key-1234",
                            "sid": "must-not-persist",
                        },
                        {
                            "devId": "unsupported",
                            "productId": "other",
                            "localKey": "example-key-1234",
                        },
                    ],
                    [
                        {
                            "id": cloud.PRODUCT_ID,
                            "category": "wk",
                            "schemaInfo": {"schema": schema.ST300_DATA["schema"]},
                        }
                    ],
                ],
            ):
                devices = account.devices()
                self.assertEqual(list(devices), ["supported"])
                self.assertNotIn("must-not-persist", str(devices))
                self.assertIsNotNone(devices["supported"]["profile"])
        finally:
            account.close()

    def test_failed_bootstrap_closes_the_session(self):
        with patch.object(cloud, "VineAccount") as factory:
            factory.return_value.login.side_effect = cloud.CloudError("USER_PASSWD_WRONG")
            with self.assertRaises(cloud.CloudError):
                cloud.fetch_devices("owner@example.invalid", "test-password")
            factory.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()

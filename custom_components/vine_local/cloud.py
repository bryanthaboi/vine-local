"""Optional, one-time Vine account bootstrap; runtime control remains local.

Implements the Tuya OEM app API signing/login sequence. The app registration
constants are shared public-client metadata from Vine's distributed app, not a
user session, device key, or authority to access an account without signing in.
Passwords and cloud sessions are used only in memory and never logged/persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid

import requests

from .app_registration import APP_SECRET, BITMAP_KEY, BUNDLE_ID, CLIENT_ID
from .schema import PRODUCT_ID, ThermostatProfile, UnsupportedProfile

SIGN_FIELDS = frozenset(
    (
        "a",
        "clientId",
        "os",
        "deviceId",
        "v",
        "imsi",
        "imei",
        "lon",
        "lat",
        "lang",
        "ttid",
        "appVersion",
        "isH5",
        "h5Token",
        "n4h5",
        "time",
        "sid",
        "postData",
        "sp",
        "requestId",
        "et",
    )
)
REGIONS = {
    "us": "https://a1.tuyaus.com/api.json",
    "eu": "https://a1.tuyaeu.com/api.json",
    "cn": "https://a1.tuyacn.com/api.json",
    "in": "https://a1.tuyain.com/api.json",
}


class CloudError(Exception):
    """Sanitized bootstrap error with a machine-readable provider code."""

    def __init__(self, code="cannot_connect"):
        self.code = code if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(code)) else "unknown_error"
        super().__init__(f"Vine account request failed ({self.code})")


def mobile_hash(value):
    digest = hashlib.md5(value.encode()).hexdigest()
    return digest[8:16] + digest[:8] + digest[24:32] + digest[16:24]


def sign(params, client_secret=APP_SECRET, bitmap_key=BITMAP_KEY, bundle_id=BUNDLE_ID):
    signed = {
        k: str(v) for k, v in params.items() if k in SIGN_FIELDS and v is not None and v != ""
    }
    if "postData" in signed:
        signed["postData"] = mobile_hash(signed["postData"])
    message = "||".join(f"{k}={v}" for k, v in sorted(signed.items()))
    key = f"{bundle_id}_{bitmap_key}_{client_secret}"
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


class VineAccount:
    def __init__(self, region="us", country_code="1"):
        if region not in REGIONS:
            raise ValueError("Unsupported Tuya data region")
        self.endpoint = REGIONS[region]
        self.country_code = country_code
        self.device_id = uuid.uuid4().hex
        self.sid = None
        self.session = requests.Session()

    def close(self):
        self.sid = None
        self.session.close()

    def request(self, action, payload=None, *, authenticated=True, extra=None):
        params = {
            "a": action,
            "v": "1.0",
            "clientId": CLIENT_ID,
            "time": str(int(time.time())),
            "os": "IOS",
            "deviceId": self.device_id,
            "requestId": uuid.uuid4().hex,
        }
        if authenticated:
            if not self.sid:
                raise CloudError("not_authenticated")
            params["sid"] = self.sid
        if extra:
            params.update(extra)
        if payload is not None:
            params["postData"] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        params["sign"] = sign(params)
        try:
            response = self.session.post(self.endpoint, data=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            raise CloudError("cannot_connect") from None
        if not isinstance(data, dict) or not data.get("success"):
            raise CloudError(
                data.get("errorCode", "invalid_response")
                if isinstance(data, dict)
                else "invalid_response"
            )
        return data.get("result")

    def login(self, email, password):
        token = self.request(
            "tuya.m.user.email.token.create",
            {"countryCode": self.country_code, "email": email},
            authenticated=False,
        )
        try:
            modulus, exponent = int(token["publicKey"]), int(token["exponent"])
            if not 1024 <= modulus.bit_length() <= 4096 or exponent not in (3, 65537):
                raise ValueError
            if not isinstance(token["token"], str) or not token["token"]:
                raise ValueError
            digest = hashlib.md5(password.encode()).hexdigest().encode()
            encrypted = pow(int.from_bytes(digest, "big"), exponent, modulus)
            encoded = encrypted.to_bytes((modulus.bit_length() + 7) // 8, "big").hex()
        except (TypeError, ValueError, KeyError, OverflowError):
            raise CloudError("unsupported_login_challenge") from None
        result = self.request(
            "tuya.m.user.email.password.login",
            {
                "countryCode": self.country_code,
                "email": email,
                "ifencrypt": 1,
                "options": '{"group":1}',
                "passwd": encoded,
                "token": token["token"],
            },
            authenticated=False,
        )
        if not isinstance(result, dict) or not isinstance(result.get("sid"), str):
            raise CloudError("unsupported_login_result")
        self.sid = result["sid"]

    def devices(self):
        groups = self.request("tuya.m.location.list")
        if not isinstance(groups, list):
            raise CloudError("invalid_device_list")
        devices = {}
        for group in groups:
            if not isinstance(group, dict) or "groupId" not in group:
                raise CloudError("invalid_device_list")
            records = self.request(
                "tuya.m.my.group.device.list", extra={"gid": str(group["groupId"])}
            )
            products = self.request(
                "tuya.m.device.ref.info.my.list", extra={"gid": str(group["groupId"]), "v": "2.0"}
            )
            if not isinstance(products, list):
                raise CloudError("invalid_product_list")
            products = {
                p["id"]: p for p in products if isinstance(p, dict) and isinstance(p.get("id"), str)
            }
            if not isinstance(records, list):
                raise CloudError("invalid_device_list")
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("devId"), str):
                    continue
                product_id = record.get("productId")
                product = products.get(product_id, {})
                category = product.get("category", record.get("category"))
                if product_id != PRODUCT_ID and category not in ("wk", "wkq"):
                    continue
                schema = product.get("schemaInfo", {}).get("schema")
                try:
                    if isinstance(schema, str):
                        schema = json.loads(schema)
                    profile = ThermostatProfile(product_id, schema)
                except (ValueError, TypeError, AttributeError, UnsupportedProfile):
                    profile = None
                exported = []
                if isinstance(schema, list):
                    for field in schema:
                        if isinstance(field, dict):
                            exported.append(
                                {
                                    k: field[k]
                                    for k in ("id", "code", "mode", "property")
                                    if k in field
                                }
                            )
                key = record.get("localKey")
                if not isinstance(key, str) or len(key.encode()) != 16:
                    continue
                identifier = record["devId"]
                devices[identifier] = {
                    "device_id": identifier,
                    "name": str(record.get("name", "Vine thermostat"))[:80],
                    "host": "",
                    "local_key": key,
                    "protocol_version": "auto",
                    "product_id": product_id,
                    "profile": profile.to_data() if profile else None,
                    "schema_export": {"product_id": product_id, "schema": exported},
                }
        return devices


def fetch_devices(email, password, region="us", country_code="1"):
    account = VineAccount(region, country_code)
    try:
        account.login(email, password)
        return account.devices()
    finally:
        account.close()

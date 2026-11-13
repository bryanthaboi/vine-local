"""One-time account bootstrap followed by an authenticated LAN read."""

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .cloud import CloudError, fetch_devices
from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY, CONF_PROTOCOL, DOMAIN
from .schema import ST300, UnsupportedProfile, from_data
from .transport import ConnectionFailed, TuyaClient


def discover_devices(identifiers):
    from tinytuya.scanner import devices

    results = devices(
        scantime=6, poll=False, forcescan=False, verbose=False, wantids=identifiers, tuyadevices=[]
    )
    return {record.get("gwId", record.get("id")): record for record in results.values()}


def advanced_schema(version="auto", manual=False):
    fields = {
        vol.Required(CONF_PROTOCOL, default=version): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["auto", "3.5", "3.4", "3.3"],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="protocol",
            )
        )
    }
    if manual:
        fields[vol.Optional("product_schema")] = selector.ObjectSelector()
    return section(vol.Schema(fields), {"collapsed": True})


class VineConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["account", "local"])

    async def async_step_account(self, user_input=None):
        errors = {}
        placeholders = {"code": ""}
        if user_input is not None:
            try:
                self._devices = await self.hass.async_add_executor_job(
                    fetch_devices,
                    user_input["email"],
                    user_input["password"],
                    user_input["region"],
                    user_input["country_code"],
                )
            except CloudError as err:
                errors["base"] = (
                    "invalid_auth"
                    if err.code in ("USER_PASSWD_WRONG", "USER_NOT_EXISTS", "USER_PASSWORD_ERROR")
                    else "cloud_error"
                )
                placeholders["code"] = err.code
            else:
                if self._devices:
                    try:
                        found = await self.hass.async_add_executor_job(
                            discover_devices, list(self._devices)
                        )
                    except OSError:
                        found = {}
                    for identifier, device in self._devices.items():
                        device["host"] = ""
                        if identifier in found:
                            device["host"] = found[identifier].get("ip", "")
                            version = str(found[identifier].get("version", "auto"))
                            device[CONF_PROTOCOL] = (
                                version if version in ("3.3", "3.4", "3.5") else "auto"
                            )
                    return await self.async_step_device()
                errors["base"] = "no_devices"
        return self.async_show_form(
            step_id="account",
            errors=errors,
            description_placeholders=placeholders,
            data_schema=vol.Schema(
                {
                    vol.Required("email"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL, autocomplete="username"
                        )
                    ),
                    vol.Required("password"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD, autocomplete="current-password"
                        )
                    ),
                    vol.Required("country_code", default="1"): str,
                    vol.Required("region", default="us"): vol.In(["us", "eu", "cn", "in"]),
                }
            ),
        )

    async def async_step_device(self, user_input=None):
        if user_input is not None:
            identifier = user_input[CONF_DEVICE_ID]
            if identifier not in self._devices:
                return self.async_abort(reason="invalid_selection")
            self._selected = self._devices[identifier]
            self._devices = {}
            if self._selected.get("profile") is None:
                product = str(self._selected.get("product_id", "unknown"))
                self._selected = {}
                return self.async_abort(
                    reason="unsupported_model", description_placeholders={"product_id": product}
                )
            return await self.async_step_connect()
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID, default=next(iter(self._devices))): vol.In(
                        {identifier: device["name"] for identifier, device in self._devices.items()}
                    ),
                }
            ),
        )

    async def _connect(self, name, connection):
        await self.async_set_unique_id(connection[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()
        profile = from_data(connection["profile"])
        client = TuyaClient(
            connection[CONF_DEVICE_ID],
            connection[CONF_HOST],
            connection[CONF_LOCAL_KEY],
            connection[CONF_PROTOCOL],
        )
        dps = await self.hass.async_add_executor_job(client.status)
        values = profile.decode(dps)
        if (
            values["current_temperature"] is None
            or values["power"] is None
            or values["mode"] is None
        ):
            raise ConnectionFailed("LAN state does not match the product schema")
        profile.limits(dps)
        connection[CONF_PROTOCOL] = client.version
        self._selected = {}
        return self.async_create_entry(title=name, data=connection)

    async def async_step_connect(self, user_input=None):
        errors = {}
        if user_input is not None:
            connection = {
                key: self._selected[key] for key in (CONF_DEVICE_ID, CONF_LOCAL_KEY, "profile")
            }
            connection[CONF_HOST] = user_input[CONF_HOST]
            connection[CONF_PROTOCOL] = user_input.get("advanced", {}).get(
                CONF_PROTOCOL, self._selected[CONF_PROTOCOL]
            )
            try:
                return await self._connect(user_input[CONF_NAME], connection)
            except (ValueError, ConnectionFailed):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="connect",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self._selected[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=self._selected[CONF_HOST]): str,
                    vol.Optional("advanced", default=dict): advanced_schema(
                        self._selected[CONF_PROTOCOL]
                    ),
                }
            ),
        )

    async def async_step_local(self, user_input=None):
        errors = {}
        if user_input is not None:
            advanced = user_input.get("advanced", {})
            try:
                profile = (
                    from_data(advanced["product_schema"]) if "product_schema" in advanced else ST300
                )
                connection = {
                    key: user_input[key] for key in (CONF_DEVICE_ID, CONF_HOST, CONF_LOCAL_KEY)
                }
                connection[CONF_PROTOCOL] = advanced.get(CONF_PROTOCOL, "auto")
                connection["profile"] = profile.to_data()
                return await self._connect(user_input[CONF_NAME], connection)
            except UnsupportedProfile:
                errors["base"] = "unsupported_schema"
            except ValueError:
                errors["base"] = "invalid_settings"
            except ConnectionFailed:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="local",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Vine thermostat"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_LOCAL_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional("advanced", default=dict): advanced_schema(manual=True),
                }
            ),
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            updated = {**entry.data, CONF_HOST: user_input[CONF_HOST]}
            if user_input.get(CONF_LOCAL_KEY):
                updated[CONF_LOCAL_KEY] = user_input[CONF_LOCAL_KEY]
            updated[CONF_PROTOCOL] = user_input.get("advanced", {}).get(
                CONF_PROTOCOL, entry.data[CONF_PROTOCOL]
            )
            try:
                client = TuyaClient(
                    updated[CONF_DEVICE_ID],
                    updated[CONF_HOST],
                    updated[CONF_LOCAL_KEY],
                    updated[CONF_PROTOCOL],
                )
                dps = await self.hass.async_add_executor_job(client.status)
                profile = from_data(updated["profile"])
                if profile.decode(dps)["current_temperature"] is None:
                    raise ConnectionFailed("LAN state does not match the product schema")
                updated[CONF_PROTOCOL] = client.version
            except (ValueError, ConnectionFailed):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=updated)
        return self.async_show_form(
            step_id="reconfigure",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Optional(CONF_LOCAL_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional("advanced", default=dict): advanced_schema(
                        entry.data[CONF_PROTOCOL]
                    ),
                }
            ),
        )

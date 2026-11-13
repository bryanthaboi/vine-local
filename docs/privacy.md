# privacy and diagnostics

Account setup sends requests directly to Tuya's HTTPS API for the Vine app:

| Region | API host |
| --- | --- |
| US | `a1.tuyaus.com` |
| Europe | `a1.tuyaeu.com` |
| China | `a1.tuyacn.com` |
| India | `a1.tuyain.com` |

Only US sign-in has been tested. The sign-in request uses the server's RSA
challenge and a password digest, inside HTTPS. No request is sent to a server
operated by this integration's developer.

The password and cloud session are used in memory during setup, then discarded.
They are not put in the config entry, logs, diagnostics or repository. Home
Assistant stores the local device key in its normal config-entry storage, so
protect Home Assistant backups as you would other integration credentials.

The shared app registration in `app_registration.py` identifies Vine's public
mobile client. It is not an account password, user session or thermostat key.
Signing in still requires the account's credentials. Vine/Tuya API changes can
break account setup without affecting an already configured LAN connection.

## diagnostics

Home Assistant diagnostics contain the product profile, protocol version,
connection status and allowlisted thermostat readings. They exclude the device
ID, IP, local key, account credentials, raw datapoints, schedules and geofencing.
Product-schema exports contain product definitions without device values.

Do not enable TinyTuya debug logging for a public support report. The underlying
library can log local keys and decrypted payloads. A raw status dump may include
location or schedule information.

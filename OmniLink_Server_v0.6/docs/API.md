# HTTP and MQTT API

## User authentication

`POST /api/auth/login` with `{"email":"you@example.com","password":"your password"}` returns a token, a CSRF token, and user details, and sets an HttpOnly session cookie. Sessions last 12 hours. Scripts send `Authorization: Bearer TOKEN`; browser mutations send the cookie and `X-CSRF-Token`. `/api/auth/me` returns user details and CSRF; `/api/auth/logout` invalidates the session. The dashboard keeps session data out of localStorage.

Create a device with `POST /api/devices`, `{"name":"My device"}`. New self-registered account owners have the account-local admin role and can register devices, define channels, invite workspace users, disable devices and rotate secrets. The global bootstrap manager alone can manage server settings and other accounts. Operators control devices and automation. Viewers can read only. Devices start with no channels. Aquarium templates are optional examples using ordinary channel-definition endpoints. All device-management routes are scoped to the authenticated user's workspace.

`PUT /api/devices/ID/channels/NUMBER` defines a channel, e.g. `{"name":"Power","type":1,"writable":true}`. An active channel's type cannot change. Numbers are 0–1023. Types follow the ONP enum: BOOL=1; INT8=2; UINT8=3; INT16=4; UINT16=5; INT32=6; UINT32=7; INT64=8; UINT64=9; FLOAT32=10; FLOAT64=11; STRING=12; BYTES=13; JSON=14; TIMESTAMP=15. Send 64-bit integer values as decimal strings and BYTES values as base64 strings.

Write a desired value (`manual_s` defaults to 0, keeping automation active):

```text
POST /api/devices/ID/channels/0/write
{"value":true,"ttl_s":30,"request_id":"my-unique-request","manual_s":300}
```

The result contains a stable 32-character command key, desired revision, expiry, and status. A repeated request ID for the same device/channel/value returns the existing command; reusing it for a different channel/value returns 409. Request IDs identify a command intent; its original TTL and manual duration are retained. New writes supersede pending commands for the same channel. Acknowledged physical effects cannot be undone by superseding a record.

`POST /api/devices/ID/override` with `{"seconds":0}` resumes server automation; a positive number sets a timed manual override. Channel, command, telemetry, event, rule, and schedule lists are available under `/api/devices/ID/...`.

## HTTP device transport

Send `Authorization: Device DEVICE_SECRET` for all `/device/ID/...` routes. Use HTTPS on deployment; local examples use loopback HTTP. Generate a random nonzero 16-byte boot ID per device boot and encode it as 32 lowercase hex characters.

Device-authenticated `GET /device/ID/channels` returns only this device's channel definitions (number, name, type, writable, minimum, maximum). The `/connect` response includes these under `channels`, alongside server time and heartbeat interval. Discovery does not mark desired values as applied.

1. `POST /device/ID/connect`: `{"boot_id":"32 lowercase hex characters","firmware":"my-firmware"}`.
2. `GET /device/ID/commands`: poll pending commands, validate their expiry/revision, apply idempotently.
3. `POST /device/ID/ack`: confirm accepted, applied, or rejected.
4. `POST /device/ID/report`: report actual state.

Command acknowledgments:

```json
{"command_key":"32 lowercase hex characters","desired_revision":1,"status":"applied","error_code":0}
```

Accepted and applied statuses require error 0; rejected requires a nonzero 16-bit error. A command key/revision must belong to that device. Rejected commands do not retry. Accepted commands continue retrying until applied, rejected, superseded, or expired.

Channel report:

```json
{"boot_id":"32 lowercase hex characters","sequence":1,"channel":0,"type":1,"value":true,"observed_at_ms":0,"applied_command_key":"32 lowercase hex characters","desired_revision":1}
```

Use the actual command key/revision for an applied command report. The channel/type/value must match that command. For unsolicited state use 32 zeros and revision 0. Reports use a monotonically increasing sequence per boot; the server does not let an older sequence replace newer state on the same channel.

Telemetry:

```json
{"boot_id":"32 lowercase hex characters","sequence":1,"observed_at_ms":0,"quality":0,"metrics":[{"name":"temperature","type":10,"value":26.5}]}
```

Send 1–16 uniquely named metrics. Names match `[a-z0-9][a-z0-9_-]{0,31}`. Quality codes are 0 good, 1 uncertain, 2 bad, 3 unavailable. Only good samples drive threshold rules. `observed_at_ms=0` means no trustworthy device clock; the server always stores its own receipt timestamp as well. Report, telemetry, and event sequences use separate deduplication namespaces.

Event:

```json
{"boot_id":"32 lowercase hex characters","sequence":1,"severity":1,"code":"CONNECTED","detail":"Device connected","observed_at_ms":0}
```

Severity is 0–4; code is 1–32 uppercase letters, digits, or underscores; detail is at most 1024 UTF-8 bytes.

## MQTT equivalents

Use the same state, telemetry, event, and ack JSON objects on the matching device topic suffixes. HTTP `report` maps to MQTT `state`. Connect with username, client ID = device ID and password = device secret.

Publish a non-retained `status` packet on connection and every 30 seconds:

```json
{"online":true,"boot_id":"32 lowercase hex characters","firmware":"my-firmware"}
```

Set an optional non-retained last will `{"online":false}`. Online status is determined from recent accepted application traffic; a will is advisory. Subscribe to your exact `cmd` topic with QoS 1. Commands are JSON objects with command key, channel, type, value, revision, expiry, source, and outcome metadata. Retained packets are ignored by server ingestion. Plain flat telemetry needs no SDK but is not deduplicated.

## Scheduling examples

Daily at 08:00 India time:

```text
POST /api/devices/ID/schedules
{"name":"Morning power","kind":"daily","channel":0,"value":true,"timezone":"Asia/Kolkata","at":"08:00","weekdays":[0,1,2,3,4,5,6]}
```

Alternate the selector, filter for 600 seconds and air for 120 seconds:

```text
POST /api/devices/ID/schedules
{"name":"Air and filter","kind":"cycle","channel":1,"value":0,"alternate_value":1,"interval_s":600,"alternate_interval_s":120}
```

Set V2=1 on the ESP32 to delegate selector scheduling to the server. The initial schedule occurrence is after `interval_s`, then the first value's hold duration is also `interval_s`. Master power is a separate V0 command.

Threshold action:

```text
POST /api/devices/ID/rules
{"name":"High temperature air","metric":"temperature","op":"gt","threshold":28,"channel":1,"value":1,"cooldown_s":60}
```

Delete a rule or schedule with `DELETE /api/devices/ID/rules/RULE_ID` or `/schedules/SCHEDULE_ID`.

## Live browser updates

`/ws/live` accepts a valid user cookie and the configured same origin, and streams only that user's workspace events. Payloads have `{"kind":"report|telemetry|command|event|heartbeat","data":{...}}`. Slow consumers get a bounded recent-event queue; use the REST lists to recover full state after reconnection. Sessions are revalidated on each event or heartbeat.

## Dashboard layouts

All routes below use existing user session/Bearer authentication, tenant isolation, cookie CSRF, and administrator/operator write permissions. Viewers can read.

- `GET /api/devices/{device_id}/dashboards` lists saved layouts.
- `POST /api/devices/{device_id}/dashboards` creates `{name, widgets}`.
- `PUT /api/devices/{device_id}/dashboards/{id}` replaces `{name, widgets, revision}`. Pass the revision last read; a stale save returns 409.
- `DELETE /api/devices/{device_id}/dashboards/{id}?revision=N` deletes that saved layout with the same revision guard.

A layout contains at most 48 widgets; a device contains at most 12 layouts. Widget IDs are unique 32-character lowercase hex values. Supported kinds: `switch`, `button`, `slider`, `input`, `value`, `gauge`, `led`, `chart`, `text`, `location`, `motion`, `camera`, `microphone`, `bluetooth`, `serial`. Their exact bounded schema is exposed in `/docs`. Control widgets require an existing writable channel. Switch/button values are checked against its type and limits; slider boundaries and integer steps are checked. Displays can read reported/desired state or telemetry. BLE UUIDs and Serial baud rates are validated. Content is rendered as escaped text. Browser readings are not ingested by this API.

Authenticated `/ws/live` connections receive a `dashboard` event when a layout is saved or deleted. The UI also polls for layouts with its normal refresh cycle.


## v0.6 account, pin, dashboard and flow APIs

See the separately packaged client’s `API.md` for the route table and `/docs` for full schemas. New account registration is `POST /api/auth/register` with email and a password of at least 12 characters. `GET /api/auth/me` adds `account_id` and the server `manager` flag. `GET /api/pins` returns pool bounds, free pins, owners and conflicts. Channel creation allocates a unique pin within this account. Release and dashboard deletion use dependency checks and return HTTP 409 with a `dependencies` array when blocked.

Account dashboards are at `/api/dashboards`; each widget carries its own `device_id`. The old device-scoped layout routes remain for compatibility. Edits/deletes require the current revision; do not retry a 409 by silently dropping it. Pin moves use `POST /api/devices/{id}/channels/{n}/move` with `new_number` and `confirm_firmware_update: true`. Firmware remapping remains the caller’s responsibility.

Flow definitions use `/api/flows`, `{name, graph: {nodes, edges}}`; updates also require `revision`. Publish is `POST /api/flows/{id}/publish?revision=N`; run is `POST /api/flows/{id}/run` with `{test: false}` or `{test: true, samples: {"device_id:pin": value}}`. GET `/api/flows/{id}/runs` returns execution history. See `FLOWS.md` for the graph semantics and quotas. History and alerts are account-scoped. Manager endpoints reject ordinary account owners even though those users have the account-local admin role.

The client persists editable `mxGraphModel` XML separately from each executable flow: `GET /api/flows/{id}/mxgraph` reads it and `PUT` saves `{"mxGraphModel":"..."}`. The server checks that its cells match the validated flow blocks and connections. The executable graph stays in the v0.5-compatible `{nodes, edges}` JSON schema, so a rollback to v0.5 can still run it; v0.5 ignores the additive visual-model table.

Server managers can list account users through `GET /api/manager/accounts` and remove one with `DELETE /api/manager/accounts/{account_id}/users/{user_id}`. Deletion revokes the user's sessions and removes their login. Devices, pins, dashboards and flows remain on the account. The active server manager and the last enabled account administrator cannot be deleted.

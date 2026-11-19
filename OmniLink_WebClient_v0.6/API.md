# Client/server API boundary

OmniLink Server v0.6 owns authentication, workspace/device permissions, channel validation, durable commands, telemetry, automation, and saved layouts. The independently packaged web client owns widget presentation, editor interactions, browser inputs, and its scoped PWA shell. The later native app can implement its own views against these same endpoints.

| API | Client use |
| --- | --- |
| POST `/api/auth/login`, GET `/api/auth/me`, POST `/api/auth/logout` | User session |
| GET `/api/devices` | Authorized workspace devices |
| GET `/api/devices/{id}/channels` | Channel definitions and desired/reported state |
| POST `/api/devices/{id}/channels/{n}/write` | Typed command, request ID, TTL, optional automation pause |
| GET `/api/devices/{id}/commands`, `/telemetry`, `/events` | Outcomes and history |
| POST `/api/auth/register` | Independent self-service account |
| GET `/api/pins` | Account pool, free numbers and migration conflicts |
| POST/PATCH/DELETE `/api/devices[/{id}]` | Account device management |
| PUT/DELETE `/api/devices/{id}/channels/{n}` | Allocate/release pin |
| GET `/api/devices/{id}/channels/{n}/dependencies` | List shared references |
| POST `/api/devices/{id}/channels/{n}/move` | Explicit remapping with firmware confirmation |
| GET/POST `/api/dashboards`; PUT/DELETE `/api/dashboards/{id}` | Multi-device, revision-checked layouts |
| GET `/api/history` | Filter device telemetry by metric/time |
| GET `/api/alerts`; POST `/api/alerts/{id}/ack` | Account alerts |
| GET/POST `/api/flows`; PUT/DELETE `/api/flows/{id}` | Flow definitions |
| POST `/api/flows/{id}/publish`, `/pause`, `/run`; GET `/runs` | Runtime and history |
| `/api/manager/*` | Global manager only: settings, accounts, integrations |
| WebSocket `/ws/live` | Notifications to refresh state |

Use the server's `/docs` or `/openapi.json` for exact request/response schemas. The current API is release-versioned by the package, without a versioned URL or a long-term frozen compatibility promise. Pair this client with server v0.6 and validate future upgrades.

The web client uses an HttpOnly session cookie and sends the CSRF token returned by `/api/auth/me` in `X-CSRF-Token` for mutations. The current server also supports bearer sessions for non-browser integrations; the login response contains a token. User credentials grant role-limited dashboard access. Device `Authorization: Device <secret>` credentials only authenticate device transport endpoints and cannot be used as user sessions.

The separate device simulator/firmware connects under `/device/{id}/*` or ONP/MQTT. Device-authenticated GET `/device/{id}/channels` returns only that device's schema. HTTP `/connect` includes the same schema. A web dashboard does not replace firmware: actual hardware must apply commands, acknowledge them, and report state.

Layout writes use a revision to reject stale edits with 409. One layout can bind multiple devices in the same account; operators and administrators can edit, viewers cannot. Sensor permissions and readings remain in the client browser. Client controls use the user's session, never the device secret.

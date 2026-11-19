# OmniLink v0.6 validation

Validated on 2026-10-03 with Python 3.12 and headless Chromium on Linux.

## Server

The full server suite passed: **59 tests and 183 scalar/corruption subtests passed; 5 MQTT broker tests skipped** because Mosquitto and its Dynamic Security plugin are not installed. One dependency deprecation warning was reported.

The v0.6 tests cover manager-only account user deletion, revoked sessions, last-administrator and manager protections, account asset retention, separate mxGraphModel storage, flow-model validation against runtime blocks and edges, malformed model rejection, and the v0.5-compatible executable graph format.

Python bytecode compilation and JavaScript syntax checks passed. The complete regression suite also exercises HTTP and verified ONP TLS, device reports and acknowledgements, account boundaries, pin allocation and explicit conflict resolution, dashboard dependencies, schedules, automation, and browser inputs.

## Browser

Headless Chromium exercised the temporary v0.6 server, its independent client package, and an HTTP simulator. It passed the full 27-widget guide and per-widget help, all 12 added widget types, mxGraphModel persistence separate from runtime JSON, flow connection/save/publish/run, device and pin creation, multi-device dashboards, live command/acknowledgement, browser geolocation, shared-reference deletion warnings, pin release, alerts, manager view, and desktop/mobile layout checks.

Screenshots in the client package show the synthetic test workspace. They do not contain real user or device data. No physical hardware was controlled.

- Desktop dashboard: `docs/screenshots/dashboard-preview.png`
- Automation flow editor: `docs/screenshots/automation-v0.6.png`
- Mobile dashboard: `docs/screenshots/dashboard-mobile-v0.6.png`

## Deployment limits

Five Mosquitto integration tests were skipped as described above. Windows batch files, Docker Compose, a live PostgreSQL service, SMTP/webhook delivery, and real browser peripherals were not run here. Review the v0.6 upgrade guide before deployment and keep a database backup if you need to recover a deleted account user.

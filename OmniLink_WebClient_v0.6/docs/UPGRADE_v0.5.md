# Upgrade to OmniLink v0.5

The server and web client remain separate packages. Update both together. Your existing server folder may keep its current name, including `D:\Projects\OmniLink_Server_v0.4`.

## Existing Windows installation

1. Stop OmniLink with Ctrl+C. Back up the entire existing server folder, including `.env`, `data/`, and certificates. For PostgreSQL, also take a database backup using the commands in the README.
2. Extract `OmniLink_Server_v0.5.zip`. Copy the contents of its server folder into your existing server folder. Preserve `.env`, `data/`, and your existing encryption key. Do not run setup again.
3. In Command Prompt, run:

```bat
cd /d D:\Projects\OmniLink_Server_v0.4
.venv\Scripts\python -m pip install -r requirements.txt
```

4. Extract the client ZIP into `D:\Projects\OmniLink_WebClient_v0.5`, then run:

```bat
cd /d D:\Projects\OmniLink_WebClient_v0.5
py -3 install.py --server-dir "D:\Projects\OmniLink_Server_v0.4"
cd /d D:\Projects\OmniLink_Server_v0.4
run.bat
```

5. Open the exact `OMNILINK_PUBLIC_URL` from your existing `.env`. The manager is at `/`; users open `/client/`. Reload browser tabs after upgrading. Remote users connect through the URL and do not need the server folder. The folder is required only by the one-time installer to configure which client assets the server serves.

## What happens on first startup

New account, pin-allocation, flow and alert tables are created additively. Existing device IDs, secrets, channel numbers, readings and dashboard IDs are preserved. Legacy widgets gain an explicit device binding. The account initially containing the configured bootstrap email retains the server manager identity; keep `OMNILINK_BOOTSTRAP_EMAIL` set to that original account on the first upgrade startup. The manager ID is persisted thereafter.

Existing users who shared a v0.4 workspace continue sharing that account and its pool; the upgrade does not guess a device owner or split shared data. New self-registered users receive independent accounts. Each account defaults to 255 pins, V0–V254. The manager can adjust the pool limit or an account override. Existing out-of-range pins are flagged and remain mapped until explicitly moved or released.

## Resolve reused pin numbers

Open **Client → Devices & pins**. A conflict appears when two existing devices in your account use the same number. Neither firmware mapping is changed automatically. Commands on conflicted pins are blocked and pending commands on those pins are superseded. Reporting can continue for diagnosis.

For each affected device pin:

1. Choose **Move** and a free destination.
2. Confirm that you will update the firmware mapping.
3. Update the firmware or device configuration to use that destination. Restart the simulator after a schema change.
4. Review and republish affected flows; review/recreate affected legacy rules or schedules. The move disables them. Dashboard bindings are updated to the explicitly selected destination.

Moving clears the moved channel's desired/reported state and discards its old commands. It preserves the channel's name, type, writable setting and bounds. It never changes another device's pin. Running real flow executions referencing that pin must be paused first.

## Deleting widgets and releasing pins

Deleting a widget is a draft change until **Save layout**. On save, its explicitly bound pins are released in the same database transaction. If another widget, saved draft/published flow, running real execution, legacy rule, or schedule references a pin, the save fails with a dependency list and leaves the layout/pins unchanged. Remove or rebind those dependencies first. Pausing a flow alone keeps its saved references; delete or rebind the flow and republish as appropriate.

Removing all widgets sharing a pin in one layout save releases it once, provided there are no external dependencies. Empty dashboards stay empty. Device status, telemetry charts, dynamic device tables, browser inputs, text, navigation and schedule-launcher widgets do not allocate explicit pins. Deleting these widgets does not release unrelated device channels. Process/floor-plan points and joystick axes do reference pins.

The server discards old queued and historical commands for a released channel, gives a future allocation a new identity, and rejects stale flow snapshots/command acknowledgements. Commands already applied by physical firmware cannot be undone by deleting a server widget. Update firmware mappings explicitly when repurposing pins.

## Docker upgrade

Back up PostgreSQL and `.env`/certificates; stop the application service. Replace source files, place client `index.html`, `sw.js`, and `assets/` under `web-client/`, set `OMNILINK_CLIENT_DIR=/web-client` in `.env`, then run `docker compose up -d --build`. Use a single OmniLink application instance. The database volume is preserved. Do not run setup against an existing installation.

## Rollback

Stop v0.5 and restore the complete pre-upgrade database backup, original server/client files and corresponding `.env`/certificates. Do not run two releases against the same database. Rollback discards changes made since the backup.

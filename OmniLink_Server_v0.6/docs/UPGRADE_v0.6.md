# Upgrade OmniLink from v0.5 to v0.6

Update the server and web client together. You can keep the existing folder names and URL.

## Windows

1. Stop OmniLink with Ctrl+C. Back up the complete server folder, including `.env`, `data/`, certificates, and a database dump if you use PostgreSQL.
2. Extract `OmniLink_Server_v0.6.zip`. Copy the package contents over the existing server source. Preserve `.env`, `data/`, and certificates. Do not run setup again.
3. In the existing server folder, install the updated requirements and client package:

```bat
.venv\Scripts\python -m pip install -r requirements.txt
cd /d D:\Projects\OmniLink_WebClient_v0.6
py -3 install.py --server-dir "D:\Projects\OmniLink_Server_v0.4"
cd /d D:\Projects\OmniLink_Server_v0.4
run.bat
```

Replace the example paths with your folders. Keep the existing server URL and open `/client/` after restarting.

## What changes

Startup creates one additional table for flow diagram documents. Existing accounts, users, devices, pin numbers, dashboards, flows, `.env`, and encryption keys remain unchanged. Existing flows get an mxGraphModel document the next time they are edited and saved. Executable graph data stays in the existing `{nodes, edges}` format, so the server and client can be rolled back to v0.5 without rewriting flow definitions. The v0.5 server ignores the extra visual-model table.

The server manager can delete account users. This revokes their sessions. The account's devices, pins, dashboards, and flows remain. The active manager and last enabled account administrator are protected. Restore the pre-upgrade database backup if you need to recover a deleted user.

## Docker

Back up the database and `.env`/certificates, then stop the application. Replace the server source, place the v0.6 client's `index.html`, `sw.js`, and `assets/` under `web-client/`, and keep `OMNILINK_CLIENT_DIR=/web-client`. Rebuild and start the application service. The new table is created additively at startup.

## Rollback

Stop OmniLink, restore the v0.5 server and client files, and restart. v0.6 leaves executable flows in the v0.5 graph schema. A full database restore is needed only to undo user deletions or other data changes made after the backup. Never run two application versions concurrently against the same database.

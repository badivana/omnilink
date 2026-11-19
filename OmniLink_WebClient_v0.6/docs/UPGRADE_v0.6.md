# Install OmniLink Web Client v0.6

Pair this client with OmniLink Server v0.6. Existing users should follow the server package's `docs/UPGRADE_v0.6.md`, which explains the server update, backup, Docker and rollback steps.

For Windows, extract this package next to the existing server folder and run:

```bat
py -3 install.py --server-dir "D:\Projects\OmniLink_Server_v0.4"
```

Restart the existing server and open its same URL followed by `/client/`. The installer only updates `OMNILINK_CLIENT_DIR` in the existing server `.env`; it does not reset credentials, keys, certificates or data. Remote users connect through the server URL and do not need the server source folder.

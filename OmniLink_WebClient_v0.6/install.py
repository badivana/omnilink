"""Attach this static client to an initialized OmniLink server (standard library only)."""
import argparse
import os
from pathlib import Path
import tempfile

CLIENT=Path(__file__).resolve().parent

def install(server_dir):
    server=Path(server_dir).expanduser().resolve()
    config=server/'.env'
    source=server/'omnilink/settings.py'
    if not config.is_file():raise ValueError('Server .env not found. Initialize the server first, or choose its existing installation folder.')
    if not source.is_file() or not (server/'omnilink/platform_api.py').is_file():raise ValueError('Upgrade the server to v0.6 before attaching this client.')
    if any(ch in str(CLIENT) for ch in '\r\n'):raise ValueError('Client folder cannot contain newline characters.')
    # Change only the external static-client setting, preserving all other lines/secrets.
    lines=config.read_text(encoding='utf8').splitlines();key='OMNILINK_CLIENT_DIR='
    lines=[line for line in lines if not line.strip().startswith(key)]
    lines.append(key+str(CLIENT))
    fd,name=tempfile.mkstemp(prefix='.omnilink-config-',dir=server)
    try:
        with os.fdopen(fd,'w',encoding='utf8',newline='\n') as stream:stream.write('\n'.join(lines)+'\n')
        os.chmod(name,config.stat().st_mode & 0o777)
        os.replace(name,config)
    finally:
        if Path(name).exists():Path(name).unlink()
    print('Client configured. Restart OmniLink with run.bat or run.sh, then open your server URL followed by /client/.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--server-dir');a=p.parse_args()
    folder=a.server_dir or input('Existing OmniLink server folder: ').strip().strip('"')
    try:install(folder)
    except (ValueError,OSError) as exc:raise SystemExit(str(exc))

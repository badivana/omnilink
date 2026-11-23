import atexit
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
import uvicorn
from .settings import Settings
from .api import create_app

GATEWAY=Path(__file__).resolve().parents[1]/'examples'/'arduino_uno_serial_gateway.py'

def gateway_command(settings):
    """Command for the Uno/Nano USB gateway, talking to this server on the local machine."""
    host=settings.http_host if settings.http_host not in ('','0.0.0.0','::') else '127.0.0.1'
    scheme='https' if settings.http_tls else 'http'
    cmd=[sys.executable,str(GATEWAY),'--serial',settings.serial_gateway.strip(),'--url',f'{scheme}://{host}:{settings.http_port}']
    if settings.http_tls: cmd+=['--ca',str(Path(settings.tls_cert).parent/'ca.crt')]
    return cmd

def start_serial_gateway(settings):
    # shortcut: one board per server; run more gateways by hand if you need several ports.
    log=logging.getLogger('omnilink')
    if not GATEWAY.is_file():
        log.error('OMNILINK_SERIAL_GATEWAY is set but %s is missing',GATEWAY);return
    cmd=gateway_command(settings);current=[]
    atexit.register(lambda:[p.terminate() for p in current if p.poll() is None])
    def supervise():
        while True:
            current[:]=[subprocess.Popen(cmd)]
            code=current[0].wait()
            log.warning('Serial gateway on %s stopped (exit %s); restarting in 5 s',settings.serial_gateway,code)
            time.sleep(5)
    threading.Thread(target=supervise,daemon=True,name='serial-gateway').start()
    log.info('Serial gateway started on %s',settings.serial_gateway)

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    settings=Settings.from_env()
    if settings.serial_gateway.strip(): start_serial_gateway(settings)
    uvicorn.run(create_app(settings),host=settings.http_host,port=settings.http_port,
                ssl_certfile=settings.tls_cert if settings.http_tls else None,
                ssl_keyfile=settings.tls_key if settings.http_tls else None,
                workers=1,proxy_headers=True,forwarded_allow_ips=os.getenv('OMNILINK_PROXY_IPS','127.0.0.1'),
                ws_max_size=65536,limit_concurrency=512,timeout_keep_alive=5,access_log=False)

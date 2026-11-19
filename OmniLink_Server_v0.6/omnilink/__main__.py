import logging
import os
import uvicorn
from .settings import Settings
from .api import create_app

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    settings=Settings.from_env()
    uvicorn.run(create_app(settings),host=settings.http_host,port=settings.http_port,
                ssl_certfile=settings.tls_cert if settings.http_tls else None,
                ssl_keyfile=settings.tls_key if settings.http_tls else None,
                workers=1,proxy_headers=True,forwarded_allow_ips=os.getenv('OMNILINK_PROXY_IPS','127.0.0.1'),
                ws_max_size=65536,limit_concurrency=512,timeout_keep_alive=5,access_log=False)

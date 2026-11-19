"""Copy mounted TLS material and drop root before starting the application."""
import os
import runpy
import shutil
from pathlib import Path

folder=Path('/run/omnilink')
folder.mkdir(parents=True,exist_ok=True)
for name in ('server.crt','server.key'):
    dest=folder/name;shutil.copyfile('/certs-ro/'+name,dest)
    dest.chmod(0o600);os.chown(dest,10001,10001)
os.chown(folder,10001,10001)
os.environ['OMNILINK_TLS_CERT']=str(folder/'server.crt')
os.environ['OMNILINK_TLS_KEY']=str(folder/'server.key')
os.setgroups([]);os.setgid(10001);os.setuid(10001)
runpy.run_module('omnilink',run_name='__main__')

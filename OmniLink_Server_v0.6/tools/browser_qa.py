"""Exercise a temporary OmniLink + simulator in Playwright; never use the real DB."""
import argparse
import asyncio
import os
from pathlib import Path
import socket
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from cryptography.fernet import Fernet
from sqlalchemy import select
from omnilink.api import create_app
from omnilink.settings import Settings
from omnilink.db import User, Channel
from examples.simulator import Simulator

async def run(output):
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='omnilink-qa-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        settings=Settings(database_url='sqlite:///'+str(Path(folder)/'test.db'),
            encryption_key=Fernet.generate_key().decode(),native_enabled=False,
            bootstrap_email='demo@example.com',bootstrap_password='Demo-Password-12345',
            public_url=f'http://127.0.0.1:{port}',client_dir=os.getenv('OMNILINK_WEB_CLIENT_DIR',str(root.parent/'OmniLink_WebClient_v0.6')))
        app=create_app(settings)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False))
        task=asyncio.create_task(server.serve());sim=None
        try:
            for _ in range(100):
                if server.started: break
                if task.done(): task.result()
                await asyncio.sleep(.05)
            if not server.started: raise RuntimeError('QA server did not start')
            rt=app.state.runtime
            with rt.db.session() as session: tenant=session.scalar(select(User)).tenant_id
            device=rt.core.new_device(tenant,'Demo controller')
            with rt.db.session.begin() as session:
                for n,name,t,w,low,high in [(0,'Power',1,True,None,None),(1,'Output selection',3,True,0,1),(3,'Setpoint',7,True,1,300),(4,'Limit',7,True,1,300),(6,'Measurement',10,False,0,100)]:
                    session.add(Channel(device_id=device['id'],number=n,name=name,type=t,writable=w,minimum=low,maximum=high))
            from omnilink import platform
            platform.initialize(rt)
            class QADevice(Simulator):
                # Explicit synthetic fixture for testing telemetry charts.
                def telemetry(self):
                    from omnilink.db import now_ms
                    self.tseq+=1;self.channel_values[6]=24.5
                    return {'boot_id':self.boot,'sequence':self.tseq,'observed_at_ms':now_ms(),'metrics':[{'name':'measurement','type':10,'value':24.5}]}
                def extra_reports(self): return [6]
            sim=asyncio.create_task(QADevice(device).http(settings.public_url))
            env={**os.environ,'OMNILINK_TEST_URL':settings.public_url,'OMNILINK_QA_DIR':str(output)}
            proc=await asyncio.create_subprocess_exec('node',str(root/'tests/browser_dashboard.cjs'),env=env)
            try: return await asyncio.wait_for(proc.wait(),180)
            except asyncio.TimeoutError:
                proc.kill();await proc.wait();raise
        finally:
            if sim:
                sim.cancel();await asyncio.gather(sim,return_exceptions=True)
            server.should_exit=True
            try: await asyncio.wait_for(task,30)
            except asyncio.TimeoutError:
                task.cancel();await asyncio.gather(task,return_exceptions=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'omnilink-browser-qa')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    sys.exit(asyncio.run(run(output)))

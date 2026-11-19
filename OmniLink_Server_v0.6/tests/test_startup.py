import asyncio
import os
import subprocess
import sys
from pathlib import Path
import httpx
from examples.aquarium_simulator import AquariumSimulator as Simulator
from conftest import free_port,eventually

async def test_setup_and_full_process_restart_preserve_command(tmp_path):
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'PYTHONPATH':str(root),'OMNILINK_SETUP_PASSWORD':'Restart-Test-Password-9876',
         'OMNILINK_HTTP_PORT':str(free_port()),'OMNILINK_NATIVE_PORT':str(free_port())}
    initialized=await asyncio.to_thread(subprocess.run,[sys.executable,'-m','omnilink.setup','--email','restart@example.com'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=20)
    assert initialized.returncode==0,initialized.stderr
    original=(tmp_path/'.env').read_bytes()
    repeated=await asyncio.to_thread(subprocess.run,[sys.executable,'-m','omnilink.setup','--email','other@example.com'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=20)
    assert repeated.returncode!=0 and (tmp_path/'.env').read_bytes()==original
    url='http://127.0.0.1:'+env['OMNILINK_HTTP_PORT']
    output=open(tmp_path/'server.log','w')
    process=None;sim_task=None
    async def launch():
        nonlocal process
        process=subprocess.Popen([sys.executable,'-m','omnilink'],cwd=tmp_path,env=env,stdout=output,stderr=output)
        async def healthy():
            if process.poll() is not None: raise AssertionError((tmp_path/'server.log').read_text())
            try:
                async with httpx.AsyncClient(base_url=url,trust_env=False) as client:
                    return (await client.get('/health/ready')).status_code==200
            except httpx.HTTPError: return False
        await eventually(healthy,10)
    async def stop():
        if process and process.poll() is None:
            process.terminate()
            await asyncio.to_thread(process.wait,10)
    try:
        await launch()
        async with httpx.AsyncClient(base_url=url,trust_env=False) as client:
            async def signin():
                r=await client.post('/api/auth/login',json={'email':'restart@example.com','password':env['OMNILINK_SETUP_PASSWORD']})
                assert r.status_code==200;client.headers['Authorization']='Bearer '+r.json()['token']
            await signin()
            d=(await client.post('/api/devices',json={'name':'Restart device'})).json()
            from examples.aquarium_channels import AQUARIUM_CHANNELS
            for definition in AQUARIUM_CHANNELS:
                body={k:v for k,v in definition.items() if k!='number'}
                r=await client.put(f"/api/devices/{d['id']}/channels/{definition['number']}",json=body)
                assert r.status_code==200,r.text
            c=(await client.post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True,'manual_s':0})).json()
            await stop();await launch();await signin()
            rows=(await client.get(f"/api/devices/{d['id']}/commands")).json()
            assert rows[0]['command_key']==c['command_key'] and rows[0]['status']=='queued'
            sim_task=asyncio.create_task(Simulator(d).http(url))
            async def applied():
                rows=(await client.get(f"/api/devices/{d['id']}/commands")).json();return rows[0]['status']=='applied'
            await eventually(applied,10)
    finally:
        if sim_task: sim_task.cancel();await asyncio.gather(sim_task,return_exceptions=True)
        await stop();output.close()

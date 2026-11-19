import asyncio
import socket
import httpx
import pytest_asyncio
import uvicorn
from cryptography.fernet import Fernet
from omnilink.api import create_app
from omnilink.settings import Settings
from omnilink.certificates import generate

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]

@pytest_asyncio.fixture
async def system(tmp_path):
    certs=tmp_path/'certs';generate(certs,['localhost','127.0.0.1'])
    settings=Settings(database_url='sqlite:///'+str(tmp_path/'server.db'),encryption_key=Fernet.generate_key().decode(),
                      native_port=0,tls_cert=str(certs/'server.crt'),tls_key=str(certs/'server.key'),
                      bootstrap_email='admin@example.com',bootstrap_password='Correct-Horse-Battery-47',retry_seconds=.25)
    app=create_app(settings);rt=app.state.runtime
    port=free_port();settings.public_url=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False))
    task=asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started: break
            if task.done(): task.result()
            await asyncio.sleep(.03)
        assert server.started
        async with httpx.AsyncClient(base_url=settings.public_url,timeout=5,trust_env=False) as client:
            response=await client.post('/api/auth/login',json={'email':settings.bootstrap_email,'password':settings.bootstrap_password})
            assert response.status_code==200
            token=response.json()['token'];client.headers['Authorization']='Bearer '+token
            yield {'app':app,'rt':rt,'client':client,'url':settings.public_url,'certs':certs,
                   'native_port':rt.native_server.sockets[0].getsockname()[1],'tmp':tmp_path}
    finally:
        server.should_exit=True
        try: await asyncio.wait_for(task,10)
        except asyncio.TimeoutError: task.cancel();await asyncio.gather(task,return_exceptions=True)

async def device(system):
    response=await system['client'].post('/api/devices',json={'name':'Optional example'})
    assert response.status_code==200,response.text
    d=response.json()
    from examples.aquarium_channels import AQUARIUM_CHANNELS
    for definition in AQUARIUM_CHANNELS:
        body={k:v for k,v in definition.items() if k!='number'}
        r=await system['client'].put(f"/api/devices/{d['id']}/channels/{definition['number']}",json=body)
        assert r.status_code==200,r.text
    return d

async def eventually(check,timeout=6):
    deadline=asyncio.get_running_loop().time()+timeout
    while asyncio.get_running_loop().time()<deadline:
        result=await check()
        if result: return result
        await asyncio.sleep(.05)
    raise AssertionError('Condition not reached within timeout')

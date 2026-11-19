import asyncio
import json
import secrets
import httpx
import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from examples.simulator import Simulator, checked
from omnilink.api import create_app
from omnilink.settings import Settings
from conftest import eventually

async def create(system):
    r=await system['client'].post('/api/devices',json={'name':'General device'})
    assert r.status_code==200
    return r.json()

async def definitions(system,d):
    channels=[]
    for kind in range(1,16):
        number=100+kind
        body={'name':f'Type {kind}','type':kind,'writable':True}
        if kind in (2,3,4,5,6,7,10,11):body.update(minimum=5,maximum=20)
        r=await system['client'].put(f"/api/devices/{d['id']}/channels/{number}",json=body)
        assert r.status_code==200,r.text
        channels.append({'number':number,**body})
    return channels

async def test_empty_generic_device_connects_without_aquarium_reports(system):
    d=await create(system);sim=Simulator(d)
    task=asyncio.create_task(sim.http(system['url']))
    try:
        async def online():return (await system['client'].get('/api/devices')).json()[0]['online']
        await eventually(online);await asyncio.sleep(.2)
        assert not task.done()
        assert sim.types=={} and sim.telemetry() is None
        assert (await system['client'].get(f"/api/devices/{d['id']}/channels")).json()==[]
        assert (await system['client'].get(f"/api/devices/{d['id']}/telemetry")).json()==[]
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_generic_http_discovers_all_types_and_applies_only_commanded_channel(system):
    d=await create(system);await definitions(system,d);sim=Simulator(d)
    task=asyncio.create_task(sim.http(system['url']))
    try:
        async def reported():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
            return len(rows)==15 and all(c['reported_ms'] for c in rows)
        await eventually(reported)
        values={1:True,2:12,3:12,4:12,5:12,6:12,7:12,8:'-9223372036854775808',9:'18446744073709551615',10:12.5,11:12.5,12:'Hello',13:'AAEC',14:{'ok':True},15:'1700000000000'}
        for kind,value in values.items():
            r=await system['client'].post(f"/api/devices/{d['id']}/channels/{100+kind}/write",json={'value':value})
            assert r.status_code==200,r.text
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json()
            return len(rows)==15 and all(c['status']=='applied' for c in rows)
        await eventually(applied)
        rows=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
        assert {c['number']:c['reported'] for c in rows}=={100+k:v for k,v in values.items()}
        assert not {0,1,5,6}&sim.types.keys()
        assert (await system['client'].get('/api/devices')).json()[0]['manual_until_ms']=='0'
        assert not task.done()
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_generic_onp_uses_explicit_discovered_schema(system):
    d=await create(system);await definitions(system,d)
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False,headers={'Authorization':'Device '+d['secret']}) as c:
        schema=checked(await c.get(f"/device/{d['id']}/channels"))
    sim=Simulator(d,channels=schema)
    task=asyncio.create_task(sim.native('localhost',system['native_port'],str(system['certs']/'ca.crt')))
    try:
        async def connected():return d['id'] in system['rt'].native_sessions
        await eventually(connected)
        r=await system['client'].post(f"/api/devices/{d['id']}/channels/112/write",json={'value':'custom ONP value'})
        assert r.status_code==200,r.text
        async def applied():return (await system['client'].get(f"/api/devices/{d['id']}/commands")).json()[0]['status']=='applied'
        await eventually(applied)
        assert sim.channel_values[112]=='custom ONP value' and not task.done()
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_device_schema_requires_own_secret(system):
    a=await create(system);b=await create(system)
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as c:
        root=f"/device/{a['id']}/channels"
        assert (await c.get(root)).status_code==401
        assert (await c.get(root,headers={'Authorization':'Device '+b['secret']})).status_code==401
        assert (await c.get(root,headers={'Authorization':'Device '+a['secret']})).json()==[]
        assert (await c.get('/api/users',headers={'Authorization':'Device '+a['secret']})).status_code==401

async def test_rejection_shows_actual_report_error_without_secret(system):
    d=await create(system)
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False,headers={'Authorization':'Device '+d['secret']}) as c:
        sim=Simulator(d,channels=[{'number':7,'type':1,'writable':True}])
        checked(await c.post(f"/device/{d['id']}/connect",json={'boot_id':sim.boot,'firmware':'test'}))
        response=await c.post(f"/device/{d['id']}/report",json=sim.report(7))
        with pytest.raises(RuntimeError,match='V7: HTTP 400: Unknown channel or type mismatch') as error:checked(response,7)
        assert d['secret'] not in str(error.value)

def test_ledger_is_scoped_to_device_and_schema(tmp_path):
    schema=[{'number':42,'type':1,'writable':True}];credentials={'id':'device-a','secret':'00'*32};ledger=tmp_path/'ledger.json'
    sim=Simulator(credentials,ledger,schema)
    command={'channel':42,'type':1,'value':True,'command_key':secrets.token_hex(16),'desired_revision':1,'expires_at_ms':'9999999999999'}
    assert sim.apply(command)==('applied',0)
    restored=Simulator(credentials,ledger,schema);assert restored.channel_values[42] is True and restored.apply(command)==('applied',0)
    other=Simulator({**credentials,'id':'device-b'},ledger,schema)
    assert other.channel_values[42] is False and other.keys=={}
    changed=Simulator(credentials,ledger,[{'number':42,'type':3,'writable':True}]);assert changed.channel_values[42]==0 and changed.keys=={}

def test_external_client_mount_and_server_only_mode(tmp_path):
    client=tmp_path/'client';client.mkdir();(client/'index.html').write_text('<h1>Separate client</h1>');(client/'sw.js').write_text('// scoped worker')
    settings=Settings(native_enabled=False,client_dir=str(client),database_url='sqlite:///'+str(tmp_path/'mount.db'),encryption_key=Fernet.generate_key().decode())
    app=create_app(settings)
    with TestClient(app) as c:
        assert c.get('/client/').text=='<h1>Separate client</h1>'
        assert c.get('/client/sw.js').status_code==200
        assert "media-src 'self' blob:" in c.get('/client/').headers['Content-Security-Policy']
        admin=c.get('/').text
        assert 'Server manager' in admin and 'id="widget-grid"' not in admin
        assert 'aquarium' not in admin.lower()
        assert c.get('/client/../.env').status_code==404
    settings.client_dir=''
    with TestClient(create_app(settings)) as c:assert c.get('/client/').status_code==404

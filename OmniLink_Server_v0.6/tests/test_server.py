import asyncio
import secrets
from sqlalchemy import select
from omnilink.db import *
from omnilink.core import Core,DomainError
from omnilink.auth import new_user
from examples.aquarium_simulator import AquariumSimulator as Simulator
from conftest import device,eventually
import pytest
import httpx

async def command(system,d,number=0,value=True,manual=0,request_id=None):
    r=await system['client'].post(f"/api/devices/{d['id']}/channels/{number}/write",json={'value':value,'manual_s':manual,'request_id':request_id})
    assert r.status_code==200,r.text
    return r.json()

async def test_http_device_applies_and_reports_real_network(system):
    d=await device(system);sim=Simulator(d)
    task=asyncio.create_task(sim.http(system['url']))
    try:
        await asyncio.sleep(.15);c=await command(system,d)
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json()
            return rows and rows[0]['status']=='applied'
        await eventually(applied)
        ch=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
        assert ch[0]['desired'] is True and ch[0]['reported'] is True
        async def extra_received():
            channels=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
            telemetry=(await system['client'].get(f"/api/devices/{d['id']}/telemetry")).json()
            return channels[5]['reported']==1 and telemetry
        await eventually(extra_received)
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_onp_tls_device_applies_and_reports(system):
    d=await device(system);sim=Simulator(d)
    task=asyncio.create_task(sim.native('localhost',system['native_port'],str(system['certs']/'ca.crt')))
    try:
        async def connected(): return d['id'] in system['rt'].native_sessions
        await eventually(connected)
        await command(system,d,1,1);await command(system,d)
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json()
            return len(rows)==2 and all(c['status']=='applied' for c in rows)
        await eventually(applied)
        channels=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
        assert channels[5]['reported']==2
        assert not task.done()
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_idempotency_and_supersession(system):
    d=await device(system)
    a=await command(system,d,request_id='request-1');b=await command(system,d,request_id='request-1')
    assert a['command_key']==b['command_key'] and a['desired_revision']==1
    r=await system['client'].post(f"/api/devices/{d['id']}/channels/0/write",json={'value':False,'request_id':'request-1'})
    assert r.status_code==409
    c=await command(system,d,value=False)
    assert c['desired_revision']==2
    rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json()
    assert next(x for x in rows if x['command_key']==a['command_key'])['status']=='superseded'

async def test_report_dedup_and_late_sequence(system):
    d=await device(system);rt=system['rt'];boot=secrets.token_hex(16)
    rt.core.mark_seen(d['id'],boot,'http')
    a=rt.core.report(d['id'],boot,2,1,3,1)
    assert not a['duplicate']
    assert rt.core.report(d['id'],boot,2,1,3,1)['duplicate']
    rt.core.report(d['id'],boot,1,1,3,0)
    with rt.db.session() as s: assert s.get(Channel,(d['id'],1)).reported==1
    with pytest.raises(DomainError): rt.core.report(d['id'],secrets.token_hex(16),3,1,3,0)

async def test_commands_survive_database_restart(system):
    d=await device(system);c=await command(system,d)
    rt=system['rt'];db2=Database(rt.settings.database_url);core2=Core(db2,rt.settings)
    try:
        pending=core2.pending(d['id'],True)
        assert pending[0]['command_key']==c['command_key']
        core2.acknowledge(d['id'],c['command_key'],1,'accepted')
        await asyncio.sleep(.3)
        retry=rt.core.pending(d['id'])
        assert retry[0]['command_key']==c['command_key'] and retry[0]['status']=='accepted'
    finally: db2.engine.dispose()

async def test_command_expiry(system):
    d=await device(system);c=await command(system,d)
    with system['rt'].db.session.begin() as s: s.get(Command,c['command_key']).expires_ms=now_ms()-1
    assert not system['rt'].core.pending(d['id'])
    with system['rt'].db.session() as s: assert s.get(Command,c['command_key']).status=='expired'

async def test_acks_cannot_cross_devices_or_forge_reports(system):
    a=await device(system);b=(await system['client'].post('/api/devices',json={'name':'Second device'})).json();c=await command(system,a)
    with pytest.raises(DomainError): system['rt'].core.acknowledge(b['id'],c['command_key'],1,'applied')
    boot=secrets.token_hex(16);system['rt'].core.mark_seen(a['id'],boot,'http')
    with pytest.raises(DomainError): system['rt'].core.report(a['id'],boot,1,0,1,False,key=c['command_key'],revision=1)
    with system['rt'].db.session() as s: assert s.get(Command,c['command_key']).status=='queued'

async def test_tenant_isolation_and_viewer_permissions(system):
    d=await device(system);rt=system['rt']
    with rt.db.session.begin() as s:
        t=Tenant(id=secrets.token_hex(16),name='Other');s.add(t);new_user(s,t.id,'other@example.com','Other-password-12345')
        owner=s.scalar(select(User).where(User.email==rt.settings.bootstrap_email))
        new_user(s,owner.tenant_id,'viewer@example.com','Viewer-password-12345','viewer')
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as c:
        response=await c.post('/api/auth/login',json={'email':'other@example.com','password':'Other-password-12345'})
        c.headers['Authorization']='Bearer '+response.json()['token']
        assert (await c.get('/api/devices')).json()==[]
        assert (await c.get(f"/api/devices/{d['id']}/channels")).status_code==404
        response=await c.post('/api/auth/login',json={'email':'viewer@example.com','password':'Viewer-password-12345'})
        c.headers['Authorization']='Bearer '+response.json()['token']
        assert (await c.get(f"/api/devices/{d['id']}/channels")).status_code==200
        assert (await c.post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True})).status_code==403

async def test_csrf_login_origin_and_device_credentials(system):
    d=await device(system)
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as c:
        r=await c.post('/api/auth/login',json={'email':'admin@example.com','password':'Correct-Horse-Battery-47'},headers={'Origin':'https://evil.example'})
        assert r.status_code==403
        r=await c.post('/api/auth/login',json={'email':'admin@example.com','password':'Correct-Horse-Battery-47'})
        csrf=r.json()['csrf']
        assert (await c.post('/api/devices',json={'name':'No CSRF'})).status_code==403
        assert (await c.post('/api/devices',json={'name':'With CSRF'},headers={'X-CSRF-Token':csrf})).status_code==200
        assert (await c.get(f"/device/{d['id']}/commands",headers={'Authorization':'Device '+'0'*64})).status_code==401

async def test_rule_edge_dedup_and_manual_override(system):
    d=await device(system);rt=system['rt'];boot=secrets.token_hex(16);rt.core.mark_seen(d['id'],boot,'http')
    r=await system['client'].post(f"/api/devices/{d['id']}/rules",json={'name':'Hot','metric':'temperature','op':'gt','threshold':26,'channel':0,'value':True,'cooldown_s':0})
    assert r.status_code==200,r.text
    def temperature(seq,value): return rt.core.telemetry(d['id'],boot,seq,[{'name':'temperature','type':10,'value':value}])
    temperature(1,27);temperature(1,27);temperature(2,28)
    with rt.db.session() as s:
        rows=list(s.scalars(select(Command).where(Command.device_id==d['id'])))
        assert len(rows)==1
    await command(system,d,value=False,manual=300)
    temperature(3,25);temperature(4,28)
    with rt.db.session() as s:
        assert len(list(s.scalars(select(Command).where(Command.device_id==d['id']))))==2
        assert s.get(Command,rows[0].key).status=='superseded'

async def test_cycle_schedule_restart_phase_and_override(system):
    d=await device(system);rt=system['rt']
    r=await system['client'].post(f"/api/devices/{d['id']}/schedules",json={'name':'Cycle','kind':'cycle','channel':1,'value':0,'alternate_value':1,'interval_s':10,'alternate_interval_s':20})
    assert r.status_code==200,r.text
    with rt.db.session.begin() as s:
        sc=s.get(Schedule,r.json()['id']);sc.next_due_ms=now_ms()-1;due=sc.next_due_ms
    rt.core.tick()
    with rt.db.session() as s:
        sc=s.get(Schedule,r.json()['id']);assert sc.phase==1 and sc.next_due_ms==due+10_000
        commands=list(s.scalars(select(Command).where(Command.device_id==d['id'])))
        assert len(commands)==1 and commands[0].value==0
    rt.core.tick()
    with rt.db.session() as s: assert len(list(s.scalars(select(Command).where(Command.device_id==d['id']))))==1
    await system['client'].post(f"/api/devices/{d['id']}/override",json={'seconds':300})
    with rt.db.session.begin() as s: s.get(Schedule,r.json()['id']).next_due_ms=now_ms()-1
    rt.core.tick()
    with rt.db.session() as s: assert len(list(s.scalars(select(Command).where(Command.device_id==d['id']))))==1

async def test_daily_timezone_and_dst_policy(system):
    from datetime import datetime,timezone
    from omnilink.core import Core
    sc=Schedule(timezone='Asia/Kolkata',at='08:00',weekdays=list(range(7)))
    after=int(datetime(2026,10,1,0,0,tzinfo=timezone.utc).timestamp()*1000)
    assert Core.calendar_next(sc,after)==int(datetime(2026,10,1,2,30,tzinfo=timezone.utc).timestamp()*1000)
    sc.timezone='America/New_York';sc.at='02:30'
    after=int(datetime(2026,3,8,0,0,tzinfo=timezone.utc).timestamp()*1000)
    assert Core.calendar_next(sc,after)==int(datetime(2026,3,9,6,30,tzinfo=timezone.utc).timestamp()*1000)

async def test_readonly_type_bounds_and_invalid_channel(system):
    d=await device(system)
    for number,value in [(5,1),(0,1),(1,2),(3,0)]:
        r=await system['client'].post(f"/api/devices/{d['id']}/channels/{number}/write",json={'value':value})
        assert r.status_code==400,(number,r.text)
    r=await system['client'].get(f"/api/devices/{d['id']}/channels")
    assert all(c['desired'] is None and c['revision']==0 for c in r.json())

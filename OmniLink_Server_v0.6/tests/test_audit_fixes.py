"""Regression tests: worker resilience, transport-aware delivery, fair flow scheduling, roles."""
import asyncio,secrets,threading,time,zipfile
import httpx
from sqlalchemy import select
from omnilink.db import Channel,Command,Schedule,Telemetry,now_ms
from omnilink.platform_models import FlowRun
from test_platform import new,pin,widget,board,flow,publish

async def test_invalid_schedule_or_rule_does_not_stop_the_worker(system):
    c=system['client'];rt=system['rt'];d=await new(c);await pin(c,d,10,3);await pin(c,d,11,3)
    bad=(await c.post(f"/api/devices/{d['id']}/schedules",json={'name':'Bad','channel':10,'value':50})).json()['id']
    good=(await c.post(f"/api/devices/{d['id']}/schedules",json={'name':'Good','channel':11,'value':1})).json()['id']
    r=await c.post(f"/api/devices/{d['id']}/rules",json={'name':'Hot','metric':'temp','op':'gt','threshold':26,'channel':10,'value':50,'cooldown_s':0})
    assert r.status_code==200,r.text
    # The pin's bounds change after the schedule and rule were saved.
    assert (await pin(c,d,10,3,minimum=0,maximum=10)).status_code==200
    stale=(await c.post(f"/api/devices/{d['id']}/channels/11/write",json={'value':2})).json()['command_key']
    with rt.db.lock,rt.db.session.begin() as s:
        for sid in (bad,good):s.get(Schedule,sid).next_due_ms=now_ms()-1
        s.get(Command,stale).expires_ms=now_ms()-1
    rt.core.tick()
    with rt.db.session() as s:
        assert s.get(Command,stale).status=='expired'
        assert [x.channel for x in s.scalars(select(Command).where(Command.status=='queued'))]==[11]
    boot=secrets.token_hex(16);rt.core.mark_seen(d['id'],boot,'http')
    assert rt.core.telemetry(d['id'],boot,1,[{'name':'temp','type':10,'value':30}])=={'duplicate':False}
    with rt.db.session() as s:assert s.scalar(select(Telemetry).where(Telemetry.metric=='temp')) is not None

class FakeMQTT:
    ready=True
    def __init__(self):self.sent=[];self.enabled={};self.provisioned={}
    def send_command(self,device_id,c):self.sent.append(device_id);return True
    async def reconcile(self):pass
    async def stop(self):pass

async def test_http_device_commands_are_not_pushed_over_mqtt(system):
    c=system['client'];rt=system['rt'];h=await new(c,'HTTP');m=await new(c,'MQTT')
    await pin(c,h,10);await pin(c,m,11)
    rt.core.mark_seen(h['id'],secrets.token_hex(16),'http');rt.core.mark_seen(m['id'],secrets.token_hex(16),'mqtt')
    fake=FakeMQTT();rt.mqtt=fake
    try:
        await c.post(f"/api/devices/{h['id']}/channels/10/write",json={'value':True})
        await c.post(f"/api/devices/{m['id']}/channels/11/write",json={'value':True})
        await asyncio.sleep(1.2)
        assert m['id'] in fake.sent and h['id'] not in fake.sent
        assert len(rt.core.pending(h['id'],mark=True))==1
    finally:rt.mqtt=None

async def test_long_waiting_runs_do_not_starve_new_runs(system):
    c=system['client'];rt=system['rt']
    waiting=await publish(c,await flow(c,[{'id':'delay','kind':'delay','seconds':86400}]))
    quick=await publish(c,await flow(c,[{'id':'end','kind':'stop'}]))
    old=now_ms()-60_000
    with rt.db.lock,rt.db.session.begin() as s:
        for _ in range(128):
            s.add(FlowRun(id=secrets.token_hex(16),flow_id=waiting['id'],tenant_id=waiting['tenant_id'],graph=waiting['published'],
                          state={'queue':[{'id':'delay','due':now_ms()+10**9,'started':now_ms()}],'visited':['start'],'variables':{},'samples':{},'log':[],'depth':0},
                          created_ms=old,updated_ms=old))
        rid=secrets.token_hex(16)
        s.add(FlowRun(id=rid,flow_id=quick['id'],tenant_id=quick['tenant_id'],graph=quick['published'],
                      state={'queue':[{'id':'start','due':0,'started':now_ms()}],'visited':[],'variables':{},'samples':{},'log':[],'depth':0}))
    # Fair scheduling finishes it within a few ticks; ticks in the same millisecond can tie, so allow slack.
    for _ in range(10):
        rt.flows.tick();time.sleep(.01)
        with rt.db.session() as s:
            if s.get(FlowRun,rid).status=='completed':break
    with rt.db.session() as s:assert s.get(FlowRun,rid).status=='completed'

async def test_webhook_is_sent_without_the_database_lock(system):
    c=system['client'];rt=system['rt']
    r=await c.put('/api/manager/integrations',json={'name':'hook','kind':'webhook','url':'https://example.invalid/hook'});assert r.status_code==200,r.text
    f=await publish(c,await flow(c,[{'id':'hook','kind':'webhook','integration':'hook','message':'hi'}]))
    calls=[];release=threading.Event()
    def external(job):
        calls.append((job['message'],rt.db.lock._is_owned()))
        release.wait(5)  # a slow receiver
    rt.flows.external=external
    rid=(await c.post('/api/flows/'+f['id']+'/run',json={})).json()['id']
    for _ in range(40):
        started=time.monotonic();rt.flows.tick()
        assert time.monotonic()-started<1,'tick() must not wait for the integration call'
        if calls:release.set()
        with rt.db.session() as s:status=s.get(FlowRun,rid).status
        if status!='running':break
        await asyncio.sleep(.1)
    assert status=='completed' and calls==[('hi',False)]

def test_library_zip_builds_from_the_package_next_to_the_server(tmp_path):
    import sys,pytest;sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]/'tools'))
    from build_arduino_library import build,LIBRARY
    if not LIBRARY.is_dir():pytest.skip('OmniLink_Arduino_v0.3 is a separate package; place it next to the server folder')
    build(tmp_path/'lib.zip')
    names=zipfile.ZipFile(tmp_path/'lib.zip').namelist()
    assert 'OmniLink/src/OmniLink.h' in names and 'OmniLink/library.properties' in names

async def test_operator_layout_edits_do_not_delete_pins(system):
    c=system['client'];d=await new(c);await pin(c,d)
    r=await c.post('/api/users',json={'email':'operator@example.com','password':'Operator-password-123','role':'operator'});assert r.status_code==200,r.text
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as op:
        token=(await op.post('/api/auth/login',json={'email':'operator@example.com','password':'Operator-password-123'})).json()['token']
        op.headers['Authorization']='Bearer '+token
        one=await board(op,[widget(d)]);two=await board(op,[widget(d)],'Other')
        assert (await op.put('/api/dashboards/'+one['id'],json={'name':'Shared','revision':1,'widgets':[]})).status_code==200
        assert (await op.delete('/api/dashboards/'+two['id'],params={'revision':1})).status_code==200
    with system['rt'].db.session() as s:assert s.get(Channel,(d['id'],10)) is not None

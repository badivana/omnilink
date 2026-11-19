"""Account boundaries, explicit upgrade, transactional pin lifecycle and durable flows."""
import asyncio,copy,json,secrets
import xml.etree.ElementTree as ET
import httpx,pytest
from sqlalchemy import select
from omnilink import platform
from omnilink.core import DomainError
from omnilink.db import Channel,Command,Dashboard,User,Database,now_ms
from omnilink.platform_models import PinLease,Flow,FlowRun,Alert
from omnilink.flows import Engine

async def new(c,name='Device'):
    r=await c.post('/api/devices',json={'name':name});assert r.status_code==200,r.text;return r.json()
async def pin(c,d,n=10,t=1,**extra):
    return await c.put(f"/api/devices/{d['id']}/channels/{n}",json={'name':f'Pin {n}','type':t,'writable':True,**extra})
def widget(d,n=10,**kw):return {'id':secrets.token_hex(16),'kind':'switch','title':'Control','device_id':d['id'],'channel':n,**kw}
async def board(c,widgets,name='Shared'):
    r=await c.post('/api/dashboards',json={'name':name,'widgets':widgets});assert r.status_code==200,r.text;return r.json()
async def flow(c,nodes,edges=None):
    g={'nodes':[{'id':'start','kind':'trigger','event':'manual'},*nodes], 'edges':edges if edges is not None else [{'from':a,'to':b,'port':'next'} for a,b in zip(['start']+[n['id'] for n in nodes], [n['id'] for n in nodes])]}
    r=await c.post('/api/flows',json={'name':'Test flow','graph':g});assert r.status_code==200,r.text;return r.json()
async def publish(c,f):
    r=await c.post('/api/flows/'+f['id']+'/publish',params={'revision':f['revision']});assert r.status_code==200,r.text;return r.json()

async def test_registration_unique_pool_and_manager_isolation(system):
    c=system['client'];a=await new(c);b=await new(c)
    assert (await pin(c,a)).status_code==200
    assert (await pin(c,b)).status_code==409
    assert (await pin(c,b,255)).status_code==400
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as other:
        credentials={'email':'new-owner@example.com','password':'New-Owner-Password-123'}
        assert (await other.post('/api/auth/register',json=credentials)).status_code==200
        login=(await other.post('/api/auth/login',json=credentials)).json();other.headers['Authorization']='Bearer '+login['token']
        assert (await other.get('/api/devices')).json()==[]
        assert (await other.get('/api/manager/settings')).status_code==403
        assert (await other.get(f"/api/devices/{a['id']}/channels")).status_code==404
        owned=await new(other);assert (await pin(other,owned)).status_code==200
        cross=await other.post('/api/dashboards',json={'name':'Unauthorized','widgets':[widget(a)]});assert cross.status_code==404
        me=(await other.get('/api/auth/me')).json();assert me['manager'] is False
        assert (await c.patch('/api/manager/accounts/'+me['account_id'],json={'enabled':False})).status_code==200
        assert (await other.get('/api/devices')).status_code==401
        with pytest.raises(DomainError):system['rt'].core.authenticate_device(owned['id'],owned['secret'])

async def test_manager_deletes_account_user_and_revokes_sessions(system):
    c=system['client']
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as owner:
        credentials={'email':'delete-owner@example.com','password':'Delete-Owner-Password-123'}
        registered=await owner.post('/api/auth/register',json=credentials);assert registered.status_code==200
        login=(await owner.post('/api/auth/login',json=credentials)).json();owner.headers['Authorization']='Bearer '+login['token']
        account_id=(await owner.get('/api/auth/me')).json()['account_id']
        d=await new(owner,'Keep this device')
        created=await owner.post('/api/users',json={'email':'remove-me@example.com','password':'Remove-Me-Password-123','role':'admin'})
        assert created.status_code==200,created.text;target=created.json()
        async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as user:
            authz=(await user.post('/api/auth/login',json={'email':'remove-me@example.com','password':'Remove-Me-Password-123'})).json()
            user.headers['Authorization']='Bearer '+authz['token']
            assert (await user.get('/api/devices')).status_code==200
            accounts=(await c.get('/api/manager/accounts')).json()
            account=next(a for a in accounts if a['id']==account_id)
            assert {u['id'] for u in account['users']} >= {registered.json()['id'],target['id']}
            me=(await c.get('/api/auth/me')).json();manager_account=next(a for a in accounts if a['id']==me['account_id'])
            manager_user=next(u for u in manager_account['users'] if u['email']==me['email'])
            assert (await c.delete(f"/api/manager/accounts/{me['account_id']}/users/{manager_user['id']}")).status_code==403
            assert (await c.delete(f"/api/manager/accounts/{account_id}/users/{target['id']}")).status_code==200
            assert (await user.get('/api/devices')).status_code==401
            assert (await c.delete(f"/api/manager/accounts/{account_id}/users/{registered.json()['id']}")).status_code==409
            after=(await c.get('/api/manager/accounts')).json()
            retained=next(a for a in after if a['id']==account_id)
            assert retained['devices']==1 and [u['id'] for u in retained['users']]==[registered.json()['id']]

async def test_flow_accepts_mxgraphmodel_and_rejects_mismatched_cells(system):
    c=system['client'];nodes=[{'id':'0','kind':'trigger','event':'manual','label':'Start','x':60,'y':40},
                              {'id':'1','kind':'stop','label':'Stop','x':360,'y':40}]
    edges=[{'from':'0','to':'1','port':'next'}]
    model=ET.Element('mxGraphModel');root=ET.SubElement(model,'root');ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0')
    for n in nodes:
        cell=ET.SubElement(root,'mxCell',id='vertex_'+n['id'],value=n['label'],vertex='1',parent='1',omni=json.dumps(n))
        ET.SubElement(cell,'mxGeometry',x=str(n['x']),y=str(n['y']),width='220',height='122',attrib={'as':'geometry'})
    edge=ET.SubElement(root,'mxCell',id='edge_0',value='next',edge='1',parent='1',source='vertex_0',target='vertex_1',omni=json.dumps({'port':'next'}))
    ET.SubElement(edge,'mxGeometry',relative='1',attrib={'as':'geometry'})
    graph={'nodes':nodes,'edges':edges};xml=ET.tostring(model,encoding='unicode')
    made=await c.post('/api/flows',json={'name':'Native model','graph':graph})
    assert made.status_code==200,made.text
    fid=made.json()['id'];saved=await c.put(f'/api/flows/{fid}/mxgraph',json={'mxGraphModel':xml})
    assert saved.status_code==200,saved.text
    assert (await c.get(f'/api/flows/{fid}/mxgraph')).json()['mxGraphModel'].startswith('<mxGraphModel')
    badxml=ET.fromstring(xml);start=next(cell for cell in badxml.findall('./root/mxCell') if cell.get('id')=='vertex_0');start.set('omni',json.dumps({**nodes[0],'label':'Changed'}))
    rejected=await c.put(f'/api/flows/{fid}/mxgraph',json={'mxGraphModel':ET.tostring(badxml,encoding='unicode')})
    assert rejected.status_code==400
    assert 'mxGraphModel' not in made.json()['draft']

async def test_release_is_atomic_and_reuse_has_no_old_command(system):
    c=system['client'];rt=system['rt'];a=await new(c);b=await new(c);await pin(c,a)
    one=await board(c,[widget(a)],'First');two=await board(c,[widget(a)],'Second')
    change={'name':'First','revision':one['revision'],'widgets':[]}
    result=await c.put('/api/dashboards/'+one['id'],json=change)
    assert result.status_code==409 and result.json()['dependencies'][0]['name']=='Second / Control'
    assert len((await c.get('/api/dashboards')).json()[0]['widgets'])==1
    # Rebind the other widget to a different pin; deletion alone must not silently free shared pins.
    await pin(c,b,11);w=two['widgets'][0];w.update(device_id=b['id'],channel=11)
    assert (await c.put('/api/dashboards/'+two['id'],json={'name':'Second','revision':1,'widgets':[w]})).status_code==200
    cmd=(await c.post(f"/api/devices/{a['id']}/channels/10/write",json={'value':True})).json()
    assert (await c.put('/api/dashboards/'+one['id'],json=change)).status_code==200
    assert 10 in (await c.get('/api/pins')).json()['free']
    assert (await pin(c,b,10)).status_code==200
    assert rt.core.pending(b['id'])==[]
    with pytest.raises(DomainError):rt.core.acknowledge(b['id'],cmd['command_key'],cmd['desired_revision'],'applied')
    with rt.db.session() as s:assert s.get(Command,cmd['command_key']) is None
    # Empty layout must remain empty after reload.
    boards=(await c.get('/api/dashboards')).json();assert next(x for x in boards if x['id']==one['id'])['widgets']==[]

async def test_same_board_and_flow_references_block_release(system):
    c=system['client'];d=await new(c);await pin(c,d)
    a=widget(d);b=widget(d);board1=await board(c,[a,b])
    r=await c.put('/api/dashboards/'+board1['id'],json={'name':'One','revision':1,'widgets':[b]})
    assert r.status_code==409 and r.json()['dependencies'][0]['id']==b['id']
    f=await flow(c,[{'id':'write','kind':'write','device_id':d['id'],'pin':10,'value':True}]);await publish(c,f)
    r=await c.put('/api/dashboards/'+board1['id'],json={'name':'One','revision':1,'widgets':[]})
    assert r.status_code==409 and any(x['kind']=='flow' for x in r.json()['dependencies'])
    assert (await c.delete('/api/flows/'+f['id'])).status_code==200
    assert (await c.put('/api/dashboards/'+board1['id'],json={'name':'One','revision':1,'widgets':[]})).status_code==200

async def test_upgrade_conflicts_preserve_firmware_and_require_explicit_move(system):
    c=system['client'];rt=system['rt'];a=await new(c);b=await new(c);await pin(c,a)
    cmd=(await c.post(f"/api/devices/{a['id']}/channels/10/write",json={'value':True})).json()
    # v0.4 database shape: two devices own V10, no unique account constraint.
    with rt.db.lock,rt.db.session.begin() as s:s.add(Channel(device_id=b['id'],number=10,name='Legacy',type=1,writable=True))
    platform.initialize(rt)
    with rt.db.session() as s:
        assert s.get(Channel,(a['id'],10)) and s.get(Channel,(b['id'],10))
        assert s.get(Command,cmd['command_key']).status=='superseded'
    inv=(await c.get('/api/pins')).json();assert inv['pins'][0]['conflict']
    assert (await c.post(f"/api/devices/{a['id']}/channels/10/write",json={'value':False})).status_code==409
    old=await board(c,[widget(b)])
    url=f"/api/devices/{b['id']}/channels/10/move"
    assert (await c.post(url,json={'new_number':12})).status_code==400
    assert (await c.post(url,json={'new_number':12,'confirm_firmware_update':True})).status_code==200
    inv=(await c.get('/api/pins')).json();assert not any(p['conflict'] for p in inv['pins'])
    with rt.db.session() as s:
        assert s.get(Channel,(a['id'],10));assert s.get(Channel,(b['id'],10)) is None
        assert s.get(Dashboard,old['id']).widgets[0]['channel']==12
        lease=s.get(PinLease,(s.get(User,platform.manager_id(s)).tenant_id,12));generation=lease.allocation_id
    platform.initialize(rt)
    with rt.db.session() as s:assert s.get(PinLease,(lease.tenant_id,12)).allocation_id==generation

async def test_move_disables_automation_and_rejects_old_snapshot(system):
    c=system['client'];rt=system['rt'];d=await new(c);await pin(c,d)
    f=await publish(c,await flow(c,[{'id':'write','kind':'write','device_id':d['id'],'pin':10,'value':True}]))
    snapshot=copy.deepcopy(f['published'])
    assert (await c.post(f"/api/devices/{d['id']}/channels/10/move",json={'new_number':11,'confirm_firmware_update':True})).status_code==200
    result=(await c.get('/api/flows')).json()[0];assert not result['enabled'] and result['published'] is None and result['draft']['nodes'][1]['pin']==11
    await pin(c,d,10)
    with rt.db.lock,rt.db.session.begin() as s:
        item=s.get(Flow,f['id']);run=rt.flows.launch(s,item,snapshot);s.flush();rid=run.id
    rt.flows.tick();rt.flows.tick()
    with rt.db.session() as s:assert s.get(FlowRun,rid).status=='failed'
    assert rt.core.pending(d['id'])==[]

async def test_flow_branch_test_mode_durable_delay_and_ack(system):
    c=system['client'];rt=system['rt'];d=await new(c);await pin(c,d)
    nodes=[{'id':'check','kind':'condition','device_id':d['id'],'pin':10,'op':'eq','value':True}, {'id':'delay','kind':'delay','seconds':20}, {'id':'write','kind':'write','device_id':d['id'],'pin':10,'value':False,'wait_ack':True}, {'id':'alert','kind':'alert','message':'Applied'}]
    edges=[{'from':'start','to':'check'},{'from':'check','to':'delay','port':'yes'},{'from':'delay','to':'write'},{'from':'write','to':'alert'}]
    f=await publish(c,await flow(c,nodes,edges))
    r=await c.post('/api/flows/'+f['id']+'/run',json={'test':True,'samples':{d['id']+':10':True}});assert r.status_code==200,r.text;rid=r.json()['id']
    for _ in range(6):rt.flows.tick()
    with rt.db.session() as s:
        assert s.get(FlowRun,rid).status=='completed'
        assert s.scalar(select(Command)) is None and s.scalar(select(Alert)) is None
    with rt.db.lock,rt.db.session.begin() as s:s.get(Channel,(d['id'],10)).reported=True
    rid=(await c.post('/api/flows/'+f['id']+'/run',json={'test':False})).json()['id']
    for _ in range(3):rt.flows.tick()
    db=Database(rt.settings.database_url)
    try:
        with db.session() as s:
            stored=s.get(FlowRun,rid);assert stored.status=='running' and stored.state['queue'][0]['id']=='delay'
    finally:db.engine.dispose()
    # Emulate the saved wait becoming due after a server restart.
    with rt.db.lock,rt.db.session.begin() as s:
        r=s.get(FlowRun,rid);state=copy.deepcopy(r.state);state['queue'][0].update(started=now_ms()-21000,due=0);r.state=state
    engine=Engine(rt);engine.tick();engine.tick()
    cmd=rt.core.pending(d['id'])[0];rt.core.acknowledge(d['id'],cmd['command_key'],cmd['desired_revision'],'applied')
    with rt.db.lock,rt.db.session.begin() as s:
        r=s.get(FlowRun,rid);state=copy.deepcopy(r.state);state['queue'][0]['due']=0;r.state=state
    engine.tick();engine.tick()
    with rt.db.session() as s:assert s.get(FlowRun,rid).status=='completed' and s.scalar(select(Alert)).message=='Applied'

async def test_new_widgets_validation_and_cross_device_layout(system):
    c=system['client'];a=await new(c,'A');b=await new(c,'B')
    await pin(c,a,0);await pin(c,a,1,10);await pin(c,a,2,10);await pin(c,b,3,12)
    target=await board(c,[],'Destination')
    specs=[('selector',0,{'options':[{'label':'On','value':True}]}),('joystick',1,{'channel_y':2}),('colour',3,{'device_id':b['id']}),('schedule',None,{}),('status',None,{}),('table',None,{}),('navigation',None,{'target_dashboard':target['id']}),('stepper',1,{}),('progress',1,{}),('map',1,{'channel_y':2,'source':'telemetry'}),('floorplan',None,{'points':[{'device_id':a['id'],'channel':0,'x':50,'y':50,'label':'Power','symbol':'motor'}]}),('process',None,{}),('chart',None,{'series':[{'device_id':a['id'],'metric':'temperature'},{'device_id':b['id'],'metric':'temperature'}]})]
    result=await board(c,[widget(a,n,kind=k,**kw) for k,n,kw in specs]);assert len(result['widgets'])==13
    assert next(w for w in result['widgets'] if w['kind']=='map')['source']=='reported'
    r=await c.post('/api/dashboards',json={'name':'Invalid','widgets':[widget(a,0,kind='colour')]});assert r.status_code==400
    r=await c.post('/api/flows',json={'name':'Cycle','graph':{'nodes':[{'id':'s','kind':'trigger'},{'id':'n','kind':'delay'}],'edges':[{'from':'s','to':'n'},{'from':'n','to':'n'}]}});assert r.status_code==400

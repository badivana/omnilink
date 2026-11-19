import secrets
import httpx
from sqlalchemy import select
from omnilink.db import Dashboard, Database, Tenant, User
from omnilink.auth import new_user
from conftest import device

def widget(kind='switch',channel=0,**extra):
    return {'id':secrets.token_hex(16),'kind':kind,'title':'Control','channel':channel,**extra}

async def test_layout_persistence_and_conflicting_browser_edits(system):
    d=await device(system);c=system['client'];url=f"/api/devices/{d['id']}/dashboards"
    r=await c.post(url,json={'name':'Aquarium','widgets':[widget(),widget('text',None,text='<img src=x onerror=alert(1)>')]})
    assert r.status_code==200,r.text
    board=r.json();assert board['revision']==1
    db=Database(system['rt'].settings.database_url)
    try:
        with db.session() as s:
            saved=s.get(Dashboard,board['id'])
            assert saved.widgets==board['widgets'] and saved.name=='Aquarium'
    finally: db.engine.dispose()
    body={'name':'Edited from browser A','widgets':board['widgets'],'revision':1}
    first=await c.put(url+'/'+board['id'],json=body)
    assert first.status_code==200 and first.json()['revision']==2
    body['name']='Stale browser B'
    assert (await c.put(url+'/'+board['id'],json=body)).status_code==409
    assert (await c.delete(url+'/'+board['id']+'?revision=1')).status_code==409
    assert (await c.get(url)).json()[0]['name']=='Edited from browser A'
    assert (await c.delete(url+'/'+board['id']+'?revision=2')).status_code==200
    assert (await c.get(url)).json()==[]

async def test_dashboard_tenant_viewer_and_device_boundaries(system):
    a=await device(system);b=(await system['client'].post('/api/devices',json={'name':'Second device'})).json();rt=system['rt'];c=system['client'];url=f"/api/devices/{a['id']}/dashboards"
    board=(await c.post(url,json={'name':'Private','widgets':[widget()]})).json()
    other_url=f"/api/devices/{b['id']}/dashboards/{board['id']}"
    body={'name':'Cross device','widgets':[],'revision':1}
    assert (await c.put(other_url,json=body)).status_code==404
    with rt.db.session.begin() as s:
        owner=s.scalar(select(User).where(User.email==rt.settings.bootstrap_email))
        new_user(s,owner.tenant_id,'layout-viewer@example.com','Viewer-password-12345','viewer')
        tenant=Tenant(id=secrets.token_hex(16),name='Other tenant');s.add(tenant)
        new_user(s,tenant.id,'layout-other@example.com','Other-password-12345')
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as client:
        for email,password,expected in [('layout-other@example.com','Other-password-12345',404),('layout-viewer@example.com','Viewer-password-12345',200)]:
            login=(await client.post('/api/auth/login',json={'email':email,'password':password})).json()
            client.headers['Authorization']='Bearer '+login['token']
            assert (await client.get(url)).status_code==expected
            assert (await client.post(url,json={'name':'Denied','widgets':[]})).status_code in (403,404)
            assert (await client.put(url+'/'+board['id'],json=body)).status_code in (403,404)

async def test_widget_bindings_limits_and_data_types(system):
    d=await device(system);c=system['client'];url=f"/api/devices/{d['id']}/dashboards"
    invalid=[widget('switch',5,on_value=1,off_value=0),widget('slider',0),widget('switch',1),
             widget('slider',1,minimum=0,maximum=2),widget('switch',0,on_value=True,off_value=True),
             widget('value',999),widget('chart',None),widget('bluetooth',None,service='invalid',characteristic='2a6e')]
    for bad in invalid:
        r=await c.post(url,json={'name':'Invalid','widgets':[bad]})
        assert r.status_code in (400,422),r.text
    same=widget()
    assert (await c.post(url,json={'name':'Duplicate','widgets':[same,same]})).status_code==422
    assert (await c.post(url,json={'name':'Too many','widgets':[widget('text',None) for _ in range(49)]})).status_code==422
    valid=[widget('switch',1,on_value=1,off_value=0),widget('slider',3,minimum=10,maximum=300,step=10),
           widget('gauge',None,source='telemetry',metric='temperature',maximum=40),
           widget('bluetooth',None,service='181a',characteristic='2a6e'),widget('serial',None,baud=115200)]
    r=await c.post(url,json={'name':'Valid','widgets':valid});assert r.status_code==200,r.text

async def test_layout_cookie_csrf_and_public_pwa_shell(system):
    d=await device(system);url=f"/api/devices/{d['id']}/dashboards"
    async with httpx.AsyncClient(base_url=system['url'],trust_env=False) as c:
        auth=(await c.post('/api/auth/login',json={'email':'admin@example.com','password':'Correct-Horse-Battery-47'})).json()
        body={'name':'Saved','widgets':[]}
        assert (await c.post(url,json=body)).status_code==403
        assert (await c.post(url,json=body,headers={'X-CSRF-Token':auth['csrf']})).status_code==200
        root=await c.get('/');assert "media-src 'self' blob:" in root.headers['Content-Security-Policy']
        assert 'camera=(self)' in root.headers['Permissions-Policy']
        sw=await c.get('/sw.js');assert sw.status_code==200 and 'no-cache' in sw.headers['Cache-Control']
        assert (await c.get('/client/')).status_code==404
        assert 'id="widget-grid"' not in root.text

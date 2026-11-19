import copy,json,re,secrets,time
from datetime import datetime
from urllib.parse import urlparse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,delete,func
from sqlalchemy.exc import IntegrityError
from fastapi import Request
from .db import *
from .platform_models import *
from . import auth,platform,flows
from .core import DomainError,obj
from .dashboards import DashboardBody,DashboardEdit,validate_widgets,dashboard_obj

class Body(BaseModel):model_config=ConfigDict(extra='forbid')
class Registration(Body):
    email:str=Field(max_length=254)
    password:str=Field(min_length=12,max_length=256)
class Limits(Body):
    signup_enabled:bool=True
    pin_limit:int=Field(default=255,ge=1,le=1024)
    max_devices:int=Field(default=64,ge=1,le=1000)
    max_dashboards:int=Field(default=32,ge=1,le=200)
    max_flows:int=Field(default=64,ge=1,le=200)
class AccountEdit(Body):
    enabled:bool|None=None
    pin_limit:int|None=Field(default=None,ge=1,le=1024)
class Move(Body):
    new_number:int=Field(ge=0,le=1023)
    confirm_firmware_update:bool=False
class FlowBody(Body):
    name:str=Field(min_length=1,max_length=80)
    graph:dict
    revision:int|None=None
class FlowModelBody(Body):
    mxGraphModel:str=Field(min_length=1,max_length=262144)
class RunBody(Body):
    test:bool=False
    samples:dict=Field(default_factory=dict)
class Integration(Body):
    name:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    kind:str
    url:str=''
    host:str=''
    port:int=Field(default=587,ge=1,le=65535)
    sender:str=''
    username:str=''
    secret:str=Field(default='',max_length=1024)

def install(app,rt):
    def notify(u,kind):rt.broadcast(u.tenant_id,kind,{})
    @app.get('/api/public/settings')
    def public():
        with rt.db.session() as s:return {'signup_enabled':platform.settings(s)['signup_enabled']}
    @app.post('/api/auth/register')
    def register(body:Registration,request:Request):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=rt.settings.public_url.rstrip('/'):raise DomainError('Origin rejected',403)
        ip='signup:'+request.client.host;now=time.monotonic()
        with rt.db.lock:
            attempts=[t for t in rt.login_attempts.get(ip,[]) if t>now-3600]
            if len(attempts)>=5:raise DomainError('Registration limit reached. Try again later.',429)
            rt.login_attempts[ip]=attempts+[now]
            with rt.db.session.begin() as s:
                if not platform.settings(s)['signup_enabled']:raise DomainError('Account registration is disabled',403)
                tenant=Tenant(id=secrets.token_hex(16),name=body.email[:120]);s.add(tenant)
                user=auth.new_user(s,tenant.id,body.email,body.password,'admin');s.add(Account(tenant_id=tenant.id))
                return {'id':user.id,'email':user.email,'message':'Account created. Sign in to create your devices.'}
    @app.get('/api/manager/settings')
    def manager_settings(request:Request):
        platform.manager(request)
        with rt.db.session() as s:return platform.settings(s)
    @app.put('/api/manager/settings')
    def save_settings(body:Limits,request:Request):
        platform.manager(request)
        with rt.db.lock,rt.db.session.begin() as s:s.get(PlatformSetting,'limits').value=body.model_dump()
        return {'ok':True}
    @app.get('/api/manager/accounts')
    def accounts(request:Request):
        platform.manager(request)
        with rt.db.session() as s:
            result=[]
            for a in s.scalars(select(Account)):
                users=list(s.scalars(select(User).where(User.tenant_id==a.tenant_id)))
                result.append({'id':a.tenant_id,'enabled':a.enabled,'pin_limit':platform.limit(s,a.tenant_id),'users':[{'id':u.id,'email':u.email,'role':u.role,'enabled':u.enabled} for u in users],
                               'devices':s.scalar(select(func.count()).select_from(Device).where(Device.tenant_id==a.tenant_id)),
                               'pins':platform.pin_inventory(s,a.tenant_id)})
            return result
    @app.delete('/api/manager/accounts/{account_id}/users/{user_id}')
    def delete_account_user(account_id:str,user_id:str,request:Request):
        manager=platform.manager(request)
        if user_id==manager.id:raise DomainError('The active server manager cannot be deleted',403)
        with rt.db.lock,rt.db.session.begin() as s:
            user=s.get(User,user_id)
            if not user or user.tenant_id!=account_id:raise DomainError('Account user not found',404)
            if user.enabled and user.role=='admin':
                admins=s.scalar(select(func.count()).select_from(User).where(User.tenant_id==account_id,User.role=='admin',User.enabled.is_(True)))
                if admins<=1:raise DomainError('This is the account’s last enabled administrator. Add another administrator before deleting this user.',409)
            s.execute(delete(Session).where(Session.user_id==user_id))
            s.delete(user)
        return {'ok':True}
    @app.patch('/api/manager/accounts/{account_id}')
    async def edit_account(account_id:str,body:AccountEdit,request:Request):
        u=platform.manager(request)
        if account_id==u.tenant_id and body.enabled is False:raise DomainError('The manager cannot disable their own account')
        with rt.db.lock,rt.db.session.begin() as s:
            a=s.get(Account,account_id)
            if not a:raise DomainError('Account not found',404)
            for key,val in body.model_dump(exclude_none=True).items():setattr(a,key,val)
            ids=list(s.scalars(select(Device.id).where(Device.tenant_id==account_id)))
            if body.enabled is False:
                uids=list(s.scalars(select(User.id).where(User.tenant_id==account_id)))
                s.execute(delete(Session).where(Session.user_id.in_(uids)))
                for command in s.scalars(select(Command).where(Command.device_id.in_(ids),Command.status.in_(['queued','sent','accepted']))):command.status='superseded'
                for run in s.scalars(select(FlowRun).where(FlowRun.tenant_id==account_id,FlowRun.status=='running')):run.status='cancelled'
        if body.enabled is False:
            for did in ids:
                if did in rt.native_sessions:await rt.native_sessions[did].close()
        return {'ok':True}
    @app.get('/api/integrations')
    def integrations(request:Request):
        auth.user(request)
        with rt.db.session() as s:
            cfg=s.get(PlatformSetting,'integrations')
            return [{'name':name,'kind':v['kind']} for name,v in (cfg.value if cfg else {}).items()]
    @app.put('/api/manager/integrations')
    def integration(body:Integration,request:Request):
        platform.manager(request)
        if body.kind not in ('webhook','email'):raise DomainError('Integration must be webhook or email')
        if body.kind=='webhook' and (urlparse(body.url).scheme not in ('https','http') or not urlparse(body.url).hostname or urlparse(body.url).username):raise DomainError('Use an HTTP(S) URL without embedded credentials')
        if body.kind=='email' and (not body.host or '@' not in body.sender or any(c in body.sender for c in '\r\n')):raise DomainError('SMTP host and sender required')
        value=body.model_dump(exclude={'name','secret'});value['secret_cipher']=rt.core.cipher.encrypt(body.secret.encode()).decode() if body.secret else ''
        with rt.db.lock,rt.db.session.begin() as s:
            cfg=s.get(PlatformSetting,'integrations')
            if not cfg:cfg=PlatformSetting(key='integrations',value={});s.add(cfg)
            cfg.value={**cfg.value,body.name:value}
        return {'ok':True}
    @app.get('/api/pins')
    def pins(request:Request):
        u=auth.user(request)
        with rt.db.session() as s:return platform.pin_inventory(s,u.tenant_id)
    @app.get('/api/devices/{device_id}/channels/{number}/dependencies')
    def pin_dependencies(device_id:str,number:int,request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            rt.core.device(s,device_id,u.tenant_id)
            return platform.dependencies(s,u.tenant_id,{(device_id,number)})
    @app.delete('/api/devices/{device_id}/channels/{number}')
    def delete_pin(device_id:str,number:int,request:Request):
        u=auth.admin(request)
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id);platform.release(s,u.tenant_id,{(device_id,number)})
        notify(u,'pins');return {'ok':True}
    @app.post('/api/devices/{device_id}/channels/{number}/move')
    def move_pin(device_id:str,number:int,body:Move,request:Request):
        u=auth.admin(request)
        if not body.confirm_firmware_update:raise DomainError('Confirm that you will update the device firmware pin mapping')
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id);old=s.get(Channel,(device_id,number))
            if not old:raise DomainError('Channel not found',404)
            if s.get(Channel,(device_id,body.new_number)):raise DomainError('Target pin already exists',409)
            active=[d for d in platform.dependencies(s,u.tenant_id,{(device_id,number)}) if d['kind']=='execution']
            if active:
                err=DomainError('Cancel the running flow before moving this pin',409);err.dependencies=active;raise err
            platform.claim(s,u.tenant_id,device_id,body.new_number)
            s.add(Channel(device_id=device_id,number=body.new_number,name=old.name,type=old.type,writable=old.writable,minimum=old.minimum,maximum=old.maximum))
            for board in s.scalars(select(Dashboard).where(Dashboard.tenant_id==u.tenant_id)):
                widgets=copy.deepcopy(board.widgets);changed=False
                for w in widgets:
                    if (w.get('device_id') or board.device_id)==device_id:
                        for key in ('channel','channel_y'):
                            if w.get(key)==number:w[key]=body.new_number;changed=True
                    for point in w.get('points',[]):
                        if point.get('device_id')==device_id and point.get('channel')==number:point['channel']=body.new_number;changed=True
                if changed:board.widgets=widgets;board.revision+=1
            for cls in (Rule,Schedule):
                for item in s.scalars(select(cls).where(cls.device_id==device_id,cls.channel==number)):item.channel=body.new_number;item.enabled=False
            for flow in s.scalars(select(Flow).where(Flow.tenant_id==u.tenant_id)):
                if (device_id,number) in platform.graph_refs(flow.draft)|platform.graph_refs(flow.published):
                    draft=copy.deepcopy(flow.draft)
                    for n in draft['nodes']:
                        if n.get('device_id')==device_id and n.get('pin')==number:n['pin']=body.new_number;n.pop('allocation_id',None)
                    flow.draft=draft;flow.published=None;flow.enabled=False;flow.revision+=1
            s.delete(old);s.execute(delete(Command).where(Command.device_id==device_id,Command.channel==number));s.flush();platform.reconcile_pin(s,u.tenant_id,number)
        notify(u,'pins');return {'ok':True,'message':'Pin moved explicitly. Update firmware. Affected automation is disabled until reviewed.'}
    @app.delete('/api/devices/{device_id}')
    async def delete_device(device_id:str,request:Request):
        u=auth.admin(request)
        with rt.db.lock,rt.db.session.begin() as s:
            d=rt.core.device(s,device_id,u.tenant_id)
            refs={(device_id,n) for n in s.scalars(select(Channel.number).where(Channel.device_id==device_id))}
            platform.release(s,u.tenant_id,refs)
            # Device-only widgets/flows also need explicit removal.
            for b in s.scalars(select(Dashboard).where(Dashboard.tenant_id==u.tenant_id)):
                if any(w.get('device_id')==device_id for w in b.widgets):raise DomainError('Remove dashboard references to this device first',409)
            for f in s.scalars(select(Flow).where(Flow.tenant_id==u.tenant_id)):
                if any(n.get('device_id')==device_id for g in [f.draft,f.published or {}] for n in g.get('nodes',[])):raise DomainError('Remove flow references to this device first',409)
            for cls in (Command,Telemetry,DeviceEvent,Receipt,Rule,Schedule):s.execute(delete(cls).where(cls.device_id==device_id))
            s.delete(d)
        if device_id in rt.native_sessions:await rt.native_sessions[device_id].close()
        notify(u,'device');return {'ok':True}
    @app.get('/api/dashboards')
    def boards(request:Request):
        u=auth.user(request)
        with rt.db.session() as s:return [dashboard_obj(b) for b in s.scalars(select(Dashboard).where(Dashboard.tenant_id==u.tenant_id).order_by(Dashboard.updated_ms))]
    @app.post('/api/dashboards')
    def create_board(body:DashboardBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            count=s.scalar(select(func.count()).select_from(Dashboard).where(Dashboard.tenant_id==u.tenant_id))
            if count>=platform.settings(s)['max_dashboards']:raise DomainError('Account dashboard limit reached')
            b=Dashboard(id=secrets.token_hex(16),tenant_id=u.tenant_id,device_id='*',name=body.name,widgets=validate_widgets(rt.core,s,'',body.widgets,u.tenant_id));s.add(b);s.flush();result=dashboard_obj(b)
        notify(u,'dashboard');return result
    def board(s,u,bid):
        b=s.get(Dashboard,bid)
        if not b or b.tenant_id!=u.tenant_id:raise DomainError('Dashboard not found',404)
        return b
    @app.put('/api/dashboards/{bid}')
    def save_board(bid:str,body:DashboardEdit,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            b=board(s,u,bid);widgets=validate_widgets(rt.core,s,b.device_id if b.device_id!='*' else '',body.widgets,u.tenant_id)
            platform.update_board(rt,s,b,widgets,body.name,body.revision);result=dashboard_obj(b)
        notify(u,'dashboard');return result
    @app.delete('/api/dashboards/{bid}')
    def remove_board(bid:str,revision:int,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            b=board(s,u,bid)
            if b.revision!=revision:raise DomainError('Dashboard changed. Reload first.',409)
            refs=set().union(*(platform.widget_refs(w,b.device_id) for w in b.widgets)) if b.widgets else set()
            platform.release(s,u.tenant_id,refs,b.id);s.delete(b)
        notify(u,'dashboard');return {'ok':True}
    @app.get('/api/history')
    def history(request:Request,device_id:str,metric:str='',start_ms:int=0,end_ms:int=9223372036854775807,limit:int=1000):
        u=auth.user(request)
        with rt.db.session() as s:
            rt.core.device(s,device_id,u.tenant_id)
            query=select(Telemetry).where(Telemetry.device_id==device_id,Telemetry.received_ms>=start_ms,Telemetry.received_ms<=end_ms)
            if metric:query=query.where(Telemetry.metric==metric)
            return [obj(row) for row in s.scalars(query.order_by(Telemetry.received_ms.desc()).limit(max(1,min(10000,limit))))]
    @app.get('/api/alerts')
    def alerts(request:Request):
        u=auth.user(request)
        with rt.db.session() as s:return [obj(a) for a in s.scalars(select(Alert).where(Alert.tenant_id==u.tenant_id).order_by(Alert.created_ms.desc()).limit(500))]
    @app.post('/api/alerts/{aid}/ack')
    def ack_alert(aid:str,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            a=s.get(Alert,aid)
            if not a or a.tenant_id!=u.tenant_id:raise DomainError('Alert not found',404)
            a.acknowledged=True
        notify(u,'alert');return {'ok':True}
    def flow(s,u,fid):
        f=s.get(Flow,fid)
        if not f or f.tenant_id!=u.tenant_id:raise DomainError('Flow not found',404)
        return f
    @app.get('/api/flows')
    def flow_list(request:Request):
        u=auth.user(request)
        with rt.db.session() as s:return [obj(f) for f in s.scalars(select(Flow).where(Flow.tenant_id==u.tenant_id))]
    @app.get('/api/flows/{fid}/mxgraph')
    def flow_model_get(fid:str,request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            f=flow(s,u,fid);model=s.get(FlowVisualModel,fid)
            return {'mxGraphModel':model.mx_graph_model if model else ''}
    @app.put('/api/flows/{fid}/mxgraph')
    def flow_model_save(fid:str,body:FlowModelBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid);flows.validate(rt,s,u.tenant_id,f.draft);flows.validate_mx_model(f.draft,body.mxGraphModel)
            model=s.get(FlowVisualModel,fid)
            if not model:model=FlowVisualModel(flow_id=fid,mx_graph_model=body.mxGraphModel);s.add(model)
            else:model.mx_graph_model=body.mxGraphModel
        return {'ok':True}
    @app.post('/api/flows')
    def flow_new(body:FlowBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            if s.scalar(select(func.count()).select_from(Flow).where(Flow.tenant_id==u.tenant_id))>=platform.settings(s)['max_flows']:raise DomainError('Flow limit reached')
            f=Flow(id=secrets.token_hex(16),tenant_id=u.tenant_id,name=body.name,draft=flows.validate(rt,s,u.tenant_id,body.graph));s.add(f);s.flush();return obj(f)
    @app.put('/api/flows/{fid}')
    def flow_save(fid:str,body:FlowBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid)
            if body.revision!=f.revision:raise DomainError('Flow changed. Reload before saving.',409)
            f.draft=flows.validate(rt,s,u.tenant_id,body.graph);f.name=body.name;f.revision+=1;return obj(f)
    @app.post('/api/flows/{fid}/publish')
    def flow_publish(fid:str,revision:int,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid)
            if revision!=f.revision:raise DomainError('Flow changed. Reload first.',409)
            f.published=flows.validate(rt,s,u.tenant_id,f.draft);f.enabled=True;f.next_due_ms=0;f.trigger_state={};f.revision+=1;return obj(f)
    @app.post('/api/flows/{fid}/pause')
    def flow_pause(fid:str,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid);f.enabled=False;f.revision+=1
            for r in s.scalars(select(FlowRun).where(FlowRun.flow_id==fid,FlowRun.status=='running')):r.status='cancelled'
        return {'ok':True}
    @app.post('/api/flows/{fid}/run')
    def flow_run(fid:str,body:RunBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid)
            if not body.test and not f.enabled:raise DomainError('Publish the flow before running it')
            graph=flows.validate(rt,s,u.tenant_id,f.draft if body.test else f.published)
            if len(body.samples)>64:raise DomainError('Too many test samples')
            r=rt.flows.launch(s,f,graph,body.test,body.samples);s.flush();return obj(r)
    @app.get('/api/flows/{fid}/runs')
    def flow_runs(fid:str,request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            flow(s,u,fid);return [obj(r) for r in s.scalars(select(FlowRun).where(FlowRun.flow_id==fid).order_by(FlowRun.created_ms.desc()).limit(30))]
    @app.delete('/api/flows/{fid}')
    def flow_delete(fid:str,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            f=flow(s,u,fid)
            for other in s.scalars(select(Flow).where(Flow.tenant_id==u.tenant_id,Flow.id!=fid)):
                if any(n.get('flow_id')==fid for g in (other.draft,other.published or {}) for n in g.get('nodes',[])):raise DomainError('Another flow references this flow',409)
            for r in s.scalars(select(FlowRun).where(FlowRun.flow_id==fid,FlowRun.status=='running')):r.status='cancelled'
            model=s.get(FlowVisualModel,fid)
            if model:s.delete(model)
            s.delete(f)
        return {'ok':True}

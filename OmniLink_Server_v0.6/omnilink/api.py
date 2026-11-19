import asyncio
import hashlib
import logging
import math
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, delete
from .settings import Settings
from .db import *
from .core import Core, DomainError, obj, command_obj, METRIC
from . import auth
from .native import NativeSession, WSIO, start_listener
from .dashboards import DashboardBody, DashboardEdit, validate_widgets, dashboard_obj

class Schema(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Login(Schema):
    email:str=Field(max_length=254)
    password:str=Field(max_length=256)
class UserCreate(Login):
    role:str='operator'
class DeviceCreate(Schema):
    name:str=Field(min_length=1,max_length=120)
class DeviceEdit(Schema):
    name:str|None=Field(default=None,min_length=1,max_length=120)
    enabled:bool|None=None
class ChannelCreate(Schema):
    name:str=Field(min_length=1,max_length=80)
    type:int=Field(ge=1,le=15)
    writable:bool=True
    minimum:float|None=None
    maximum:float|None=None
class WriteBody(Schema):
    value:Any
    ttl_s:int=Field(default=30,ge=1,le=86400)
    request_id:str|None=Field(default=None,min_length=1,max_length=128)
    manual_s:int=Field(default=0,ge=0,le=86400)
class OverrideBody(Schema):
    seconds:int=Field(ge=0,le=86400)
class RuleBody(Schema):
    name:str=Field(min_length=1,max_length=120)
    metric:str=Field(max_length=32)
    op:str='gt'
    threshold:float
    channel:int=Field(ge=0,le=1023)
    value:Any
    cooldown_s:int=Field(default=60,ge=0,le=86400)
    enabled:bool=True
class ScheduleBody(Schema):
    name:str=Field(min_length=1,max_length=120)
    kind:str='interval'
    channel:int=Field(ge=0,le=1023)
    value:Any
    alternate_value:Any=None
    interval_s:int=Field(default=60,ge=1,le=604800)
    alternate_interval_s:int=Field(default=60,ge=1,le=604800)
    timezone:str='UTC'
    at:str='00:00'
    weekdays:list[int]=Field(default_factory=lambda:list(range(7)))
    enabled:bool=True
class ConnectBody(Schema):
    boot_id:str=Field(min_length=32,max_length=32)
    firmware:str=Field(default='',max_length=32)
class ReportBody(Schema):
    boot_id:str
    sequence:int=Field(ge=1,le=0xffffffff)
    channel:int=Field(ge=0,le=1023)
    type:int=Field(ge=1,le=15)
    value:Any
    observed_at_ms:int=Field(default=0,ge=0,le=0xffffffffffffffff)
    applied_command_key:str='0'*32
    desired_revision:int=Field(default=0,ge=0,le=0xffffffff)
class Metric(Schema):
    name:str
    type:int=Field(ge=1,le=15)
    value:Any
class TelemetryBody(Schema):
    boot_id:str
    sequence:int=Field(ge=1,le=0xffffffff)
    metrics:list[Metric]=Field(min_length=1,max_length=16)
    observed_at_ms:int=Field(default=0,ge=0,le=0xffffffffffffffff)
    quality:int=Field(default=0,ge=0,le=3)
class EventBody(Schema):
    boot_id:str
    sequence:int=Field(ge=1,le=0xffffffff)
    severity:int=Field(ge=0,le=4)
    code:str
    detail:str=Field(max_length=1024)
    observed_at_ms:int=Field(default=0,ge=0,le=0xffffffffffffffff)
class AckBody(Schema):
    command_key:str=Field(min_length=32,max_length=32)
    desired_revision:int=Field(ge=1,le=0xffffffff)
    status:str
    error_code:int=Field(default=0,ge=0,le=65535)

class Runtime:
    def __init__(self,settings):
        self.settings=settings
        self.db=Database(settings.database_url)
        self.core=Core(self.db,settings)
        self.native_sessions={}
        self.native_connections=set()
        self.watchers={}
        self.native_server=None
        self.mqtt=None
        self.task=None
        self.log=logging.getLogger('omnilink')
        from .flows import Engine
        self.flows=Engine(self)
        self.core.notify=self.broadcast
        self.login_attempts={}
    def broadcast(self,tenant,kind,data):
        if kind in ('report','telemetry'):self.flows.emit(tenant,kind,data)
        if hasattr(self,'loop'):
            self.loop.call_soon_threadsafe(self._broadcast,tenant,kind,data)
    def _broadcast(self,tenant,kind,data):
        for queue in tuple(self.watchers.get(tenant,set())):
            if queue.full():
                try: queue.get_nowait()
                except asyncio.QueueEmpty: pass
            queue.put_nowait({'kind':kind,'data':data})
    async def start(self):
        self.loop=asyncio.get_running_loop()
        auth.bootstrap(self.db,self.settings)
        from .platform import initialize
        initialize(self)
        if self.settings.native_enabled: self.native_server=await start_listener(self)
        if self.settings.mqtt_enabled:
            from .mqtt import MQTTAdapter
            self.mqtt=MQTTAdapter(self)
            await self.mqtt.start()
        self.task=asyncio.create_task(self.worker())
    async def stop(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        for connection in list(self.native_connections): await connection.close()
        if self.native_server:
            self.native_server.close();await self.native_server.wait_closed()
        if self.mqtt: await self.mqtt.stop()
        self.db.engine.dispose()
    async def worker(self):
        last_prune=0
        while True:
            try:
                await asyncio.to_thread(self.core.tick)
                await asyncio.to_thread(self.flows.tick)
                if now_ms()-last_prune>3600_000:
                    self.core.prune();last_prune=now_ms()
                with self.db.session() as s:
                    ids=list(s.scalars(select(Device.id).where(Device.enabled==True)))
                for device_id in ids:
                    connection=self.native_sessions.get(device_id)
                    if not connection and not (self.mqtt and self.mqtt.ready): continue
                    try: pending=self.core.pending(device_id)
                    except DomainError: continue
                    for c in pending:
                        try:
                            if connection: await connection.command(c)
                            elif not self.mqtt.send_command(device_id,c): continue
                            self.core.mark_sent(c['command_key'])
                        except Exception:
                            if connection: await connection.close()
                            self.log.info('Delivery deferred for %s',device_id)
                            break
                if self.mqtt: await self.mqtt.reconcile()
            except Exception: self.log.exception('Worker iteration failed')
            await asyncio.sleep(.5)

def create_app(settings=None):
    settings=settings or Settings.from_env()
    rt=Runtime(settings)
    @asynccontextmanager
    async def lifespan(app):
        await rt.start()
        try: yield
        finally: await rt.stop()
    app=FastAPI(title='OmniLink',version='0.5.0',lifespan=lifespan)
    app.state.runtime=rt
    from . import platform
    from .platform_api import install
    install(app,rt)
    @app.exception_handler(DomainError)
    async def domain_error(req,exc): return JSONResponse({'detail':str(exc),**({'dependencies':exc.dependencies} if hasattr(exc,'dependencies') else {})},status_code=exc.status)
    @app.middleware('http')
    async def security(req,call_next):
        if req.method in ('POST','PUT','PATCH'):
            parts=[];size=0
            async for chunk in req.stream():
                size+=len(chunk)
                if size>(1048576 if req.url.path.startswith('/api/') else 65536): return JSONResponse({'detail':'Request too large'},status_code=413)
                parts.append(chunk)
            req._body=b''.join(parts)
        response=await call_next(req)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        if req.url.path=='/' or req.url.path.startswith(('/static','/client')) or req.url.path=='/sw.js':
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; media-src 'self' blob:; worker-src 'self'; frame-ancestors 'none'"
            response.headers['Permissions-Policy']='geolocation=(self), camera=(self), microphone=(self), accelerometer=(self), gyroscope=(self), magnetometer=(self), bluetooth=(self), serial=(self)'
            response.headers['Cache-Control']='no-cache'
        if req.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
        return response
    @app.get('/health/live')
    def live(): return {'status':'ok','version':'0.5.0'}
    @app.get('/health/ready')
    def ready():
        with rt.db.session() as s: s.execute(select(1))
        return {'status':'ok','mqtt':bool(rt.mqtt and rt.mqtt.ready),'native':bool(rt.native_server)}
    @app.get('/')
    def index(): return FileResponse(Path(__file__).parent/'static'/'index.html')
    @app.get('/sw.js')
    def service_worker(): return FileResponse(Path(__file__).parent/'static'/'sw.js',media_type='text/javascript')
    app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
    # The web client is an optional, independently packaged static application.
    if settings.client_dir:
        client_path=Path(settings.client_dir).expanduser().resolve()
        if not (client_path/'index.html').is_file():
            raise RuntimeError('OMNILINK_CLIENT_DIR must point to the web client folder containing index.html')
        app.mount('/client',StaticFiles(directory=client_path,html=True),name='client')
    @app.post('/api/auth/login')
    def signin(body:Login,request:Request):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=settings.public_url.rstrip('/'): raise DomainError('Origin rejected',403)
        ip=request.client.host
        recent=[stamp for stamp in rt.login_attempts.get(ip,[]) if stamp>time.monotonic()-60]
        if len(recent)>=10: raise DomainError('Too many attempts; wait one minute',429)
        rt.login_attempts[ip]=recent+[time.monotonic()]
        if len(rt.login_attempts)>1024:
            rt.login_attempts={key:values for key,values in rt.login_attempts.items() if values and values[-1]>time.monotonic()-60}
        u,token,csrf=auth.login(rt.db,body.email,body.password)
        response=JSONResponse({'user':{'email':u.email,'role':u.role},'csrf':csrf,'token':token})
        response.set_cookie('omnilink_session',token,httponly=True,secure=settings.secure_cookie,samesite='strict',max_age=43200,path='/')
        return response
    @app.get('/api/auth/me')
    def me(request:Request):
        u=auth.user(request)
        return {'email':u.email,'role':u.role,'csrf':request.state.session.csrf,'account_id':u.tenant_id,'manager':platform.is_manager(rt,u)}
    @app.post('/api/auth/logout')
    def logout(request:Request):
        auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s: s.execute(delete(Session).where(Session.token_hash==request.state.session.token_hash))
        response=JSONResponse({'ok':True});response.delete_cookie('omnilink_session');return response
    @app.get('/api/users')
    def users(request:Request):
        u=auth.admin(request)
        with rt.db.session() as s: return [{'id':v.id,'email':v.email,'role':v.role,'enabled':v.enabled} for v in s.scalars(select(User).where(User.tenant_id==u.tenant_id))]
    @app.post('/api/users')
    def create_user(body:UserCreate,request:Request):
        u=auth.admin(request)
        if body.role not in ('admin','operator','viewer'): raise DomainError('Invalid role')
        with rt.db.lock,rt.db.session.begin() as s:
            v=auth.new_user(s,u.tenant_id,body.email,body.password,body.role)
            return {'id':v.id,'email':v.email,'role':v.role}
    @app.get('/api/devices')
    def devices(request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            return [{'id':d.id,'name':d.name,'enabled':d.enabled,'online':d.enabled and now_ms()-d.last_seen_ms<90_000,
                     'last_seen_ms':str(d.last_seen_ms),'transport':d.transport,'firmware':d.firmware,
                     'manual_until_ms':str(d.manual_until_ms),'mqtt_provisioned':bool(rt.mqtt and rt.mqtt.provisioned.get(d.id)==d.secret_cipher)}
                    for d in s.scalars(select(Device).where(Device.tenant_id==u.tenant_id).order_by(Device.created_ms))]
    @app.post('/api/devices')
    def new_device(body:DeviceCreate,request:Request):
        u=auth.admin(request)
        with rt.db.session() as s:
            if len(list(s.scalars(select(Device.id).where(Device.tenant_id==u.tenant_id))))>=platform.settings(s)['max_devices']:raise DomainError('Device limit reached')
        return rt.core.new_device(u.tenant_id,body.name)
    @app.patch('/api/devices/{device_id}')
    async def edit_device(device_id:str,body:DeviceEdit,request:Request):
        u=auth.admin(request)
        with rt.db.lock,rt.db.session.begin() as s:
            d=rt.core.device(s,device_id,u.tenant_id)
            for k,v in body.model_dump(exclude_none=True).items(): setattr(d,k,v)
            enabled=d.enabled
        if not enabled and device_id in rt.native_sessions: await rt.native_sessions[device_id].close()
        return {'ok':True}
    @app.post('/api/devices/{device_id}/rotate-secret')
    async def rotate(device_id:str,request:Request):
        u=auth.admin(request);secret=secrets.token_bytes(32)
        with rt.db.lock,rt.db.session.begin() as s:
            d=rt.core.device(s,device_id,u.tenant_id)
            d.secret_cipher=rt.core.cipher.encrypt(secret).decode()
        if device_id in rt.native_sessions: await rt.native_sessions[device_id].close()
        return {'secret':secret.hex(),'mqtt_password':secret.hex()}
    @app.get('/api/devices/{device_id}/channels')
    def channels(device_id:str,request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            rt.core.device(s,device_id,u.tenant_id)
            return [obj(c) for c in s.scalars(select(Channel).where(Channel.device_id==device_id).order_by(Channel.number))]
    @app.get('/api/devices/{device_id}/dashboards')
    def dashboards(device_id:str,request:Request):
        u=auth.user(request)
        with rt.db.session() as s:
            rt.core.device(s,device_id,u.tenant_id)
            return [dashboard_obj(row) for row in s.scalars(select(Dashboard).where(Dashboard.device_id==device_id,Dashboard.tenant_id==u.tenant_id).order_by(Dashboard.updated_ms))]
    @app.post('/api/devices/{device_id}/dashboards')
    def new_dashboard(device_id:str,body:DashboardBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id)
            rows=list(s.scalars(select(Dashboard.id).where(Dashboard.device_id==device_id)))
            if len(rows)>=12: raise DomainError('Maximum 12 dashboards per device')
            row=Dashboard(id=secrets.token_hex(16),tenant_id=u.tenant_id,device_id=device_id,
                          name=body.name,widgets=validate_widgets(rt.core,s,device_id,body.widgets))
            s.add(row);s.flush();result=dashboard_obj(row)
        rt.broadcast(u.tenant_id,'dashboard',{'device_id':device_id,'id':row.id})
        return result
    @app.put('/api/devices/{device_id}/dashboards/{dashboard_id}')
    def edit_dashboard(device_id:str,dashboard_id:str,body:DashboardEdit,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id)
            row=s.get(Dashboard,dashboard_id)
            if not row or row.device_id!=device_id or row.tenant_id!=u.tenant_id: raise DomainError('Dashboard not found',404)
            if row.revision!=body.revision: raise DomainError('Dashboard changed in another session. Reload its layout before saving.',409)
            platform.update_board(rt,s,row,validate_widgets(rt.core,s,device_id,body.widgets),body.name,body.revision)
            result=dashboard_obj(row)
        rt.broadcast(u.tenant_id,'dashboard',{'device_id':device_id,'id':dashboard_id})
        return result
    @app.delete('/api/devices/{device_id}/dashboards/{dashboard_id}')
    def delete_dashboard(device_id:str,dashboard_id:str,request:Request,revision:int):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id)
            row=s.get(Dashboard,dashboard_id)
            if not row or row.device_id!=device_id or row.tenant_id!=u.tenant_id: raise DomainError('Dashboard not found',404)
            if row.revision!=revision: raise DomainError('Dashboard changed in another session. Reload first.',409)
            refs=set().union(*(platform.widget_refs(w,row.device_id) for w in row.widgets)) if row.widgets else set()
            platform.release(s,u.tenant_id,refs,row.id)
            s.delete(row)
        rt.broadcast(u.tenant_id,'dashboard',{'device_id':device_id,'id':dashboard_id})
        return {'ok':True}
    @app.put('/api/devices/{device_id}/channels/{number}')
    def channel(device_id:str,number:int,body:ChannelCreate,request:Request):
        u=auth.admin(request)
        if not 0<=number<=1023: raise DomainError('Channel must be V0..V1023')
        if any(v is not None and not math.isfinite(v) for v in (body.minimum,body.maximum)): raise DomainError('Finite bounds required')
        if body.minimum is not None and body.maximum is not None and body.minimum>body.maximum: raise DomainError('Invalid bounds')
        with rt.db.lock,rt.db.session.begin() as s:
            rt.core.device(s,device_id,u.tenant_id)
            ch=s.get(Channel,(device_id,number))
            if ch and (ch.revision or ch.reported_ms) and ch.type!=body.type: raise DomainError('An active channel type cannot change',409)
            if not ch:
                platform.claim(s,u.tenant_id,device_id,number)
                ch=Channel(device_id=device_id,number=number);s.add(ch)
            for k,v in body.model_dump().items(): setattr(ch,k,v)
        return {'ok':True}
    @app.post('/api/devices/{device_id}/channels/{number}/write')
    def write(device_id:str,number:int,body:WriteBody,request:Request):
        u=auth.user(request)
        return rt.core.write(u.tenant_id,device_id,number,body.value,body.ttl_s,body.request_id,body.manual_s)
    @app.post('/api/devices/{device_id}/override')
    def override(device_id:str,body:OverrideBody,request:Request):
        u=auth.user(request)
        with rt.db.lock,rt.db.session.begin() as s:
            d=rt.core.device(s,device_id,u.tenant_id)
            d.manual_until_ms=now_ms()+body.seconds*1000 if body.seconds else 0
            # Entering manual mode cancels pending automation commands.
            if body.seconds:
                for c in s.scalars(select(Command).where(Command.device_id==device_id,Command.status.in_(('queued','sent','accepted')),Command.source!='manual')): c.status='superseded'
        return {'ok':True}
    def owned(request,device_id,s):
        u=auth.user(request);return rt.core.device(s,device_id,u.tenant_id)
    @app.get('/api/devices/{device_id}/commands')
    def commands(device_id:str,request:Request,limit:int=50):
        with rt.db.session() as s:
            owned(request,device_id,s)
            return [command_obj(c) for c in s.scalars(select(Command).where(Command.device_id==device_id).order_by(Command.created_ms.desc()).limit(max(1,min(limit,200))))]
    @app.get('/api/devices/{device_id}/telemetry')
    def telemetry(device_id:str,request:Request,metric:str|None=None,limit:int=100):
        with rt.db.session() as s:
            owned(request,device_id,s)
            q=select(Telemetry).where(Telemetry.device_id==device_id)
            if metric: q=q.where(Telemetry.metric==metric)
            return [obj(t) for t in s.scalars(q.order_by(Telemetry.id.desc()).limit(max(1,min(limit,1000))))]
    @app.get('/api/devices/{device_id}/events')
    def events(device_id:str,request:Request,limit:int=50):
        with rt.db.session() as s:
            owned(request,device_id,s)
            return [obj(e) for e in s.scalars(select(DeviceEvent).where(DeviceEvent.device_id==device_id).order_by(DeviceEvent.id.desc()).limit(max(1,min(limit,200))))]
    @app.get('/api/devices/{device_id}/rules')
    def rules(device_id:str,request:Request):
        with rt.db.session() as s:
            owned(request,device_id,s)
            return [obj(r) for r in s.scalars(select(Rule).where(Rule.device_id==device_id))]
    @app.post('/api/devices/{device_id}/rules')
    def new_rule(device_id:str,body:RuleBody,request:Request):
        if not METRIC.fullmatch(body.metric) or body.op not in ('gt','gte','lt','lte','eq') or not math.isfinite(body.threshold): raise DomainError('Invalid condition')
        with rt.db.lock,rt.db.session.begin() as s:
            owned(request,device_id,s)
            ch=s.get(Channel,(device_id,body.channel))
            if not ch: raise DomainError('Channel not found',404)
            data=body.model_dump();data['value']=rt.core.validate_channel_value(ch,body.value,True)
            rule=Rule(id=secrets.token_hex(16),device_id=device_id,**data);s.add(rule)
            return {'id':rule.id}
    @app.get('/api/devices/{device_id}/schedules')
    def schedules(device_id:str,request:Request):
        with rt.db.session() as s:
            owned(request,device_id,s)
            return [obj(sc) for sc in s.scalars(select(Schedule).where(Schedule.device_id==device_id))]
    @app.post('/api/devices/{device_id}/schedules')
    def new_schedule(device_id:str,body:ScheduleBody,request:Request):
        if body.kind not in ('interval','cycle','daily'): raise DomainError('Invalid schedule kind')
        if not body.weekdays or any(type(v) is not int or v not in range(7) for v in body.weekdays): raise DomainError('Invalid weekdays')
        if not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]',body.at): raise DomainError('Time must be HH:MM')
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        try: ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError: raise DomainError('Unknown timezone')
        with rt.db.lock,rt.db.session.begin() as s:
            owned(request,device_id,s)
            ch=s.get(Channel,(device_id,body.channel))
            if not ch: raise DomainError('Channel not found',404)
            data=body.model_dump();data['value']=rt.core.validate_channel_value(ch,body.value,True)
            if body.kind=='cycle': data['alternate_value']=rt.core.validate_channel_value(ch,body.alternate_value,True)
            sc=Schedule(id=secrets.token_hex(16),device_id=device_id,**data)
            sc.next_due_ms=rt.core.calendar_next(sc,now_ms()) if sc.kind=='daily' else now_ms()+sc.interval_s*1000
            s.add(sc);return {'id':sc.id,'next_due_ms':str(sc.next_due_ms)}
    @app.delete('/api/devices/{device_id}/{collection}/{item_id}')
    def remove_automation(device_id:str,collection:str,item_id:str,request:Request):
        cls={'rules':Rule,'schedules':Schedule}.get(collection)
        if not cls: raise DomainError('Not found',404)
        with rt.db.lock,rt.db.session.begin() as s:
            owned(request,device_id,s)
            row=s.get(cls,item_id)
            if not row or row.device_id!=device_id: raise DomainError('Not found',404)
            s.delete(row)
        return {'ok':True}
    # Device HTTP transport: use Authorization: Device <64 lowercase hex secret>.
    def device_schema(device_id):
        with rt.db.session() as s:
            return [{'number':c.number,'name':c.name,'type':c.type,'writable':c.writable,
                     'minimum':c.minimum,'maximum':c.maximum}
                    for c in s.scalars(select(Channel).where(Channel.device_id==device_id).order_by(Channel.number))]
    @app.get('/device/{device_id}/channels')
    def device_channels(device_id:str,request:Request):
        auth.device_user(request,device_id)
        return device_schema(device_id)
    @app.post('/device/{device_id}/connect')
    def connect(device_id:str,body:ConnectBody,request:Request):
        auth.device_user(request,device_id)
        rt.core.mark_seen(device_id,body.boot_id,'http',body.firmware)
        return {'server_time_ms':str(now_ms()),'heartbeat_s':30,'channels':device_schema(device_id)}
    @app.get('/device/{device_id}/commands')
    def poll(device_id:str,request:Request):
        d=auth.device_user(request,device_id)
        if not d.boot_id: raise DomainError('Connect first',409)
        rt.core.mark_seen(device_id,d.boot_id,'http')
        return rt.core.pending(device_id,mark=True)
    @app.post('/device/{device_id}/report')
    def report(device_id:str,body:ReportBody,request:Request):
        auth.device_user(request,device_id)
        return rt.core.report(device_id,body.boot_id,body.sequence,body.channel,body.type,body.value,body.observed_at_ms,body.applied_command_key,body.desired_revision)
    @app.post('/device/{device_id}/telemetry')
    def ingest_telemetry(device_id:str,body:TelemetryBody,request:Request):
        auth.device_user(request,device_id)
        return rt.core.telemetry(device_id,body.boot_id,body.sequence,[m.model_dump() for m in body.metrics],body.observed_at_ms,body.quality)
    @app.post('/device/{device_id}/event')
    def event(device_id:str,body:EventBody,request:Request):
        auth.device_user(request,device_id)
        return rt.core.event(device_id,body.boot_id,body.sequence,body.severity,body.code,body.detail,body.observed_at_ms)
    @app.post('/device/{device_id}/ack')
    def ack(device_id:str,body:AckBody,request:Request):
        auth.device_user(request,device_id)
        return rt.core.acknowledge(device_id,body.command_key,body.desired_revision,body.status,body.error_code)
    @app.websocket('/ws/live')
    async def live_ws(ws:WebSocket):
        token=ws.cookies.get('omnilink_session')
        try:
            u,session=auth.resolve(rt.db,token)
            if ws.headers.get('origin','').rstrip('/')!=settings.public_url.rstrip('/'): raise DomainError('Origin rejected',403)
        except DomainError:
            await ws.close(code=4401);return
        await ws.accept()
        queue=asyncio.Queue(maxsize=100)
        rt.watchers.setdefault(u.tenant_id,set()).add(queue)
        try:
            while True:
                auth.resolve(rt.db,token)
                try: data=await asyncio.wait_for(queue.get(),20)
                except asyncio.TimeoutError: data={'kind':'heartbeat','data':{}}
                await ws.send_json(data)
        except Exception: pass
        finally: rt.watchers[u.tenant_id].discard(queue)
    @app.websocket('/device/onp')
    async def device_ws(ws:WebSocket):
        await ws.accept()
        await NativeSession(rt,WSIO(ws),'wss').run()
    return app

"""Mosquitto integration; the broker enforces per-device directional ACLs."""
import asyncio
import json
import secrets
import ssl
import time
from paho.mqtt import client as mqtt
from sqlalchemy import select
from .db import Device
from .onp import strict_json_loads
from .core import DomainError

CONTROL='$CONTROL/dynamic-security/v1'
RESPONSE=CONTROL+'/response'

def acl(kind,topic): return {'acltype':kind,'topic':topic,'allow':True,'priority':10}

def device_acls(device_id):
    root=f'omnilink/v1/dev/{device_id}/'
    result=[acl('publishClientSend',root+t) for t in ('telemetry','state','event','ack','status')]
    for t in ('cmd','config'):
        result.extend([acl('subscribeLiteral',root+t),acl('publishClientReceive',root+t),acl('unsubscribeLiteral',root+t)])
    return result

class MQTTAdapter:
    def __init__(self,rt):
        self.rt=rt;self.loop=asyncio.get_running_loop()
        self.admin=None;self.client=None;self.admin_ready=False;self.ready=False
        self.provisioned={};self.enabled={};self.pending={};self.bootstrap_done=False
        self.last_reconcile=0
    def make_client(self,username,password,suffix):
        c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='omnilink-'+suffix,clean_session=True)
        c.username_pw_set(username,password)
        c.reconnect_delay_set(1,30)
        c.max_queued_messages_set(1000)
        if self.rt.settings.mqtt_ca: c.tls_set(ca_certs=self.rt.settings.mqtt_ca,tls_version=ssl.PROTOCOL_TLS_CLIENT)
        return c
    async def start(self):
        cfg=self.rt.settings
        if not cfg.mqtt_password or not cfg.mqtt_admin_password: raise RuntimeError('MQTT credentials required')
        self.admin=self.make_client(cfg.mqtt_admin_user,cfg.mqtt_admin_password,'control')
        def connected(c,u,f,reason,p):
            if reason==0: c.subscribe(RESPONSE,qos=1)
        def subscribed(c,u,mid,reasons,p):
            self.loop.call_soon_threadsafe(self._admin_connected,all(not r.is_failure for r in reasons))
        def disconnected(c,u,f,reason,p): self.loop.call_soon_threadsafe(self._admin_connected,False)
        self.admin.on_connect=connected;self.admin.on_subscribe=subscribed;self.admin.on_disconnect=disconnected
        self.admin.on_message=lambda c,u,m:self.loop.call_soon_threadsafe(self.control_reply,bytes(m.payload))
        self.admin.connect_async(cfg.mqtt_host,cfg.mqtt_port,30);self.admin.loop_start()
    def _admin_connected(self,ready):
        self.admin_ready=ready
        if ready:
            self.bootstrap_done=False;self.provisioned.clear();self.enabled.clear()
    async def control(self,command,allow_existing=False,**data):
        if not self.admin_ready: raise RuntimeError('Broker administration offline')
        correlation=secrets.token_hex(12)
        future=self.loop.create_future();self.pending[correlation]=future
        payload=json.dumps({'commands':[{'command':command,'correlationData':correlation,**data}]})
        try:
            info=self.admin.publish(CONTROL,payload,qos=1,retain=False)
            if info.rc: raise RuntimeError('Broker publish failed')
            response=await asyncio.wait_for(future,5)
            error=response.get('error')
            if error and not (allow_existing and 'already exists' in error.lower()): raise RuntimeError(f'Broker control {command} failed: {error}')
            return response
        finally: self.pending.pop(correlation,None)
    def control_reply(self,payload):
        try:
            for response in strict_json_loads(payload).get('responses',[]):
                future=self.pending.get(response.get('correlationData'))
                if future and not future.done(): future.set_result(response)
        except Exception: self.rt.log.warning('Malformed broker control reply')
    async def reconcile(self):
        if not self.admin_ready or time.monotonic()-self.last_reconcile<2: return
        self.last_reconcile=time.monotonic()
        try:
            if not self.bootstrap_done:
                await self.control('setDefaultACLAccess',acls=[{'acltype':t,'allow':False} for t in ('publishClientSend','publishClientReceive','subscribe','unsubscribe')])
                name='omnilink-service'
                acls=[acl('publishClientSend','omnilink/v1/dev/+/cmd'),acl('publishClientSend','omnilink/v1/dev/+/config')]
                for t in ('telemetry','state','event','ack','status'):
                    topic='omnilink/v1/dev/+/'+t
                    acls.extend([acl('subscribeLiteral',topic),acl('publishClientReceive',topic),acl('unsubscribeLiteral',topic)])
                await self.control('createRole',True,rolename=name,acls=acls)
                await self.control('modifyRole',rolename=name,acls=acls)
                await self.control('createClient',True,username=self.rt.settings.mqtt_user,password=self.rt.settings.mqtt_password,roles=[{'rolename':name,'priority':10}])
                await self.control('setClientPassword',username=self.rt.settings.mqtt_user,password=self.rt.settings.mqtt_password)
                await self.control('modifyClient',username=self.rt.settings.mqtt_user,roles=[{'rolename':name,'priority':10}],groups=[])
                self.bootstrap_done=True
                if self.client is None: self.start_data_client()
            from .platform_models import Account
            with self.rt.db.session() as s:
                devices=list(s.scalars(select(Device)))
                disabled_accounts=set(s.scalars(select(Account.tenant_id).where(Account.enabled==False)))
            for removed in set(self.provisioned)-{d.id for d in devices}:
                await self.control('deleteClient',True,username=removed)
                await self.control('deleteRole',True,rolename='device-'+removed)
                self.provisioned.pop(removed,None);self.enabled.pop(removed,None)
            for d in devices:
                effective_enabled=d.enabled and d.tenant_id not in disabled_accounts
                if self.provisioned.get(d.id)==d.secret_cipher and self.enabled.get(d.id)==effective_enabled: continue
                role='device-'+d.id;acls=device_acls(d.id)
                await self.control('createRole',True,rolename=role,acls=acls)
                await self.control('modifyRole',rolename=role,acls=acls)
                await self.control('createClient',True,username=d.id,password=self.rt.core.secret(d).hex(),clientid=d.id,roles=[{'rolename':role,'priority':10}])
                await self.control('setClientPassword',username=d.id,password=self.rt.core.secret(d).hex())
                await self.control('modifyClient',username=d.id,clientid=d.id,roles=[{'rolename':role,'priority':10}],groups=[])
                await self.control('enableClient' if effective_enabled else 'disableClient',username=d.id)
                self.provisioned[d.id]=d.secret_cipher;self.enabled[d.id]=effective_enabled
        except Exception as exc:
            self.rt.log.warning('MQTT provisioning deferred: %s',str(exc))
    def start_data_client(self):
        cfg=self.rt.settings
        self.client=self.make_client(cfg.mqtt_user,cfg.mqtt_password,'service')
        def connected(c,u,f,reason,p):
            if reason==0:
                c.subscribe([('omnilink/v1/dev/+/'+t,1) for t in ('telemetry','state','event','ack','status')])
        def subscribed(c,u,mid,reasons,p): self.loop.call_soon_threadsafe(self.set_ready,all(not r.is_failure for r in reasons))
        def disconnected(c,u,f,reason,p): self.loop.call_soon_threadsafe(self.set_ready,False)
        self.client.on_connect=connected;self.client.on_subscribe=subscribed;self.client.on_disconnect=disconnected
        self.client.on_message=lambda c,u,m:self.loop.call_soon_threadsafe(self.message,m.topic,bytes(m.payload),m.retain)
        self.client.connect_async(cfg.mqtt_host,cfg.mqtt_port,30);self.client.loop_start()
    def set_ready(self,value): self.ready=value
    def send_command(self,device_id,c):
        if not self.ready or not self.enabled.get(device_id): return False
        info=self.client.publish(f'omnilink/v1/dev/{device_id}/cmd',json.dumps(c,separators=(',',':')),qos=1,retain=False)
        return info.rc==mqtt.MQTT_ERR_SUCCESS
    def message(self,topic,payload,retained=False):
        try:
            if len(payload)>8192: raise DomainError('MQTT payload too large')
            parts=topic.split('/')
            if len(parts)!=5 or parts[:3]!=['omnilink','v1','dev']: raise DomainError('Unexpected topic')
            device_id,kind=parts[3:]
            data=strict_json_loads(payload)
            if not isinstance(data,dict): raise DomainError('Object required')
            with self.rt.db.session() as s: self.rt.core.device(s,device_id,enabled=True)
            # Retained state/status is advisory and must not replay commands or trigger rules.
            if retained: return
            from .api import ReportBody,TelemetryBody,EventBody,AckBody,ConnectBody
            if kind=='status':
                if data.get('online') is True:
                    connect=ConnectBody.model_validate({k:v for k,v in data.items() if k!='online'})
                    self.rt.core.mark_seen(device_id,connect.boot_id,'mqtt',connect.firmware)
            elif kind=='state':
                r=ReportBody.model_validate(data)
                self.rt.core.report(device_id,r.boot_id,r.sequence,r.channel,r.type,r.value,r.observed_at_ms,r.applied_command_key,r.desired_revision)
            elif kind=='telemetry':
                if 'metrics' not in data:
                    self.rt.core.plain_telemetry(device_id,data);return
                r=TelemetryBody.model_validate(data)
                self.rt.core.telemetry(device_id,r.boot_id,r.sequence,[m.model_dump() for m in r.metrics],r.observed_at_ms,r.quality)
            elif kind=='event':
                r=EventBody.model_validate(data)
                self.rt.core.event(device_id,r.boot_id,r.sequence,r.severity,r.code,r.detail,r.observed_at_ms)
            elif kind=='ack':
                r=AckBody.model_validate(data)
                self.rt.core.acknowledge(device_id,r.command_key,r.desired_revision,r.status,r.error_code)
        except Exception as exc:
            self.rt.log.warning('MQTT message rejected on %s (%s)',topic,type(exc).__name__)
    async def stop(self):
        for c in (self.client,self.admin):
            if c: c.disconnect();await asyncio.to_thread(c.loop_stop)

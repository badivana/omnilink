"""Transactional state, durable commands, and transport-independent ingestion."""
import base64
import hashlib
import hmac
import json
import math
import operator
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet
from sqlalchemy import select, delete
from .db import *
from .onp import Type, encode_value, ProtocolError

ACTIVE = ('queued', 'sent', 'accepted')
METRIC = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
HEX32 = re.compile(r'^[0-9a-f]{32}$')

class DomainError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def typed_value(kind, value):
    """Validate wire range and round FLOAT32 exactly as the wire does."""
    from .onp import decode_value
    try:
        if int(kind) == Type.BYTES:
            value = base64.b64decode(value, validate=True)
        if int(kind) in (Type.INT64, Type.UINT64, Type.TIMESTAMP) and isinstance(value, str):
            if not re.fullmatch(r'-?(0|[1-9][0-9]*)', value):
                raise ValueError('invalid decimal')
            value = int(value)
        raw = encode_value(kind, value)
        if len(raw) > 2048:
            raise ValueError('Value exceeds 2048 bytes')
        value = decode_value(raw)[1]
        if int(kind) == Type.BYTES:
            value = base64.b64encode(value).decode()
        if int(kind) in (Type.INT64, Type.UINT64, Type.TIMESTAMP):
            value = str(value)
        return value
    except (ProtocolError, ValueError, TypeError) as exc:
        raise DomainError('Invalid typed value') from exc

def wire_value(kind, value):
    if int(kind) == Type.BYTES:
        return base64.b64decode(value)
    if int(kind) in (Type.INT64, Type.UINT64, Type.TIMESTAMP):
        return int(value)
    return value

def obj(row):
    return {col.name: getattr(row, col.name) for col in row.__table__.columns}

def command_obj(c):
    return {'command_key': c.key, 'channel': c.channel, 'desired_revision': c.revision,
            'type': c.type, 'value': c.value, 'expires_at_ms': str(c.expires_ms),
            'status': c.status, 'source': c.source, 'attempts': c.attempts,
            'created_at_ms': str(c.created_ms), 'error_code': c.error_code}

class Core:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.cipher = Fernet(settings.encryption_key.encode())
        self.notify = lambda tenant, kind, data: None

    def secret(self, device):
        return self.cipher.decrypt(device.secret_cipher.encode())

    def device(self, s, device_id, tenant=None, enabled=False):
        d = s.get(Device, device_id)
        if not d or (tenant is not None and d.tenant_id != tenant):
            raise DomainError('Device not found', 404)
        from .platform_models import Account
        account=s.get(Account,d.tenant_id)
        if enabled and account and not account.enabled:raise DomainError('Account disabled',403)
        if enabled and not d.enabled:
            raise DomainError('Device disabled', 403)
        return d

    def authenticate_device(self, device_id, token):
        with self.db.lock, self.db.session() as s:
            d = self.device(s, device_id, enabled=True)
            try:
                candidate = bytes.fromhex(token)
            except (ValueError, TypeError):
                candidate = b''
            if not hmac.compare_digest(self.secret(d), candidate):
                raise DomainError('Invalid device credentials', 401)
            return d

    def new_device(self, tenant, name):
        device_id, secret = 'dev_' + secrets.token_hex(10), secrets.token_bytes(32)
        with self.db.lock, self.db.session.begin() as s:
            from .platform import settings
            if len(list(s.scalars(select(Device.id).where(Device.tenant_id==tenant))))>=settings(s)['max_devices']:raise DomainError('Device limit reached')
            d = Device(id=device_id, tenant_id=tenant, name=name,
                       secret_cipher=self.cipher.encrypt(secret).decode())
            s.add(d)
        return {'id': device_id, 'name': name, 'secret': secret.hex(),
                'mqtt_username': device_id, 'mqtt_password': secret.hex(),
                'mqtt_topic_root': f'omnilink/v1/dev/{device_id}'}

    def validate_channel_value(self, ch, value, write=False):
        if write and not ch.writable:
            raise DomainError('Channel is read-only')
        value = typed_value(ch.type, value)
        if ch.minimum is not None and (not isinstance(value,(int,float)) or value < ch.minimum):
            raise DomainError('Value below channel minimum')
        if ch.maximum is not None and (not isinstance(value,(int,float)) or value > ch.maximum):
            raise DomainError('Value above channel maximum')
        return value

    def _write(self, s, d, number, value, source, ttl_s=30, request_id=None, manual_s=0):
        from .platform_models import PinLease,Account
        account=s.get(Account,d.tenant_id)
        lease=s.get(PinLease,(d.tenant_id,number))
        if (account and not account.enabled) or (lease and lease.device_id!=d.id):
            if source!='manual':return None
            raise DomainError('Account disabled or pin allocation conflict. Resolve it before sending commands.',409)
        ch = s.get(Channel, (d.id, number))
        if ch is None:
            raise DomainError('Channel not found',404)
        value = self.validate_channel_value(ch, value, write=True)
        if request_id:
            old = s.scalar(select(Command).where(Command.device_id==d.id,Command.request_id==request_id))
            if old:
                if old.channel != number or old.value != value:
                    raise DomainError('Idempotency key reused with different command',409)
                return old
        if source != 'manual' and d.manual_until_ms > now_ms():
            return None
        if source == 'manual' and manual_s:
            d.manual_until_ms = now_ms()+manual_s*1000
            for old in s.scalars(select(Command).where(Command.device_id==d.id,Command.status.in_(ACTIVE),Command.source!='manual')):
                old.status='superseded'
        if ch.revision >= 0xffffffff:
            raise DomainError('Revision exhausted; reprovision channel',409)
        for old in s.scalars(select(Command).where(Command.device_id==d.id,Command.channel==number,Command.status.in_(ACTIVE))):
            old.status = 'superseded'
        ch.revision += 1
        ch.desired = value
        c = Command(key=secrets.token_hex(16),device_id=d.id,channel=number,revision=ch.revision,
                    type=ch.type,value=value,source=source,request_id=request_id,
                    expires_ms=now_ms()+ttl_s*1000)
        s.add(c)
        s.flush()
        return c

    def write(self, tenant, device_id, number, value, ttl_s=30, request_id=None, manual_s=0):
        with self.db.lock, self.db.session.begin() as s:
            d = self.device(s,device_id,tenant,enabled=True)
            c = self._write(s,d,number,value,'manual',ttl_s,request_id,manual_s)
            result = command_obj(c)
        self.notify(d.tenant_id,'command',{'device_id':device_id,**result})
        return result

    def mark_seen(self, device_id, boot_id, transport, firmware=''):
        if not HEX32.fullmatch(boot_id) or boot_id == '0'*32:
            raise DomainError('boot_id must be a nonzero 32-character lowercase hex ID')
        with self.db.lock, self.db.session.begin() as s:
            d = self.device(s,device_id,enabled=True)
            d.last_seen_ms, d.boot_id, d.transport = now_ms(),boot_id,transport
            if firmware:
                d.firmware = firmware[:32]

    def pending(self, device_id, mark=False):
        result=[]
        with self.db.lock, self.db.session.begin() as s:
            d = self.device(s,device_id,enabled=True)
            current=now_ms()
            for c in s.scalars(select(Command).where(Command.device_id==device_id,Command.status.in_(ACTIVE)).order_by(Command.created_ms)):
                from .platform_models import PinLease
                lease=s.get(PinLease,(d.tenant_id,c.channel))
                if lease and lease.device_id!=device_id:
                    c.status='superseded'
                    continue
                if c.expires_ms <= current:
                    c.status='expired'
                    continue
                if c.next_attempt_ms > current:
                    continue
                result.append(command_obj(c))
                if mark:
                    c.attempts+=1
                    c.next_attempt_ms=current+int(self.settings.retry_seconds*1000)
                    if c.status=='queued':
                        c.status='sent'
        return result

    def mark_sent(self, key):
        with self.db.lock, self.db.session.begin() as s:
            c=s.get(Command,key)
            if c and c.status in ACTIVE:
                c.attempts+=1
                c.next_attempt_ms=now_ms()+int(self.settings.retry_seconds*1000)
                if c.status=='queued': c.status='sent'

    def _ack(self,s,d,key,revision,status,error=0):
        c=s.get(Command,key)
        if not c or c.device_id!=d.id or c.revision!=revision:
            raise DomainError('Command key/revision does not belong to this device',409)
        if status not in ('accepted','applied','rejected') or type(error) is not int or not 0<=error<=65535:
            raise DomainError('Invalid acknowledgment')
        if (status=='rejected') != (error!=0):
            raise DomainError('Rejected requires a nonzero error; success requires zero')
        if c.status in ACTIVE:
            c.status=status
            c.error_code=error
            if status=='applied': c.applied_ms=now_ms()
        return c

    def acknowledge(self,device_id,key,revision,status,error=0):
        with self.db.lock,self.db.session.begin() as s:
            d=self.device(s,device_id,enabled=True)
            c=self._ack(s,d,key,revision,status,error)
            d.last_seen_ms=now_ms()
            result=command_obj(c)
        self.notify(d.tenant_id,'command',{'device_id':device_id,**result})
        return result

    def _receipt(self,s,d,boot,kind,sequence):
        if type(sequence) is not int or not 1<=sequence<=0xffffffff:
            raise DomainError('sequence must be 1..4294967295')
        if not HEX32.fullmatch(boot) or boot=='0'*32:
            raise DomainError('Invalid boot_id')
        if s.get(Receipt,(d.id,boot,kind,sequence)):
            return False
        s.add(Receipt(device_id=d.id,boot_id=boot,kind=kind,sequence=sequence))
        d.last_seen_ms=now_ms()
        return True

    def report(self,device_id,boot,sequence,number,kind,value,observed=0,key='0'*32,revision=0):
        with self.db.lock,self.db.session.begin() as s:
            d=self.device(s,device_id,enabled=True)
            ch=s.get(Channel,(device_id,number))
            if ch is None or ch.type!=kind:
                raise DomainError('Unknown channel or type mismatch')
            value=self.validate_channel_value(ch,value)
            if (key=='0'*32) != (revision==0):
                raise DomainError('Report command key/revision mismatch')
            if not HEX32.fullmatch(key):
                raise DomainError('Invalid command key')
            # A late prior-boot report never replaces the current connection's state.
            if d.boot_id and d.boot_id!=boot:
                raise DomainError('Stale boot; establish a device connection first',409)
            if not self._receipt(s,d,boot,'report',sequence): return {'duplicate':True}
            if key!='0'*32:
                c=s.get(Command,key)
                if not c or c.device_id!=d.id or c.channel!=number or c.revision!=revision or c.value!=value:
                    raise DomainError('Applied report does not match command',409)
                self._ack(s,d,key,revision,'applied')
            if ch.reported_boot!=boot or sequence>ch.reported_seq:
                ch.reported, ch.reported_revision, ch.reported_ms=value,revision,now_ms()
                ch.reported_boot,ch.reported_seq=boot,sequence
            result={'device_id':device_id,'channel':number,'value':value,'type':kind,'desired_revision':revision}
        self.notify(d.tenant_id,'report',result)
        return {'duplicate':False}

    def telemetry(self,device_id,boot,sequence,metrics,observed=0,quality=0):
        if not 1<=len(metrics)<=16 or quality not in (0,1,2,3):
            raise DomainError('Invalid telemetry count/quality')
        normalized=[]
        seen=set()
        for m in metrics:
            if not METRIC.fullmatch(m['name']) or m['name'] in seen:
                raise DomainError('Invalid/duplicate metric name')
            seen.add(m['name'])
            normalized.append({**m,'value':typed_value(m['type'],m['value'])})
        with self.db.lock,self.db.session.begin() as s:
            d=self.device(s,device_id,enabled=True)
            if d.boot_id and d.boot_id!=boot: raise DomainError('Stale boot',409)
            if not self._receipt(s,d,boot,'telemetry',sequence): return {'duplicate':True}
            for m in normalized:
                s.add(Telemetry(device_id=device_id,metric=m['name'],type=m['type'],value=m['value'],observed_ms=observed,quality=quality))
                if quality==0: self._rules(s,d,m)
        self.notify(d.tenant_id,'telemetry',{'device_id':device_id,'metrics':normalized,'received_at_ms':str(now_ms())})
        return {'duplicate':False}

    def event(self,device_id,boot,sequence,severity,code,detail,observed=0):
        if severity not in range(5) or not re.fullmatch(r'[A-Z0-9_]{1,32}',code) or len(detail.encode())>1024:
            raise DomainError('Invalid event')
        with self.db.lock,self.db.session.begin() as s:
            d=self.device(s,device_id,enabled=True)
            if d.boot_id and d.boot_id!=boot: raise DomainError('Stale boot',409)
            if not self._receipt(s,d,boot,'event',sequence): return {'duplicate':True}
            s.add(DeviceEvent(device_id=device_id,severity=severity,code=code,detail=detail,observed_ms=observed))
        self.notify(d.tenant_id,'event',{'device_id':device_id,'code':code,'detail':detail})
        return {'duplicate':False}

    def plain_telemetry(self,device_id,values):
        """SDK-free flat MQTT metrics: no packet deduplication is promised."""
        if not 1<=len(values)<=16: raise DomainError('Send 1..16 metrics')
        metrics=[]
        for name,value in values.items():
            if not METRIC.fullmatch(name): raise DomainError('Invalid metric name')
            kind=1 if type(value) is bool else 11 if type(value) in (int,float) else 12 if type(value) is str else 14
            metrics.append({'name':name,'type':kind,'value':typed_value(kind,value)})
        with self.db.lock,self.db.session.begin() as s:
            d=self.device(s,device_id,enabled=True);d.last_seen_ms=now_ms();d.transport='mqtt'
            for m in metrics:
                s.add(Telemetry(device_id=device_id,metric=m['name'],value=m['value'],type=m['type'],observed_ms=0,quality=0))
                self._rules(s,d,m)
        self.notify(d.tenant_id,'telemetry',{'device_id':device_id,'metrics':metrics,'received_at_ms':str(now_ms())})
        return {'deduplicated':False}

    def _rules(self,s,d,m):
        ops={'gt':operator.gt,'gte':operator.ge,'lt':operator.lt,'lte':operator.le,'eq':operator.eq}
        if type(m['value']) not in (int,float): return
        for r in s.scalars(select(Rule).where(Rule.device_id==d.id,Rule.metric==m['name'],Rule.enabled==True)):
            active=ops[r.op](m['value'],r.threshold)
            if active and not r.active and now_ms()>=r.last_trigger_ms+r.cooldown_s*1000:
                c=self._write(s,d,r.channel,r.value,'rule')
                if c: r.last_trigger_ms=now_ms()
            r.active=active

    @staticmethod
    def calendar_next(sc, after):
        zone=ZoneInfo(sc.timezone)
        local=datetime.fromtimestamp(after/1000,timezone.utc).astimezone(zone)
        h,m=map(int,sc.at.split(':'))
        for offset in range(9):
            date=local.date()+timedelta(days=offset)
            if date.weekday() not in sc.weekdays: continue
            candidate=datetime(date.year,date.month,date.day,h,m,tzinfo=zone,fold=0)
            stamp=int(candidate.timestamp()*1000)
            # Skip nonexistent wall-clock times; fall-back hour fires once.
            if datetime.fromtimestamp(stamp/1000,zone).replace(tzinfo=None)!=candidate.replace(tzinfo=None): continue
            if stamp>after: return stamp
        raise DomainError('No calendar occurrence')

    def tick(self):
        current=now_ms()
        with self.db.lock,self.db.session.begin() as s:
            for c in s.scalars(select(Command).where(Command.status.in_(ACTIVE),Command.expires_ms<=current)):
                c.status='expired'
            for sc in s.scalars(select(Schedule).where(Schedule.enabled==True,Schedule.next_due_ms<=current)):
                d=self.device(s,sc.device_id)
                if not d.enabled: continue
                due=sc.next_due_ms
                value=sc.alternate_value if sc.kind=='cycle' and sc.phase else sc.value
                # No catch-up burst after downtime; stale occurrences are skipped.
                if current-due<30_000:
                    self._write(s,d,sc.channel,value,'schedule',request_id=f'schedule:{sc.id}:{due}')
                if sc.kind=='daily': sc.next_due_ms=self.calendar_next(sc,current)
                elif sc.kind=='cycle':
                    period=(sc.interval_s+sc.alternate_interval_s)*1000
                    if current-due>=30_000:
                        cycles=max(0,(current-due)//period)
                        due+=cycles*period
                        while due<=current:
                            duration=sc.alternate_interval_s if sc.phase else sc.interval_s
                            sc.phase=1-sc.phase
                            due+=duration*1000
                        sc.next_due_ms=due
                    else:
                        duration=sc.alternate_interval_s if sc.phase else sc.interval_s
                        sc.phase=1-sc.phase
                        sc.next_due_ms=due+duration*1000
                else: sc.next_due_ms=due+((max(0,current-due)//(sc.interval_s*1000))+1)*sc.interval_s*1000

    def prune(self):
        cut=now_ms()-self.settings.retention_days*86400_000
        with self.db.lock,self.db.session.begin() as s:
            for cls in (Telemetry,DeviceEvent,Receipt):
                s.execute(delete(cls).where(cls.received_ms<cut))
            s.execute(delete(Session).where(Session.expires_ms<now_ms()))
            from .platform_models import FlowRun,Alert
            s.execute(delete(FlowRun).where(FlowRun.created_ms<cut,FlowRun.status!='running'))
            s.execute(delete(Alert).where(Alert.created_ms<cut,Alert.acknowledged==True))

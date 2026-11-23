"""Bounded ONP v1 compact codec over TLS and binary WebSocket."""
import asyncio
import secrets
import ssl
import struct
import re
from . import onp
from .core import DomainError, wire_value
from .db import Channel, Device, now_ms
from sqlalchemy import select

class Cursor:
    def __init__(self,data): self.data,self.i=data,0
    def take(self,n):
        if self.i+n>len(self.data): raise onp.ProtocolError('Truncated payload')
        v=self.data[self.i:self.i+n];self.i+=n;return v
    def u(self,n): return int.from_bytes(self.take(n),'big')
    def text(self,n=1,maximum=64):
        size=self.u(n)
        if size>maximum: raise onp.ProtocolError('String too long')
        return self.take(size).decode('utf8')
    def done(self):
        if self.i!=len(self.data): raise onp.ProtocolError('Trailing payload')

def text8(value):
    raw=value.encode();return bytes([len(raw)])+raw

class TCPIO:
    def __init__(self,reader,writer): self.reader,self.writer=reader,writer
    async def receive(self,limit,timeout):
        header=await asyncio.wait_for(self.reader.readexactly(20),timeout)
        fields=onp._header_fields(header,limit)
        body=await asyncio.wait_for(self.reader.readexactly(fields[3]),min(timeout,10))
        return onp.decode_frame(header+body,limit)
    async def send(self,frame,limit):
        self.writer.write(onp.encode_frame(frame,limit))
        await asyncio.wait_for(self.writer.drain(),5)
    async def close(self):
        self.writer.close()
        try: await self.writer.wait_closed()
        except (OSError,ssl.SSLError): pass

class WSIO:
    def __init__(self,ws): self.ws=ws
    async def receive(self,limit,timeout):
        data=await asyncio.wait_for(self.ws.receive_bytes(),timeout)
        return onp.decode_frame(data,limit)
    async def send(self,frame,limit): await asyncio.wait_for(self.ws.send_bytes(onp.encode_frame(frame,limit)),5)
    async def close(self):
        try: await self.ws.close()
        except RuntimeError: pass

class NativeSession:
    def __init__(self,runtime,io,transport='onp'):
        self.rt,self.io,self.transport=runtime,io,transport
        self.sid,self.limit,self.heartbeat=0,256,30
        self.device_id,self.boot='', ''
        self.mid=secrets.randbelow(0xfffffffe)+1
        self.command_mids={}
        self.send_lock=asyncio.Lock()
        self.closed=False
        self.caps,self.types=0,0
    def next_mid(self):
        self.mid=self.mid%0xffffffff+1
        return self.mid
    async def send(self,kind,payload=b'',mid=None,flags=0):
        async with self.send_lock:
            await self.io.send(onp.Frame(kind,mid or self.next_mid(),self.sid,payload,flags),self.limit)
    async def command(self,c):
        if not self.caps&2 or not self.types&(1<<(c['type']-1)):
            self.rt.core.acknowledge(self.device_id,c['command_key'],c['desired_revision'],'rejected',415)
            return
        if len(self.command_mids)>2048: raise onp.ProtocolError('Session command limit; reconnect')
        old=self.command_mids.get(c['command_key'])
        mid=old or self.next_mid()
        self.command_mids[c['command_key']]=mid
        payload=onp.encode_write(onp.Write(bytes.fromhex(c['command_key']),c['desired_revision'],int(c['expires_at_ms']),c['channel'],onp.Type(c['type']),wire_value(c['type'],c['value'])))
        if len(payload)+20>self.limit:
            self.rt.core.acknowledge(self.device_id,c['command_key'],c['desired_revision'],'rejected',413)
            return
        await self.send(0x10,payload,mid,onp.ACK_REQUESTED|(onp.RETRANSMISSION if old else 0))
    async def run(self):
        if len(self.rt.native_connections)>=256:
            await self.close();return
        self.rt.native_connections.add(self)
        try:
            hello=await self.io.receive(256,10)
            if hello.type!=1 or hello.codec or hello.session_id or hello.flags:
                raise onp.ProtocolError('HELLO required')
            p=Cursor(hello.payload)
            device_id=p.text();role=p.u(1);firmware=p.text(maximum=32)
            codecs=p.u(1);caps=p.u(4);types=p.u(4);maximum=p.u(4);heartbeat=p.u(2)
            p.take(16);boot=p.take(16).hex();p.done()
            if role not in (0,1) or not codecs&1 or not 256<=maximum<=65536 or caps&~0x3f or types&~0x7fff:
                raise onp.ProtocolError('Unsupported HELLO negotiation')
            self.limit=min(maximum,4096);self.heartbeat=max(10,min(heartbeat or 30,120))
            self.caps,self.types=caps,types
            ack=struct.pack('>BIIIHB',0,caps&0x3f,types&0x7fff,self.limit,self.heartbeat,1)
            await self.send(2,ack,hello.message_id,onp.RESPONSE)
            nonce=secrets.token_bytes(32);challenge_mid=self.next_mid()
            await self.send(4,nonce+struct.pack('>H',10),challenge_mid)
            response=await self.io.receive(256,10)
            p=Cursor(response.payload);method=p.u(1);proof=p.take(p.u(2));p.done()
            if response.type!=5 or response.codec or response.session_id or response.flags!=onp.RESPONSE or response.message_id!=challenge_mid or method!=1:
                raise onp.ProtocolError('Invalid authentication response')
            with self.rt.db.session() as s:
                d=self.rt.core.device(s,device_id,enabled=True)
                secret=self.rt.core.secret(d)
            if not onp.verify_auth(secret,hello.payload,ack,nonce,proof): raise DomainError('Authentication failed',401)
            self.rt.core.mark_seen(device_id,boot,self.transport,firmware)
            self.device_id,self.boot=device_id,boot
            self.sid=secrets.randbelow(0xffffffff)+1
            previous=self.rt.native_sessions.get(device_id)
            if previous: await previous.close()
            self.rt.native_sessions[device_id]=self
            await self.send(6,struct.pack('>QI',now_ms(),1000))
            while not self.closed:
                f=await self.io.receive(self.limit,self.heartbeat*2.5)
                if f.session_id!=self.sid or f.codec!=0:
                    raise onp.ProtocolError('Session/codec mismatch')
                await self.handle(f)
                self.rt.core.mark_seen(device_id,boot,self.transport)
        except (asyncio.TimeoutError,asyncio.IncompleteReadError,ConnectionError,OSError,UnicodeError,onp.ProtocolError,DomainError) as exc:
            if not self.sid:
                try: await self.send(7,struct.pack('>H',1)+text8('Connection rejected'))
                except Exception: pass
            else:
                self.rt.log.info('ONP connection closed for %s (%s)',self.device_id,type(exc).__name__)
        except Exception as exc:
            from starlette.websockets import WebSocketDisconnect
            if not isinstance(exc,WebSocketDisconnect): self.rt.log.exception('ONP connection error')
        finally: await self.close()
    async def close(self):
        self.closed=True
        self.rt.native_connections.discard(self)
        if self.rt.native_sessions.get(self.device_id) is self: self.rt.native_sessions.pop(self.device_id,None)
        await self.io.close()
    async def handle(self,f):
        if f.type==8:
            if f.payload or f.flags: raise onp.ProtocolError('Invalid PING')
            await self.send(9,mid=f.message_id,flags=onp.RESPONSE);return
        if f.type==0x60:
            if len(f.payload)!=8 or f.flags: raise onp.ProtocolError('Invalid time request')
            received=now_ms()
            await self.send(0x61,f.payload+struct.pack('>QQI',received,now_ms(),1000),f.message_id,onp.RESPONSE);return
        if f.type in (0x80,0x81):
            a=onp.decode_ack(f.payload);key=a.command_key.hex()
            if not f.flags&onp.RESPONSE or self.command_mids.get(key)!=f.message_id or (f.type==0x81)!=(a.status==2):
                raise onp.ProtocolError('ACK correlation mismatch')
            self.rt.core.acknowledge(self.device_id,key,a.revision,('accepted','applied','rejected')[a.status],a.error_code);return
        if f.type==0x13:
            r=onp.decode_report(f.payload)
            self.rt.core.report(self.device_id,self.boot,r.sequence,r.channel,int(r.type),
                                self.json_value(r.type,r.value),r.observed_at_ms,r.applied_command_key.hex(),r.desired_revision)
        elif f.type==0x20:
            p=Cursor(f.payload);seq=p.u(4);observed=p.u(8);quality=p.u(1);count=p.u(2)
            if not 1<=count<=16: raise onp.ProtocolError('Bad telemetry count')
            metrics=[]
            for _ in range(count):
                name=p.text(maximum=32)
                kind,value,end=onp.decode_value(p.data,p.i);p.i=end
                metrics.append({'name':name,'type':int(kind),'value':self.json_value(kind,value)})
            p.done();self.rt.core.telemetry(self.device_id,self.boot,seq,metrics,observed,quality)
        elif f.type==0x21:
            p=Cursor(f.payload);seq=p.u(4);observed=p.u(8);severity=p.u(1);code=p.text(maximum=32);detail=p.text(2,1024);p.done()
            self.rt.core.event(self.device_id,self.boot,seq,severity,code,detail,observed)
        elif f.type==0x12:
            if len(f.payload)!=4: raise onp.ProtocolError('Invalid VSYNC')
            first,count=struct.unpack('>HH',f.payload)
            if not 1<=count<=16 or first+count>1024: raise onp.ProtocolError('Invalid VSYNC range')
            with self.rt.db.lock,self.rt.db.session.begin() as s:
                d=self.rt.core.device(s,self.device_id,enabled=True)
                for ch in s.scalars(select(Channel).where(Channel.device_id==d.id,Channel.number>=first,Channel.number<first+count)):
                    if ch.desired is not None and ch.writable:
                        # A desired value made invalid by a later bounds change is skipped, not fatal.
                        try: self.rt.core._write(s,d,ch.number,ch.desired,'sync')
                        except DomainError: pass
        else: raise onp.ProtocolError('Unsupported message type')
        if f.flags&onp.ACK_REQUESTED or f.type==0x12:
            await self.send(0x80,onp.encode_ack(onp.Ack(bytes(16),0,0)),f.message_id,onp.RESPONSE)
    @staticmethod
    def json_value(kind,value):
        import base64
        if kind==onp.Type.BYTES: return base64.b64encode(value).decode()
        if kind in (onp.Type.INT64,onp.Type.UINT64,onp.Type.TIMESTAMP): return str(value)
        return value

async def start_listener(runtime):
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(runtime.settings.tls_cert,runtime.settings.tls_key)
    async def accepted(reader,writer):
        if len(runtime.native_sessions)>=256:
            writer.close();return
        await NativeSession(runtime,TCPIO(reader,writer)).run()
    return await asyncio.start_server(accepted,runtime.settings.native_host,runtime.settings.native_port,ssl=ctx,ssl_handshake_timeout=10,limit=8192)

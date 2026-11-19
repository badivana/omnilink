"""A real network device simulator: HTTP, ONP TLS, or MQTT TLS."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import secrets
import ssl
import struct
import time
import httpx
from omnilink import onp
from omnilink.core import wire_value, typed_value
from omnilink.db import now_ms
from omnilink.native import TCPIO,text8

def checked(response,channel=None):
    if response.is_error:
        try: detail=response.json().get('detail','Request rejected')
        except (ValueError,AttributeError): detail='Request rejected (non-JSON response)'
        label='' if channel is None else f' for V{channel}'
        raise RuntimeError(f'{response.request.method} {response.request.url.path}{label}: HTTP {response.status_code}: {detail}')
    return response.json()

class Simulator:
    """General-purpose simulated device. Initial values are neutral, bounded values.

    Discovery describes channels only; desired values are never treated as applied.
    """
    def __init__(self,credentials,ledger=None,channels=None):
        self.id=credentials['id'];self.secret=credentials['secret'];self.boot=secrets.token_hex(16)
        self.sequence=0;self.tseq=0;self.channel_values={};self.types={};self.schema=[]
        self.revisions={};self.keys={};self.ledger=Path(ledger) if ledger else None
        if channels is not None: self.configure(channels)
    def configure(self,channels):
        self.schema=channels;self.types={c['number']:c['type'] for c in channels}
        self.channel_values={};self.revisions={};self.keys={}
        for c in channels:
            kind=c['type'];value=False if kind==1 else '' if kind in (12,13) else {} if kind==14 else 0
            if kind in range(2,12) or kind==15:
                if c.get('minimum') is not None: value=max(value,c['minimum'])
                if c.get('maximum') is not None: value=min(value,c['maximum'])
                if kind not in (10,11): value=math.ceil(value)
            self.channel_values[c['number']]=self.validate(c['number'],value)
        if self.ledger and self.ledger.exists():
            old=json.loads(self.ledger.read_text())
            if old.get('device_id')==self.id and old.get('schema')==self.schema:
                values={int(k):self.validate(int(k),v) for k,v in old['values'].items()}
                if values.keys()==self.types.keys():
                    self.channel_values=values;self.revisions={int(k):v for k,v in old['revisions'].items()};self.keys=old['keys']
            else: print('Ignoring simulator state for a different device or channel schema.')
    def validate(self,ch,value):
        value=typed_value(self.types[ch],value);c=next(c for c in self.schema if c['number']==ch)
        numeric=int(value) if self.types[ch] in (8,9,15) else value
        if c.get('minimum') is not None and numeric<c['minimum']: raise ValueError(f'V{ch}: value below minimum')
        if c.get('maximum') is not None and numeric>c['maximum']: raise ValueError(f'V{ch}: value above maximum')
        return value
    def after_apply(self): pass
    def extra_reports(self): return []
    def apply(self,c):
        key=c['command_key'];ch=c['channel'];rev=c['desired_revision']
        if key in self.keys: return 'applied',0
        if int(c['expires_at_ms'])<=now_ms(): return 'rejected',408
        if rev<=self.revisions.get(ch,0): return 'rejected',409
        if ch not in self.types or c['type']!=self.types[ch]: return 'rejected',404
        definition=next(d for d in self.schema if d['number']==ch)
        if not definition['writable']: return 'rejected',403
        try: value=self.validate(ch,c['value'])
        except (ValueError,TypeError): return 'rejected',400
        self.channel_values[ch]=value;self.revisions[ch]=rev;self.keys[key]=ch
        if len(self.keys)>1024: self.keys.pop(next(iter(self.keys)))
        self.after_apply()
        if self.ledger:
            self.ledger.parent.mkdir(parents=True,exist_ok=True)
            temp=self.ledger.with_suffix('.tmp');temp.write_text(json.dumps({'device_id':self.id,'schema':self.schema,'revisions':self.revisions,'keys':self.keys,'values':self.channel_values}));temp.replace(self.ledger)
        print(f"Applied V{ch}={c['value']} revision {rev}")
        return 'applied',0
    def report(self,ch,key='0'*32,rev=0):
        self.sequence+=1
        return {'boot_id':self.boot,'sequence':self.sequence,'channel':ch,'type':self.types[ch],
                'value':self.channel_values[ch],'observed_at_ms':now_ms(),
                'applied_command_key':key,'desired_revision':rev}
    def telemetry(self):
        # Simulate a temperature sensor on read-only channel V5.
        if 5 not in self.types:
            return None

        value = round(25 + 5 * math.sin(time.time() / 10), 2)
        self.channel_values[5] = self.validate(5, value)
        self.tseq += 1
        return {
            'boot_id': self.boot,
            'sequence': self.tseq,
            'observed_at_ms': now_ms(),
            'metrics': [{
                'name': 'temperature',
                'type': self.types[5],
                'value': self.channel_values[5],
            }],
        }
    async def http(self,url,ca=None):
        async with httpx.AsyncClient(base_url=url,verify=ca or True,trust_env=False,headers={'Authorization':'Device '+self.secret}) as client:
            root='/device/'+self.id
            async def post(path,data):
                r=await client.post(root+path,json=data);return checked(r,data.get('channel'))
            info=await post('/connect',{'boot_id':self.boot,'firmware':'omnilink-sim-0.4'})
            if not self.schema: self.configure(info['channels'])
            print(f'Connected simulated device {self.id}: {len(self.types)} configured channels. No physical hardware is being controlled.')
            if not self.types: print('No channels configured; add channels in server administration, then restart this simulator.')
            for ch in self.types: await post('/report',self.report(ch))
            last=0
            while True:
                r=await client.get(root+'/commands')
                for c in checked(r):
                    status,error=self.apply(c)
                    await post('/ack',{'command_key':c['command_key'],'desired_revision':c['desired_revision'],'status':status,'error_code':error})
                    if status=='applied':
                        await post('/report',self.report(c['channel'],c['command_key'],c['desired_revision']))
                        for ch in self.extra_reports(): await post('/report',self.report(ch))
                if time.monotonic() - last > 5:
                    t = self.telemetry()
                    if t:
                        await post('/telemetry', t)

                        # Report the updated sensor value to the dashboard.
                        if 5 in self.types:
                            await post('/report', self.report(5))

                        for ch in self.extra_reports():
                            await post('/report', self.report(ch))

                    last = time.monotonic()
                await asyncio.sleep(1)
    async def native(self,host,port,ca):
        ctx=ssl.create_default_context(cafile=ca)
        reader,writer=await asyncio.open_connection(host,port,ssl=ctx,server_hostname=host)
        io=TCPIO(reader,writer);mid=1;sid=0
        async def send(kind,payload=b'',flags=0,message_id=None):
            nonlocal mid
            mid=mid%0xffffffff+1
            await io.send(onp.Frame(kind,message_id or mid,sid,payload,flags),4096)
        hello=text8(self.id)+b'\x00'+text8('omnilink-sim-0.4')+struct.pack('>BIIIH',1,0x3f,0x7fff,4096,30)+secrets.token_bytes(16)+bytes.fromhex(self.boot)
        await send(1,hello)
        ack=await io.receive(256,10);challenge=await io.receive(256,10)
        proof=onp.auth_proof(bytes.fromhex(self.secret),hello,ack.payload,challenge.payload[:32])
        await send(5,b'\x01\x00\x20'+proof,onp.RESPONSE,challenge.message_id)
        ok=await io.receive(256,10)
        if ok.type!=6: raise RuntimeError('Authentication rejected')
        sid=ok.session_id
        async def report(ch,key='0'*32,revision=0):
            r=self.report(ch,key,revision)
            payload=onp.encode_report(onp.Report(r['sequence'],r['observed_at_ms'],bytes.fromhex(key),revision,ch,onp.Type(r['type']),wire_value(r['type'],r['value'])))
            await send(0x13,payload)
        for ch in self.types: await report(ch)
        async def metrics():
            while True:
                t=self.telemetry()
                if t:
                    m=t['metrics'][0]
                    payload=struct.pack('>IQBH',t['sequence'],t['observed_at_ms'],0,1)+text8(m['name'])+onp.encode_value(m['type'],m['value'])
                    await send(0x20,payload)
                    for ch in self.extra_reports(): await report(ch)
                await send(8)
                await asyncio.sleep(5)
        task=asyncio.create_task(metrics())
        try:
            while True:
                f=await io.receive(4096,90)
                if f.type==0x10:
                    w=onp.decode_write(f.payload)
                    c={'command_key':w.command_key.hex(),'desired_revision':w.desired_revision,'expires_at_ms':str(w.expires_at_ms),'channel':w.channel,'type':int(w.type),'value':NativeJSON(w.type,w.value)}
                    status,error=self.apply(c)
                    await send(0x80 if not error else 0x81,onp.encode_ack(onp.Ack(w.command_key,w.desired_revision,1 if not error else 2,error)),onp.RESPONSE,f.message_id)
                    if not error:
                        await report(w.channel,c['command_key'],w.desired_revision)
                        for ch in self.extra_reports(): await report(ch)
                elif f.type==0x11:
                    ch=int.from_bytes(f.payload,'big')
                    if ch in self.types: await report(ch)
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            await io.close()
    async def mqtt(self,host,port,ca):
        from paho.mqtt import client as mqtt
        loop=asyncio.get_running_loop();queue=asyncio.Queue();connected=asyncio.Event()
        c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=self.id,clean_session=True)
        c.username_pw_set(self.id,self.secret)
        if ca: c.tls_set(ca_certs=ca,tls_version=ssl.PROTOCOL_TLS_CLIENT)
        root='omnilink/v1/dev/'+self.id+'/'
        c.will_set(root+'status',json.dumps({'online':False}),qos=1,retain=False)
        def on_connect(client,u,f,reason,p):
            if reason==0:
                client.subscribe(root+'cmd',qos=1)
                client.publish(root+'status',json.dumps({'online':True,'boot_id':self.boot,'firmware':'omnilink-sim-0.4'}),qos=1,retain=False)
                loop.call_soon_threadsafe(connected.set)
            else: print('MQTT authentication rejected:',reason)
        c.on_connect=on_connect
        c.on_message=lambda client,u,m:loop.call_soon_threadsafe(queue.put_nowait,json.loads(m.payload))
        c.connect_async(host,port,30);c.loop_start()
        def publish(topic,data): c.publish(root+topic,json.dumps(data),qos=1,retain=False)
        try:
            await asyncio.wait_for(connected.wait(),20)
            await asyncio.sleep(.5)
            for ch in self.types: publish('state',self.report(ch))
            last=0
            while True:
                try: command=await asyncio.wait_for(queue.get(),1)
                except asyncio.TimeoutError: command=None
                if command:
                    status,error=self.apply(command)
                    publish('ack',{'command_key':command['command_key'],'desired_revision':command['desired_revision'],'status':status,'error_code':error})
                    if not error:
                        publish('state',self.report(command['channel'],command['command_key'],command['desired_revision']))
                        for ch in self.extra_reports(): publish('state',self.report(ch))
                if time.monotonic() - last > 5:
                    t = self.telemetry()
                    if t:
                        publish('telemetry', t)
                        publish('state', self.report(5))
                        for ch in self.extra_reports():
                            publish('state', self.report(ch))
                    last = time.monotonic()
        finally:
            c.disconnect();await asyncio.to_thread(c.loop_stop)

def NativeJSON(kind,value):
    from omnilink.native import NativeSession
    return NativeSession.json_value(kind,value)

def main(simulator_class=Simulator):
    p=argparse.ArgumentParser();p.add_argument('--credentials',default='device-credentials.json');p.add_argument('--transport',choices=['http','onp','mqtt'],default='http');p.add_argument('--url',default='http://localhost:8000');p.add_argument('--host',default='localhost');p.add_argument('--port',type=int);p.add_argument('--ca',default='data/certs/ca.crt');p.add_argument('--ledger');p.add_argument('--schema',help='Channel schema JSON file for ONP/MQTT; otherwise discover through --url');p.add_argument('--http-ca',help='CA certificate for an HTTPS discovery/HTTP server')
    a=p.parse_args();credentials=json.loads(Path(a.credentials).read_text());sim=simulator_class(credentials,a.ledger or f'data/simulator-{credentials["id"]}.json')
    async def run():
        if a.transport!='http' and not sim.schema:
            if a.schema: sim.configure(json.loads(Path(a.schema).read_text()))
            else:
                async with httpx.AsyncClient(verify=a.http_ca or True,trust_env=False) as client:
                    sim.configure(checked(await client.get(a.url.rstrip('/')+'/device/'+sim.id+'/channels',headers={'Authorization':'Device '+sim.secret})))
        await (sim.http(a.url,a.http_ca) if a.transport=='http' else sim.native(a.host,a.port or 7443,a.ca) if a.transport=='onp' else sim.mqtt(a.host,a.port or 8883,a.ca))
    try: asyncio.run(run())
    except KeyboardInterrupt: print('Simulator stopped.')
    except (RuntimeError,ValueError,httpx.HTTPError,OSError) as exc: raise SystemExit(str(exc))

if __name__=='__main__': main()

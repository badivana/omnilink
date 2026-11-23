"""OmniLink Arduino 0.3 library and examples, run on the host against this server.

Each example sketch is compiled with g++ against small Arduino stubs
(tests/arduino_host/stubs). Network calls are forwarded in lockstep to the
real test server: HTTP through the device API, MQTT through the server's own
MQTT message handler (the harness plays the broker), and the Uno through the
real examples/arduino_uno_serial_gateway.py. Skipped when g++ or ArduinoJson 7
is unavailable (set OMNILINK_ARDUINOJSON to ArduinoJson's src folder).
"""
import asyncio, json, os, re, shutil, subprocess, threading
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from conftest import eventually

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT.parent/'OmniLink_Arduino_v0.3'   # separate package next to the server
HOST=ROOT/'tests'/'arduino_host'
ARDUINOJSON=Path(os.getenv('OMNILINK_ARDUINOJSON',Path.home()/'Documents'/'Arduino'/'libraries'/'ArduinoJson'/'src'))
GXX=shutil.which('g++')
pytestmark=pytest.mark.skipif(not GXX or not (ARDUINOJSON/'ArduinoJson.h').is_file() or not LIB.is_dir(),
                              reason='Needs g++, ArduinoJson 7 (OMNILINK_ARDUINOJSON) and ../OmniLink_Arduino_v0.3 for host builds')
# Same pins as `python -m examples.create_demo` in a fresh account.
DEMO=[(0,'Power',1,True,None,None),(1,'Output selection',3,True,0,1),(2,'Setpoint',7,True,1,300),(3,'Measurement',10,False,0,100)]
BOARDS={'esp32':['-DESP32','-DHOST_ANALOG=2048'],'esp8266':['-DESP8266'],
        'uno':['-DOMNILINK_SERIAL_TRANSPORT','-DHOST_SERIAL_PROTOCOL','-DHOST_ANALOG=512']}

def build(sketch,board,tmp,replace=None,run=True):
    source=(LIB/'examples'/sketch/f'{sketch}.ino').read_text(encoding='utf-8')
    for pattern,value in (replace or {}).items():
        source,count=re.subn(pattern,value,source);assert count,pattern
    ino=tmp/f'{sketch}.cpp';ino.write_text(source,encoding='utf-8')
    exe=tmp/(sketch+('.exe' if os.name=='nt' else ''))
    cmd=[GXX,'-std=gnu++17','-Wall','-Werror','-Wno-unused-variable','-DARDUINO=10819','-DARDUINOJSON_ENABLE_PROGMEM=0',*BOARDS[board],
         '-I',str(HOST/'stubs'),'-I',str(LIB/'src'),'-I',str(ARDUINOJSON),str(ino),
         str(LIB/'src'/'OmniLinkMqtt.cpp'),str(LIB/'src'/'OmniLinkSerial.cpp')]
    cmd+=[str(HOST/'host_main.cpp'),'-static','-o',str(exe)] if run else ['-fsyntax-only']
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
    assert result.returncode==0,result.stderr[-4000:]
    return exe

def credentials(device,url,**extra):
    values={r'DEVICE_ID = "[^"]*"':f'DEVICE_ID = "{device["id"]}"',r'DEVICE_SECRET = "[^"]*"':f'DEVICE_SECRET = "{device["secret"]}"'}
    values.update(extra);return values

class Board:
    """Runs a host build; handler(request)->reply until stop is set."""
    def __init__(self,exe,handler,tmp):
        self.stop=threading.Event();self.errors=[]
        self.proc=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=open(tmp/'board.log','w'),text=True,bufsize=1)
        self.handler=handler
    def run(self):
        try:
            while not self.stop.is_set():
                line=self.proc.stdout.readline()
                if not line: break
                self.proc.stdin.write(json.dumps(self.handler(json.loads(line)))+'\n');self.proc.stdin.flush()
        except Exception as exc: self.errors.append(exc)
        finally: self.proc.kill();self.proc.wait()

async def demo_device(system):
    c=system['client']
    r=await c.post('/api/devices',json={'name':'Arduino demo'});assert r.status_code==200,r.text;d=r.json()
    for number,name,kind,writable,low,high in DEMO:
        r=await c.put(f"/api/devices/{d['id']}/channels/{number}",json={'name':name,'type':kind,'writable':writable,'minimum':low,'maximum':high})
        assert r.status_code==200,r.text
    return d

async def exercise(system,d,percent):
    """Same checks for every transport: real initial state, then dashboard writes."""
    c=system['client'];base=f"/api/devices/{d['id']}"
    async def channels():
        return {ch['number']:ch for ch in (await c.get(base+'/channels')).json()}
    async def initial():
        ch=await channels()
        return ch[0]['reported'] is False and ch[1]['reported']==0 and ch[2]['reported']==10 \
               and ch[3]['reported'] is not None and abs(ch[3]['reported']-percent)<0.01 and ch
    await eventually(initial,15)
    hist=await c.get('/api/history',params={'device_id':d['id'],'metric':'measurement'})
    assert hist.json() and abs(hist.json()[0]['value']-percent)<0.01
    for number,value in ((0,True),(1,1),(2,5),(0,False)):
        r=await c.post(f'{base}/channels/{number}/write',json={'value':value});assert r.status_code==200,r.text
        command=r.json()
        async def applied():
            commands={x['command_key']:x for x in (await c.get(base+'/commands')).json()}
            ch=(await channels())[number]
            return commands[command['command_key']]['status']=='applied' and ch['reported']==value \
                   and ch['reported_revision']==command['desired_revision']
        await eventually(applied,10)
    # Bounds come from the server pin definition (Setpoint is 1..300).
    assert (await c.post(f'{base}/channels/2/write',json={'value':0})).status_code==400
    assert (await c.get('/api/devices')).json()[0]['online']

def http_handler(device_url,device,seen):
    client=httpx.Client(base_url=device_url,trust_env=False,timeout=10)
    def handle(req):
        assert req['h']=='http',req
        path=re.sub(r'^https?://[^/]+','',req['url'])
        seen.add((req['method'],path.rsplit('/',1)[-1]))
        response=client.request(req['method'],path,content=req.get('body'),
                                headers={'Authorization':req['auth'],**({'Content-Type':'application/json'} if 'body' in req else {})})
        return {'code':response.status_code,'body':response.text}
    return handle

@pytest.mark.asyncio
async def test_esp32_http_example_against_server(system):
    d=await demo_device(system);seen=set()
    exe=await asyncio.to_thread(build,'ESP32_HTTP','esp32',system['tmp'],
        credentials(d,system['url'],**{r'#define OMNILINK_HTTP_TLS 1':'#define OMNILINK_HTTP_TLS 0',r'"http://192\.168\.1\.50:8000"':'"'+system['url']+'"'}))
    board=Board(exe,http_handler(system['url'],d,seen),system['tmp'])
    task=asyncio.create_task(asyncio.to_thread(board.run))
    try:
        await exercise(system,d,2048*100/4095)
        assert {('POST','connect'),('GET','commands'),('POST','report'),('POST','ack'),('POST','telemetry')}<=seen
    finally:
        board.stop.set();await task
    assert not board.errors,board.errors

@pytest.mark.asyncio
async def test_esp32_mqtt_example_against_server(system):
    from omnilink.mqtt import MQTTAdapter
    rt=system['rt'];d=await demo_device(system);root=f"omnilink/v1/dev/{d['id']}/"
    warnings=[];rt.log.warning=lambda *a:warnings.append(a)
    broker=SimpleNamespace(rt=rt);topics=[]
    def handle(req):
        kind=req['h']
        if kind=='mqtt_connect':
            # Same credentials the server provisions in Mosquitto Dynamic Security.
            ok=req['id']==req['user']==d['id'] and req['pass']==d['secret'] and req['will_topic']==root+'status'
            return {'ok':ok,'state':0 if ok else 4}
        if kind=='mqtt_sub':
            assert req['topic']==root+'cmd' and req['qos']==1;return {'ok':True}
        if kind=='mqtt_pub':
            assert req['topic'].startswith(root) and req['retain'] is False
            topics.append(req['topic'][len(root):])
            MQTTAdapter.message(broker,req['topic'],req['payload'].encode(),False);return {'ok':True}
        if kind=='mqtt_loop':   # mirrors Runtime.worker + MQTTAdapter.send_command
            msgs=[]
            for c in rt.core.pending(d['id']):
                rt.core.mark_sent(c['command_key']);msgs.append({'topic':root+'cmd','payload':json.dumps(c,separators=(',',':'))})
            return {'msgs':msgs}
        raise AssertionError(req)
    exe=await asyncio.to_thread(build,'ESP32_MQTT','esp32',system['tmp'],
        credentials(d,system['url'],**{r'#define OMNILINK_MQTT_TLS 1':'#define OMNILINK_MQTT_TLS 0'}))
    board=Board(exe,handle,system['tmp'])
    task=asyncio.create_task(asyncio.to_thread(board.run))
    try:
        await exercise(system,d,2048*100/4095)
    finally:
        board.stop.set();await task
    assert not board.errors,board.errors
    assert not warnings,warnings   # the server accepted every MQTT message
    assert {'status','state','telemetry','ack'}<=set(topics)

@pytest.mark.asyncio
async def test_uno_serial_example_through_gateway(system):
    from examples.arduino_uno_serial_gateway import SerialGateway,ask_board
    d=await demo_device(system);log=[]
    # The credentials live only in the sketch; the gateway reads them from the board.
    exe=await asyncio.to_thread(build,'ArduinoUno_Serial','uno',system['tmp'],
                                {r'DEVICE_ID\[\]\s*=\s*""':f'DEVICE_ID[] = "{d["id"]}"',r'DEVICE_SECRET\[\]\s*=\s*""':f'DEVICE_SECRET[] = "{d["secret"]}"'})
    class ProcPort:   # the Uno's USB serial port, as pyserial would present it
        def __init__(self): self.pending=b'';self.lines=[]
        def write(self,raw): self.pending+=raw
        def readline(self):
            if not self.lines:
                req=json.loads(proc.stdout.readline())
                proc.stdin.write(json.dumps({'in':self.pending.decode()})+'\n');proc.stdin.flush();self.pending=b''
                self.lines=[p.encode()+b'\n' for p in req['out'].split('\n') if p]
            return self.lines.pop(0) if self.lines else b''
    proc=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    stop=threading.Event();errors=[]
    def run():
        try:
            port=ProcPort();device_id,secret=ask_board(port)
            assert (device_id,secret)==(d['id'],d['secret'])
            with httpx.Client(base_url=system['url'],trust_env=False,timeout=10,headers={'Authorization':'Device '+secret}) as client:
                gateway=SerialGateway(client,port,device_id,log=log.append)
                gateway.connect()
                while not stop.is_set(): gateway.step()
        except Exception as exc: errors.append(exc)
        finally: proc.kill();proc.wait()
    task=asyncio.create_task(asyncio.to_thread(run))
    try:
        await exercise(system,d,512*100/1023)
    finally:
        stop.set();await task
    assert not errors,errors
    assert not [line for line in log if 'rejected' in line.lower() or 'ignoring' in line.lower()],log

def test_gateway_explains_a_board_without_credentials():
    from examples.arduino_uno_serial_gateway import ask_board
    port=SimpleNamespace(write=lambda raw:None,readline=lambda:b'{"op":"identity","id":"","secret":""}\n')
    with pytest.raises(ValueError,match='DEVICE_ID'):ask_board(port)

def test_gateway_survives_rejections_and_reports_reason():
    """A bad board line or a server 400 is logged; the gateway keeps running."""
    from examples.arduino_uno_serial_gateway import SerialGateway
    calls=[]
    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/connect'):
            return httpx.Response(200,json={'channels':[{'number':3,'name':'Measurement','type':10}]})
        return httpx.Response(400,json={'detail':'Value above channel maximum'})
    client=httpx.Client(base_url='http://server',transport=httpx.MockTransport(respond))
    port=SimpleNamespace(written=[],write=lambda raw:port.written.append(raw))
    log=[];gw=SerialGateway(client,port,'dev_x',log=log.append)
    gw.connect()
    assert json.loads(port.written[0])=={'op':'sync'}
    gw.handle_line(b'{"op":"report","channel":3,"type":10,"value":250}\n')
    gw.handle_line(b'debug text from Serial.print\n')
    gw.handle_line(b'{"op":"report","channel":9,"type":1,"value":true}\n')
    gw.handle_line(b'{"op":"ack"}\n')
    assert gw.connected
    assert any('Value above channel maximum' in line for line in log)
    assert any('Board: debug text' in line for line in log)
    assert any('V9' in line for line in log) and any('malformed' in line for line in log)

@pytest.mark.parametrize('sketch,board',[('ESP8266_HTTP','esp8266'),('ESP8266_MQTT','esp8266'),('ESP8266_Provisioning','esp8266')])
def test_other_examples_compile(sketch,board,tmp_path):
    build(sketch,board,tmp_path,run=False)

def test_bundled_gateway_matches_server_example():
    assert (LIB/'examples'/'ArduinoUno_Serial'/'arduino_uno_serial_gateway.py').read_bytes()==(ROOT/'examples'/'arduino_uno_serial_gateway.py').read_bytes()

"""HTTPS bridge for OmniLinkSerial (OmniLink Arduino 0.3) on a USB Uno/Nano.

The board exchanges bounded JSON lines over USB. This process maps each line to
the OmniLink Server v0.6 HTTP device API:

  at start the gateway sends {"op":"identify"}; the board answers with the
  device ID and secret stored in its sketch
  board -> {"op":"report"|"telemetry"|"event"|"ack",...}  -> POST /device/<id>/...
  server  GET /device/<id>/commands -> {"op":"command",...} -> board
  on every (re)connect the gateway sends {"op":"sync"} so the board reports
  its real state.

A rejected message (for example a value outside the pin's limits) is printed
with the server's reason and the gateway keeps running. A lost network or
server restart triggers a reconnect with backoff instead of exiting.

Credentials: DEVICE_ID and DEVICE_SECRET in the ArduinoUno_Serial sketch. To
keep them off the board instead, pass --credentials with the JSON from OmniLink.
"""
import argparse, json, secrets, sys, time
from pathlib import Path
import httpx

LINE_LIMIT=224          # OmniLinkSerial::LINE_SIZE, including the newline
RESEND_AFTER=10         # seconds before an unacknowledged command is resent
FIRMWARE='omnilink-uno-serial-gateway/0.3'

def ask_board(port,timeout=10):
    """Read the device ID/secret stored in the sketch (OmniLinkSerial "identify")."""
    deadline=time.monotonic()+timeout;asked=0.0
    while time.monotonic()<deadline:
        if time.monotonic()-asked>=1:
            port.write(b'{"op":"identify"}\n');asked=time.monotonic()
        try: msg=json.loads(port.readline() or b'null')
        except (ValueError,UnicodeDecodeError): continue
        if isinstance(msg,dict) and msg.get('op')=='identity':
            if not msg.get('id') or not msg.get('secret'):
                raise ValueError('The board has no device ID/secret: fill in DEVICE_ID and DEVICE_SECRET in the sketch and upload it again')
            return msg['id'],msg['secret']
    raise ValueError('The board did not answer with its device ID. Upload the current ArduinoUno_Serial sketch and close Serial Monitor.')

def detail(response):
    try: return response.json().get('detail',response.text)
    except ValueError: return response.text

class SerialGateway:
    def __init__(self,client,port,device_id,log=print,boot=None):
        self.client,self.port,self.log=client,port,log
        self.root='/device/'+device_id
        self.boot=boot or secrets.token_hex(16)
        self.seq=0;self.channels={};self.inflight={}
        self.connected=False;self.last_poll=0.0

    def post(self,path,body):
        """POST one message; a server rejection is reported, not fatal."""
        response=self.client.post(self.root+path,json=body)
        if response.status_code in (401,403,404):
            self.connected=False
            raise PermissionError(f'{path}: HTTP {response.status_code} {detail(response)}')
        if response.status_code==409 and 'boot' in str(detail(response)).lower():
            self.connected=False
        if response.is_error:
            self.log(f'Server rejected {path[1:]}: HTTP {response.status_code} {detail(response)}')
            return False
        return True

    def connect(self):
        r=self.client.post(self.root+'/connect',json={'boot_id':self.boot,'firmware':FIRMWARE})
        if r.is_error: raise PermissionError(f'connect: HTTP {r.status_code} {detail(r)}')
        self.channels={c['number']:c for c in r.json().get('channels',[])}
        self.connected=True;self.inflight.clear();self.last_poll=0.0
        self.log(f'Connected; {len(self.channels)} configured pins: '+', '.join(f"V{n} {c['name']}" for n,c in sorted(self.channels.items())))
        self.write({'op':'sync'})

    def write(self,obj):
        raw=(json.dumps(obj,separators=(',',':'))+'\n').encode()
        if len(raw)>LINE_LIMIT: return False
        self.port.write(raw);return True

    def next_seq(self):
        self.seq+=1;return self.seq

    def report(self,channel,kind,value,key='0'*32,revision=0):
        definition=self.channels.get(channel)
        if definition is None or kind!=definition['type']:
            self.log(f'Ignoring report for V{channel}: not configured on the server with type {kind}');return False
        return self.post('/report',{'boot_id':self.boot,'sequence':self.next_seq(),'channel':channel,'type':kind,'value':value,
                                    'observed_at_ms':0,'applied_command_key':key,'desired_revision':revision})

    def handle_line(self,raw):
        try:
            msg=json.loads(raw)
            if not isinstance(msg,dict): raise ValueError
        except (ValueError,UnicodeDecodeError):
            text=raw.decode(errors='replace').strip() if isinstance(raw,bytes) else str(raw)
            if text: self.log('Board: '+text[:120])   # plain Serial.print debug output
            return
        try:
            op=msg.get('op')
            if op=='identity': return   # late answer to the startup "identify"
            if op=='report': self.report(int(msg['channel']),int(msg['type']),msg['value'])
            elif op=='ack':
                key,rev=msg['command_key'],int(msg['desired_revision'])
                self.inflight.pop(key,None)
                ok=self.post('/ack',{'command_key':key,'desired_revision':rev,'status':msg['status'],'error_code':int(msg.get('error_code',0))})
                if ok and msg['status']=='applied':
                    self.report(int(msg['channel']),int(msg['type']),msg['value'],key,rev)
                elif msg['status']!='applied':
                    self.log(f"Board rejected V{msg.get('channel')} command (error {msg.get('error_code')})")
            elif op=='telemetry':
                self.post('/telemetry',{'boot_id':self.boot,'sequence':self.next_seq(),'observed_at_ms':0,'quality':0,
                                        'metrics':[{'name':msg['metric'],'type':int(msg['type']),'value':msg['value']}]})
            elif op=='event':
                self.post('/event',{'boot_id':self.boot,'sequence':self.next_seq(),'observed_at_ms':0,
                                    'severity':int(msg['severity']),'code':msg['code'],'detail':msg.get('detail','')})
            else: self.log(f'Ignoring unknown board message {op!r}')
        except (KeyError,TypeError,ValueError) as exc:
            self.log(f'Ignoring malformed board message ({type(exc).__name__}: {exc})')

    def poll(self,now=None):
        now=time.monotonic() if now is None else now
        if now-self.last_poll<1: return
        self.last_poll=now
        r=self.client.get(self.root+'/commands')
        if r.status_code in (401,403,404,409):
            self.connected=False;raise PermissionError(f'poll: HTTP {r.status_code} {detail(r)}')
        r.raise_for_status()
        pending=r.json()
        current={c['command_key'] for c in pending}
        self.inflight={k:v for k,v in self.inflight.items() if k in current}   # superseded/expired
        for c in pending:
            key=c['command_key']
            if now-self.inflight.get(key,-RESEND_AFTER)<RESEND_AFTER: continue
            command={'op':'command','command_key':key,'desired_revision':c['desired_revision'],
                     'channel':c['channel'],'type':c['type'],'value':c['value']}
            if self.write(command): self.inflight[key]=now
            else:
                self.log(f"V{c['channel']} command is too large for the board; rejecting it")
                self.post('/ack',{'command_key':key,'desired_revision':c['desired_revision'],'status':'rejected','error_code':413})

    def step(self):
        raw=self.port.readline()
        if raw: self.handle_line(raw)
        self.poll()

def main():
    p=argparse.ArgumentParser(description='Bridge an OmniLinkSerial Uno/Nano to OmniLink Server over HTTPS.')
    p.add_argument('--serial',required=True,help='COM4 on Windows or /dev/ttyACM0 on Linux')
    p.add_argument('--credentials',help='JSON file with id/secret; default: read DEVICE_ID/DEVICE_SECRET from the sketch')
    p.add_argument('--url',required=True,help='OmniLink server URL, e.g. https://iot.example.com')
    p.add_argument('--ca',help='CA certificate used by the HTTPS server, if private (e.g. data/certs/ca.crt)')
    p.add_argument('--baud',type=int,default=115200)
    a=p.parse_args()
    import serial
    if a.url.startswith('http://') and not any(h in a.url for h in ('://localhost','://127.0.0.1')):
        print('Warning: plain HTTP sends the device secret unencrypted; use HTTPS outside a private test network.')
    with serial.Serial(a.serial,a.baud,timeout=.1,write_timeout=3) as port:
        time.sleep(2)   # opening the port resets an Uno; wait for its bootloader
        if a.credentials:
            credentials=json.loads(Path(a.credentials).read_text(encoding='utf-8'))
            device_id,secret=credentials['id'],credentials['secret']
        else: device_id,secret=ask_board(port)
        client=httpx.Client(base_url=a.url.rstrip('/'),verify=a.ca or True,trust_env=False,headers={'Authorization':'Device '+secret},timeout=10)
        gateway=SerialGateway(client,port,device_id)
        print(f'Gateway for {device_id} on {a.serial}. Ctrl+C stops it.')
        delay=1
        try:
            while True:
                try:
                    if not gateway.connected: gateway.connect();delay=1
                    gateway.step()
                except (httpx.TransportError,httpx.HTTPStatusError,PermissionError) as exc:
                    gateway.connected=False
                    print(f'Server unavailable ({exc}); retrying in {delay}s')
                    time.sleep(delay);delay=min(delay*2,30)
        except KeyboardInterrupt:
            print('\nSerial gateway stopped.')
        finally: client.close()
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,KeyError,ValueError) as exc:
        print(f'OmniLink serial gateway error: {exc}',file=sys.stderr);raise SystemExit(2)

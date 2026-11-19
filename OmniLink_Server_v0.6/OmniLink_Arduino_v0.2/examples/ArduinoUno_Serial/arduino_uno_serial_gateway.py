"""HTTPS bridge for OmniLinkSerial on a USB-connected Arduino Uno/Nano.

The Uno sends bounded JSON lines over USB. This process holds the device
credential and maps lines to the authenticated HTTP device API.
"""
import argparse, json, secrets, sys, time
from pathlib import Path
import httpx, serial

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--serial',required=True,help='COM4 on Windows or /dev/ttyACM0 on Linux')
    p.add_argument('--credentials',default='device-credentials.json')
    p.add_argument('--url',required=True,help='OmniLink server URL, e.g. https://iot.example.com')
    p.add_argument('--ca',help='CA certificate used by the HTTPS server, if private/self-signed')
    p.add_argument('--baud',type=int,default=115200)
    a=p.parse_args()
    credentials=json.loads(Path(a.credentials).read_text(encoding='utf-8'))
    device_id,secret=credentials['id'],credentials['secret']
    boot=secrets.token_hex(16);seq=0
    headers={'Authorization':'Device '+secret}
    with httpx.Client(base_url=a.url.rstrip('/'),verify=a.ca or True,trust_env=False,headers=headers,timeout=10) as client, serial.Serial(a.serial,a.baud,timeout=.1,write_timeout=3) as port:
        root='/device/'+device_id
        r=client.post(root+'/connect',json={'boot_id':boot,'firmware':'omnilink-uno-serial-0.1'});r.raise_for_status()
        channels={c['number']:c for c in r.json().get('channels',[])}
        print(f"Connected {device_id}; {len(channels)} configured channels. Waiting for USB serial device.")
        last_poll=0.0; last_send={}; inflight={}
        def send_command(c):
            obj={'op':'command','command_key':c['command_key'],'desired_revision':c['desired_revision'],
                 'channel':c['channel'],'type':c['type'],'value':c['value']}
            raw=(json.dumps(obj,separators=(',',':'))+'\n').encode()
            if len(raw)>224: print(f"Skipping oversize command for V{c['channel']}");return
            port.write(raw);inflight[c['command_key']]=c;last_send[c['command_key']]=time.monotonic()
        def receive_line(raw):
            nonlocal seq
            try: msg=json.loads(raw)
            except (ValueError,UnicodeDecodeError): print('Ignoring invalid serial JSON line');return
            op=msg.get('op')
            if op=='report':
                ch=int(msg['channel']);definition=channels.get(ch)
                if definition is None or int(msg['type'])!=definition['type']:
                    print(f'Ignoring unconfigured channel V{ch}');return
                seq+=1
                body={'boot_id':boot,'sequence':seq,'channel':ch,'type':int(msg['type']),'value':msg['value'],'observed_at_ms':0,
                      'applied_command_key':'0'*32,'desired_revision':0}
                response=client.post(root+'/report',json=body);response.raise_for_status()
            elif op=='ack':
                key=msg['command_key'];rev=int(msg['desired_revision']);status=msg['status'];error=int(msg.get('error_code',0))
                response=client.post(root+'/ack',json={'command_key':key,'desired_revision':rev,'status':status,'error_code':error});response.raise_for_status()
                inflight.pop(key,None);last_send.pop(key,None)
                if status=='applied':
                    seq+=1;ch=int(msg['channel'])
                    body={'boot_id':boot,'sequence':seq,'channel':ch,'type':int(msg['type']),'value':msg['value'],'observed_at_ms':0,
                          'applied_command_key':key,'desired_revision':rev}
                    response=client.post(root+'/report',json=body);response.raise_for_status()
            elif op=='telemetry':
                seq+=1
                body={'boot_id':boot,'sequence':seq,'observed_at_ms':0,'quality':0,
                      'metrics':[{'name':msg['metric'],'type':int(msg['type']),'value':msg['value']}]}
                response=client.post(root+'/telemetry',json=body);response.raise_for_status()
            elif op=='event':
                seq+=1
                body={'boot_id':boot,'sequence':seq,'observed_at_ms':0,'severity':int(msg['severity']),
                      'code':msg['code'],'detail':msg.get('detail','')}
                response=client.post(root+'/event',json=body);response.raise_for_status()
            else: print('Ignoring unknown serial message')
        try:
            while True:
                raw=port.readline()
                if raw: receive_line(raw)
                now=time.monotonic()
                if now-last_poll>=1:
                    response=client.get(root+'/commands');response.raise_for_status()
                    for command in response.json():
                        key=command['command_key']
                        if key not in inflight or now-last_send.get(key,0)>10:send_command(command)
                    last_poll=now
        except KeyboardInterrupt:
            print('\nSerial gateway stopped.')
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,httpx.HTTPError,KeyError,ValueError,serial.SerialException) as exc:
        print(f'OmniLink serial gateway error: {exc}',file=sys.stderr);raise SystemExit(2)

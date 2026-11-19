import argparse
import getpass
import json
import os
from pathlib import Path
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:8000');p.add_argument('--email');p.add_argument('--aquarium',action='store_true',help='Optional aquarium template');p.add_argument('--output',default='device-credentials.json');a=p.parse_args()
    if Path(a.output).exists(): raise SystemExit('Credentials file already exists; use --output with a new name.')
    email=a.email or input('Account email: ')
    password=getpass.getpass('Account password: ')
    with httpx.Client(base_url=a.url,trust_env=False) as c:
        r=c.post('/api/auth/login',json={'email':email,'password':password});r.raise_for_status()
        c.headers['Authorization']='Bearer '+r.json()['token']
        if a.aquarium:
            from .aquarium_channels import AQUARIUM_CHANNELS
            channels=AQUARIUM_CHANNELS
        else:
            channels=[{'number':number,'name':name,'type':kind,'writable':writable,'minimum':low,'maximum':high}
                      for number,name,kind,writable,low,high in [(0,'Power',1,True,None,None),(1,'Output selection',3,True,0,1),(3,'Setpoint',7,True,1,300),(6,'Measurement',10,False,0,100)]]
        response=c.get('/api/pins');response.raise_for_status();free=response.json()['free']
        if a.aquarium:
            if any(item['number'] not in free for item in channels):raise SystemExit('The optional aquarium example requires V0–V6 to be free. Use a separate account or release those pins explicitly.')
        else:
            if len(free)<len(channels):raise SystemExit('Not enough free pins in this account.')
            channels=[{**item,'number':free[i]} for i,item in enumerate(channels)]
        r=c.post('/api/devices',json={'name':'Aquarium simulator' if a.aquarium else 'Demo device'});r.raise_for_status();device=r.json()
        Path(a.output).write_text(json.dumps(device,indent=2))
        for definition in channels:
            body={k:v for k,v in definition.items() if k!='number'}
            channel=c.put(f"/api/devices/{device['id']}/channels/{definition['number']}",json=body);channel.raise_for_status()
        Path(a.output).write_text(json.dumps(r.json(),indent=2))
        try: Path(a.output).chmod(0o600)
        except OSError: pass
    print('Demo device registered. Credentials saved to '+a.output+'.')

if __name__=='__main__': main()

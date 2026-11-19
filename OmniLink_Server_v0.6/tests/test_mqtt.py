import asyncio
import json
import os
import secrets
import shutil
import ssl
import subprocess
from pathlib import Path
import pytest
import pytest_asyncio
from paho.mqtt import client as mqtt
from omnilink.mqtt import MQTTAdapter
from examples.aquarium_simulator import AquariumSimulator as Simulator
from conftest import device,eventually,free_port

@pytest_asyncio.fixture
async def broker(system):
    binary=os.getenv('MOSQUITTO_BIN') or shutil.which('mosquitto')
    ctrl=os.getenv('MOSQUITTO_CTRL') or shutil.which('mosquitto_ctrl')
    plugin=os.getenv('MOSQUITTO_PLUGIN')
    if not plugin:
        for p in ['/usr/lib/x86_64-linux-gnu/mosquitto_dynamic_security.so','/usr/lib/mosquitto_dynamic_security.so']:
            if Path(p).exists(): plugin=p;break
    if not binary or not ctrl or not plugin: pytest.skip('Install Mosquitto and its Dynamic Security plugin for broker tests')
    folder=system['tmp']/'broker';folder.mkdir()
    admin_password=secrets.token_hex(32)
    config_file=folder/'dynamic-security.json'
    initialized=subprocess.run([ctrl,'dynsec','init',str(config_file),'omnilink-admin'],input=admin_password+'\n'+admin_password+'\n',text=True,capture_output=True,timeout=10)
    assert initialized.returncode==0,initialized.stderr
    port,tls_port=free_port(),free_port()
    cfg=folder/'mosquitto.conf'
    cfg.write_text(f'user root\nallow_anonymous false\nplugin {plugin}\nplugin_opt_config_file {config_file}\nlistener {port} 127.0.0.1\nlistener {tls_port} 127.0.0.1\ncertfile {system["certs"]}/server.crt\nkeyfile {system["certs"]}/server.key\n')
    output=open(folder/'broker.log','w')
    proc=subprocess.Popen([binary,'-c',str(cfg)],stdout=output,stderr=output)
    adapter=None
    try:
        async def listening():
            if proc.poll() is not None: raise AssertionError((folder/'broker.log').read_text())
            try:
                r,w=await asyncio.open_connection('127.0.0.1',port);w.close();await w.wait_closed();return True
            except OSError: return False
        await eventually(listening)
        rt=system['rt'];rt.settings.mqtt_host='localhost';rt.settings.mqtt_port=port
        rt.settings.mqtt_password=secrets.token_hex(32);rt.settings.mqtt_admin_password=admin_password
        adapter=MQTTAdapter(rt);rt.mqtt=adapter;await adapter.start()
        async def ready(): return adapter.ready
        await eventually(ready,15)
        yield {'adapter':adapter,'port':port,'tls_port':tls_port,'system':system}
    finally:
        if adapter: await adapter.stop();system['rt'].mqtt=None
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
        output.close()

async def provision(broker,d):
    async def ready(): return d['id'] in broker['adapter'].provisioned
    await eventually(ready,10)

async def test_mqtt_tls_command_and_report(broker):
    system=broker['system'];d=await device(system);await provision(broker,d)
    sim=Simulator(d);task=asyncio.create_task(sim.mqtt('localhost',broker['tls_port'],str(system['certs']/'ca.crt')))
    try:
        async def seen():
            rows=(await system['client'].get('/api/devices')).json();return any(r['id']==d['id'] and r['online'] for r in rows)
        await eventually(seen)
        response=await system['client'].post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True,'manual_s':0})
        assert response.status_code==200
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json()
            return rows and rows[0]['status']=='applied'
        await eventually(applied,10)
        channels=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
        assert channels[0]['reported'] is True
        assert not task.done()
    finally: task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_mqtt_directional_acl_and_flat_telemetry(broker):
    system=broker['system'];a=await device(system);b=(await system['client'].post('/api/devices',json={'name':'Second device'})).json()
    await provision(broker,a);await provision(broker,b)
    loop=asyncio.get_running_loop();connected=asyncio.Event();sub_results=asyncio.Queue();messages=[]
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=a['id'],protocol=mqtt.MQTTv5)
    client.username_pw_set(a['id'],a['secret']);client.tls_set(ca_certs=str(system['certs']/'ca.crt'))
    client.on_connect=lambda c,u,f,r,p:loop.call_soon_threadsafe(connected.set) if r==0 else None
    client.on_subscribe=lambda c,u,mid,reasons,p:loop.call_soon_threadsafe(sub_results.put_nowait,(mid,reasons))
    client.on_message=lambda c,u,m:loop.call_soon_threadsafe(messages.append,bytes(m.payload))
    client.connect_async('localhost',broker['tls_port'],30);client.loop_start()
    try:
        await asyncio.wait_for(connected.wait(),5)
        root=f"omnilink/v1/dev/{a['id']}/"
        for topic,denied in [(root+'cmd',False),(root+'#',True),(f"omnilink/v1/dev/{b['id']}/cmd",True),(root+'telemetry',True),('$CONTROL/dynamic-security/v1/response',True)]:
            code,mid=client.subscribe(topic,qos=1)
            reply_id,reasons=await asyncio.wait_for(sub_results.get(),5)
            assert reply_id==mid and reasons[0].is_failure==denied,(topic,reasons)
        client.publish(root+'telemetry',json.dumps({'temperature':27.5}),qos=1,retain=False)
        client.publish(f"omnilink/v1/dev/{b['id']}/telemetry",json.dumps({'temperature':99}),qos=1,retain=False)
        client.publish(root+'cmd',json.dumps({'fake':True}),qos=1,retain=False)
        async def received():
            rows=(await system['client'].get(f"/api/devices/{a['id']}/telemetry")).json();return rows and rows[0]['value']==27.5
        await eventually(received)
        assert not (await system['client'].get(f"/api/devices/{b['id']}/telemetry")).json()
        assert not messages, 'Device must not be able to publish a command to its own subscription'
    finally: client.disconnect();await asyncio.to_thread(client.loop_stop)

async def test_disabled_device_cannot_reconnect_to_broker(broker):
    system=broker['system'];d=await device(system);await provision(broker,d)
    response=await system['client'].patch('/api/devices/'+d['id'],json={'enabled':False});assert response.status_code==200
    async def disabled(): return broker['adapter'].enabled.get(d['id']) is False
    await eventually(disabled,10)
    loop=asyncio.get_running_loop();result=asyncio.Queue()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=d['id'])
    client.username_pw_set(d['id'],d['secret']);client.tls_set(ca_certs=str(system['certs']/'ca.crt'))
    client.on_connect=lambda c,u,f,r,p:loop.call_soon_threadsafe(result.put_nowait,r)
    client.connect_async('localhost',broker['tls_port'],30);client.loop_start()
    try: assert (await asyncio.wait_for(result.get(),5)).is_failure
    finally: client.disconnect();await asyncio.to_thread(client.loop_stop)

async def test_general_mqtt_device_has_only_configured_channels(system,broker):
    from examples.simulator import Simulator as GeneralSimulator
    d=(await system['client'].post('/api/devices',json={'name':'Generic MQTT'})).json()
    r=await system['client'].put(f"/api/devices/{d['id']}/channels/42",json={'name':'Output','type':1,'writable':True})
    assert r.status_code==200,r.text
    async def provisioned():return d['id'] in broker['adapter'].provisioned
    await eventually(provisioned,15)
    sim=GeneralSimulator(d,channels=[{'number':42,'type':1,'writable':True}])
    task=asyncio.create_task(sim.mqtt('localhost',broker['tls_port'],str(system['certs']/'ca.crt')))
    try:
        async def online():return any(row['id']==d['id'] and row['online'] for row in (await system['client'].get('/api/devices')).json())
        await eventually(online)
        r=await system['client'].post(f"/api/devices/{d['id']}/channels/42/write",json={'value':True})
        assert r.status_code==200,r.text
        async def applied():return (await system['client'].get(f"/api/devices/{d['id']}/commands")).json()[0]['status']=='applied'
        await eventually(applied)
        rows=(await system['client'].get(f"/api/devices/{d['id']}/channels")).json()
        assert len(rows)==1 and rows[0]['reported'] is True and sim.telemetry() is None
        assert not task.done()
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_disabled_account_and_deleted_device_revoke_broker_identity(broker):
    from omnilink.platform_models import Account
    from omnilink.db import Device
    system=broker['system'];d=await device(system);await provision(broker,d);rt=system['rt']
    with rt.db.lock,rt.db.session.begin() as s:
        tenant=s.get(Device,d['id']).tenant_id;s.get(Account,tenant).enabled=False
    async def disabled():return broker['adapter'].enabled.get(d['id']) is False
    await eventually(disabled,10)
    with rt.db.lock,rt.db.session.begin() as s:s.get(Account,tenant).enabled=True
    response=await system['client'].delete('/api/devices/'+d['id']);assert response.status_code==200,response.text
    async def removed():return d['id'] not in broker['adapter'].provisioned
    await eventually(removed,10)

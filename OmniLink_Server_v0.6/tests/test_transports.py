import asyncio
import os
import secrets
import ssl
import struct
import pytest
import websockets
from omnilink import onp
from omnilink.native import TCPIO,text8
from conftest import device,eventually

async def handshake(io,d,secret=None,max_frame=4096):
    boot=secrets.token_bytes(16)
    hello=text8(d['id'])+b'\0'+text8('transport-test')+struct.pack('>BIIIH',1,0x3f,0x7fff,max_frame,30)+secrets.token_bytes(16)+boot
    await io.send(onp.Frame(1,1,payload=hello),256)
    ack=await io.receive(256,5);challenge=await io.receive(256,5)
    proof=onp.auth_proof(bytes.fromhex(secret or d['secret']),hello,ack.payload,challenge.payload[:32])
    await io.send(onp.Frame(5,challenge.message_id,payload=b'\x01\x00\x20'+proof,flags=onp.RESPONSE),256)
    return await io.receive(256,5),boot.hex()

async def test_wrong_onp_secret_and_session_spoof(system):
    d=await device(system)
    ctx=ssl.create_default_context(cafile=str(system['certs']/'ca.crt'))
    r,w=await asyncio.open_connection('localhost',system['native_port'],ssl=ctx)
    io=TCPIO(r,w)
    result,boot=await handshake(io,d,'0'*64)
    assert result.type==7 and result.session_id==0
    await io.close()
    assert d['id'] not in system['rt'].native_sessions
    r,w=await asyncio.open_connection('localhost',system['native_port'],ssl=ctx)
    io=TCPIO(r,w);result,boot=await handshake(io,d)
    assert result.type==6
    await io.send(onp.Frame(8,5,session_id=result.session_id^1),4096)
    assert await asyncio.wait_for(r.read(1),3)==b''
    await io.close()

class DeviceWS:
    def __init__(self,ws): self.ws=ws
    async def send(self,f,limit): await self.ws.send(onp.encode_frame(f,limit))
    async def receive(self,limit,timeout): return onp.decode_frame(await asyncio.wait_for(self.ws.recv(),timeout),limit)

async def test_binary_device_websocket_command(system):
    d=await device(system)
    async with websockets.connect(system['url'].replace('http:','ws:')+'/device/onp',proxy=None) as ws:
        io=DeviceWS(ws);ok,boot=await handshake(io,d);assert ok.type==6
        response=await system['client'].post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True,'manual_s':0})
        assert response.status_code==200
        f=await io.receive(4096,5);assert f.type==0x10
        c=onp.decode_write(f.payload)
        await io.send(onp.Frame(0x80,f.message_id,ok.session_id,onp.encode_ack(onp.Ack(c.command_key,c.desired_revision,1)),onp.RESPONSE),4096)
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json();return rows[0]['status']=='applied'
        await eventually(applied)

async def test_live_websocket_tenant_event_and_origin(system):
    d=await device(system)
    cookie='omnilink_session='+system['client'].cookies.get('omnilink_session')
    url=system['url'].replace('http:','ws:')+'/ws/live'
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(url,origin='https://evil.example',additional_headers={'Cookie':cookie},proxy=None): pass
    async with websockets.connect(url,origin=system['url'],additional_headers={'Cookie':cookie},proxy=None) as ws:
        await system['client'].post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True,'manual_s':0})
        import json
        event=json.loads(await asyncio.wait_for(ws.recv(),5))
        assert event['kind']=='command' and event['data']['device_id']==d['id']

@pytest.mark.skipif(os.name!='posix',reason='Pseudo-terminal integration requires POSIX')
async def test_serial_bridge_real_pty_crc_and_command(system):
    import pty
    from examples.serial_bridge import bridge
    master,slave=pty.openpty();path=os.ttyname(slave);os.set_blocking(master,False)
    decoder=onp.SerialDecoder(256);queue=[]
    class SerialChild:
        async def send(self,f,limit): os.write(master,onp.encode_serial(f,256))
        async def receive(self,limit,timeout):
            async def recv():
                while not queue:
                    try: raw=os.read(master,1024)
                    except BlockingIOError: raw=b''
                    if raw: queue.extend(decoder.feed(raw))
                    if not queue: await asyncio.sleep(.01)
                return queue.pop(0)
            return await asyncio.wait_for(recv(),timeout)
    task=asyncio.create_task(bridge(path,115200,'localhost',system['native_port'],str(system['certs']/'ca.crt'),256))
    try:
        await asyncio.sleep(.1);d=await device(system);io=SerialChild();ok,boot=await handshake(io,d,max_frame=256)
        assert ok.type==6
        # Bad serial CRC is discarded; the following valid packet still works.
        damaged=bytearray(onp.encode_serial(onp.Frame(8,9,ok.session_id),256));damaged[-3]^=1
        os.write(master,damaged)
        await io.send(onp.Frame(8,10,ok.session_id),256)
        pong=await io.receive(256,5);assert pong.type==9 and pong.message_id==10
        response=await system['client'].post(f"/api/devices/{d['id']}/channels/0/write",json={'value':True,'manual_s':0});assert response.status_code==200
        f=await io.receive(256,5);c=onp.decode_write(f.payload)
        await io.send(onp.Frame(0x80,f.message_id,ok.session_id,onp.encode_ack(onp.Ack(c.command_key,c.desired_revision,1)),onp.RESPONSE),256)
        async def applied():
            rows=(await system['client'].get(f"/api/devices/{d['id']}/commands")).json();return rows[0]['status']=='applied'
        await eventually(applied)
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True);os.close(master);os.close(slave)

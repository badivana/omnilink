"""One serial child to one authenticated upstream ONP TLS connection.

The bridge does not hold device secrets: the child performs the ONP handshake.
COBS + complete-frame CRC protect the serial link. Restart on disconnect.
"""
import argparse
import asyncio
import ssl
import serial
from omnilink import onp
from omnilink.native import TCPIO

async def bridge(port,baud,host,tcp_port,ca,maximum):
    link=serial.Serial(port,baudrate=baud,timeout=.2,write_timeout=3)
    ctx=ssl.create_default_context(cafile=ca)
    r,w=await asyncio.open_connection(host,tcp_port,ssl=ctx,server_hostname=host)
    io=TCPIO(r,w);decoder=onp.SerialDecoder(maximum)
    async def upstream():
        while True:
            data=await asyncio.to_thread(link.read,1024)
            for frame in decoder.feed(data):
                if frame.type==1:
                    from omnilink.native import Cursor
                    p=Cursor(frame.payload);p.text();p.u(1);p.text(maximum=32);p.u(1);p.u(4);p.u(4)
                    advertised=p.u(4)
                    if advertised>maximum: raise onp.ProtocolError('Child advertises a frame larger than bridge capacity')
                await io.send(frame,maximum)
    async def downstream():
        while True:
            frame=await io.receive(maximum,300)
            encoded=onp.encode_serial(frame,maximum)
            await asyncio.to_thread(link.write,encoded)
    tasks=[asyncio.create_task(upstream()),asyncio.create_task(downstream())]
    try:
        done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done: task.result()
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        link.close();await io.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--baud',type=int,default=115200);p.add_argument('--host',default='localhost');p.add_argument('--port',type=int,default=7443);p.add_argument('--ca',default='data/certs/ca.crt');p.add_argument('--max-frame',type=int,default=256)
    a=p.parse_args()
    try: asyncio.run(bridge(a.serial,a.baud,a.host,a.port,a.ca,a.max_frame))
    except KeyboardInterrupt: pass

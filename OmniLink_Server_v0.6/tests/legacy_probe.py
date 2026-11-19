"""Read-only synthetic legacy frame probe based on supplied source layouts.

This is an independent parser for inspection fixtures, not a compatibility
adapter, server, or Blynk client library. No Blynk implementation is included.
"""
from dataclasses import dataclass
import struct

@dataclass(frozen=True)
class LegacyFrame:
    command: int
    message_id: int
    body: bytes = b''
    status: int | None = None

def parse_legacy(data,application=False):
    width=7 if application else 5
    if len(data)<width: raise ValueError('Truncated legacy header')
    command,message_id=struct.unpack('>BH',data[:3])
    size_or_status=int.from_bytes(data[3:width],'big')
    if command==0:
        if len(data)!=width: raise ValueError('Response has no body')
        return LegacyFrame(command,message_id,status=size_or_status)
    if len(data)!=width+size_or_status: raise ValueError('Legacy length mismatch')
    return LegacyFrame(command,message_id,bytes(data[width:]))

def inspect_virtual_write(frame):
    if frame.command!=20: raise ValueError('Not legacy HARDWARE')
    parts=frame.body.decode('utf-8').split('\0',2)
    if len(parts)!=3 or parts[0]!='vw': raise ValueError('Not legacy virtual write')
    return {'channel':int(parts[1]),'value_text':parts[2]}

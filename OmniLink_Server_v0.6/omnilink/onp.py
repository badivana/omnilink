"""OmniLink ONP v1 byte-level codec, using the Python standard library.

Authentication state, policy, clocks, and delivery live in the server's native
session and core modules. This module handles bounded frames and typed values.
"""
from dataclasses import dataclass
from enum import IntEnum
import hashlib
import hmac
import json
import math
import struct

MAGIC = b'ON'
VERSION = 1
HEADER_SIZE = 20
MAX_FRAME = 65536
RESPONSE = 1
ACK_REQUESTED = 2
RETRANSMISSION = 4

class ProtocolError(ValueError):
    pass

class Type(IntEnum):
    BOOL=1; INT8=2; UINT8=3; INT16=4; UINT16=5; INT32=6; UINT32=7
    INT64=8; UINT64=9; FLOAT32=10; FLOAT64=11; STRING=12; BYTES=13
    JSON=14; TIMESTAMP=15

FORMATS = {Type.INT8:'b', Type.UINT8:'B', Type.INT16:'h', Type.UINT16:'H',
           Type.INT32:'i', Type.UINT32:'I', Type.INT64:'q', Type.UINT64:'Q',
           Type.FLOAT32:'f', Type.FLOAT64:'d', Type.TIMESTAMP:'Q'}

def _int(value, bits, nonzero=False):
    if type(value) is not int or not (int(nonzero) <= value < (1 << bits)):
        raise ProtocolError(f'Expected unsigned {bits}-bit integer')
    return value

def _bound(max_frame):
    if type(max_frame) is not int or not 256 <= max_frame <= MAX_FRAME:
        raise ProtocolError('max_frame must be in 256..65536')

def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

@dataclass(frozen=True)
class Frame:
    type: int
    message_id: int
    session_id: int = 0
    payload: bytes = b''
    flags: int = 0
    codec: int = 0

def _header_fields(header, max_frame):
    _bound(max_frame)
    if len(header) != HEADER_SIZE:
        raise ProtocolError('Truncated header')
    if crc16(header[:18]) != int.from_bytes(header[18:20], 'big'):
        raise ProtocolError('Header CRC mismatch')
    magic, version, flags, kind, codec, mid, sid, length = struct.unpack('>2sBBBBIII',header[:18])
    if magic != MAGIC or version != VERSION:
        raise ProtocolError('Bad magic/version')
    if flags & ~7 or codec not in (0,1,2) or mid == 0:
        raise ProtocolError('Invalid flags/codec/message ID')
    if length > max_frame - HEADER_SIZE:
        raise ProtocolError('Frame exceeds negotiated receive limit')
    return kind, mid, sid, length, flags, codec

def encode_frame(frame, max_frame=4096):
    _bound(max_frame)
    for value,bits in [(frame.type,8),(frame.message_id,32),(frame.session_id,32),
                       (frame.flags,8),(frame.codec,8)]:
        _int(value,bits)
    if not frame.message_id or frame.flags & ~7 or frame.codec not in (0,1,2):
        raise ProtocolError('Invalid frame fields')
    if not isinstance(frame.payload,bytes):
        raise ProtocolError('Payload must be bytes')
    if len(frame.payload) > max_frame-HEADER_SIZE:
        raise ProtocolError('Frame exceeds negotiated limit')
    header = struct.pack('>2sBBBBIII',MAGIC,VERSION,frame.flags,frame.type,frame.codec,
                         frame.message_id,frame.session_id,len(frame.payload))
    return header + struct.pack('>H',crc16(header)) + frame.payload

def decode_frame(data, max_frame=4096):
    if len(data) < HEADER_SIZE:
        raise ProtocolError('Truncated frame')
    kind,mid,sid,length,flags,codec = _header_fields(data[:20],max_frame)
    if len(data) != HEADER_SIZE+length:
        raise ProtocolError('Frame length mismatch')
    return Frame(kind,mid,sid,bytes(data[20:]),flags,codec)

class StreamDecoder:
    """Incremental, bounded native parser. Caller supplies read deadlines.

    A malformed header permanently fails this instance, matching the contract
    to close the native connection instead of scanning for another magic byte.
    """
    def __init__(self,max_frame=4096):
        _bound(max_frame)
        self.max_frame=max_frame
        self.buffer=bytearray()
        self.expected=HEADER_SIZE
        self.failed=False

    def feed(self,data):
        if self.failed:
            raise ProtocolError('Decoder failed; replace connection')
        frames=[]
        view=memoryview(data)
        position=0
        try:
            while position<len(view):
                count=min(self.expected-len(self.buffer),len(view)-position)
                self.buffer.extend(view[position:position+count])
                position+=count
                if len(self.buffer)<self.expected:
                    continue
                if self.expected==HEADER_SIZE:
                    fields=_header_fields(self.buffer,self.max_frame)
                    self.expected=HEADER_SIZE+fields[3]
                    if len(self.buffer)<self.expected:
                        continue
                frames.append(decode_frame(bytes(self.buffer),self.max_frame))
                self.buffer.clear()
                self.expected=HEADER_SIZE
        except ProtocolError:
            self.failed=True
            self.buffer.clear()
            raise
        return frames

def cobs_encode(data):
    result=bytearray([0])
    code_index=0
    code=1
    for byte in data:
        if byte==0:
            result[code_index]=code
            code_index=len(result)
            result.append(0)
            code=1
        else:
            result.append(byte)
            code+=1
            if code==255:
                result[code_index]=code
                code_index=len(result)
                result.append(0)
                code=1
    result[code_index]=code
    return bytes(result)

def cobs_decode(data):
    if not data or 0 in data:
        raise ProtocolError('Invalid COBS block')
    result=bytearray()
    index=0
    while index<len(data):
        code=data[index]
        index+=1
        end=index+code-1
        if end>len(data):
            raise ProtocolError('COBS run exceeds block')
        result.extend(data[index:end])
        index=end
        if code != 255 and index<len(data):
            result.append(0)
    return bytes(result)

def encode_serial(frame,max_frame=256):
    native=encode_frame(frame,max_frame)
    return cobs_encode(native+struct.pack('>H',crc16(native)))+b'\0'

def decode_serial(block,max_frame=256):
    _bound(max_frame)
    decoded_limit=max_frame+2
    encoded_limit=decoded_limit+decoded_limit//254+1
    if not block.endswith(b'\0') or len(block)-1>encoded_limit:
        raise ProtocolError('Missing delimiter or oversize block')
    native_and_crc=cobs_decode(block[:-1])
    if len(native_and_crc)<22 or len(native_and_crc)>decoded_limit:
        raise ProtocolError('Invalid decoded serial length')
    native=native_and_crc[:-2]
    if crc16(native)!=int.from_bytes(native_and_crc[-2:],'big'):
        raise ProtocolError('Serial CRC mismatch')
    return decode_frame(native,max_frame)

class SerialDecoder:
    """Discard corrupt/oversize blocks and resume at the next 00 delimiter."""
    def __init__(self,max_frame=256):
        _bound(max_frame)
        self.max_frame=max_frame
        length=max_frame+2
        self.encoded_limit=length+length//254+1
        self.buffer=bytearray()
        self.discarding=False
        self.error_count=0

    def feed(self,data):
        frames=[]
        for byte in data:
            if byte==0:
                if self.discarding:
                    self.discarding=False
                elif self.buffer:
                    try:
                        frames.append(decode_serial(bytes(self.buffer)+b'\0',self.max_frame))
                    except ProtocolError:
                        self.error_count+=1
                self.buffer.clear()
            elif not self.discarding:
                if len(self.buffer)>=self.encoded_limit:
                    self.buffer.clear()
                    self.discarding=True
                    self.error_count+=1
                else:
                    self.buffer.append(byte)
        return frames

def _json_pairs(items):
    result={}
    for key,value in items:
        if key in result:
            raise ProtocolError('Duplicate JSON key')
        result[key]=value
    return result

def strict_json_loads(data,max_depth=8):
    def invalid_constant(value):
        raise ProtocolError('Non-finite JSON number')
    try:
        obj=json.loads(data,object_pairs_hook=_json_pairs,parse_constant=invalid_constant)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise ProtocolError('Invalid JSON') from exc
    def check(value,depth=0):
        if depth>max_depth:
            raise ProtocolError('JSON nesting limit exceeded')
        if isinstance(value,float) and not math.isfinite(value):
            raise ProtocolError('Non-finite JSON number')
        if isinstance(value,dict):
            for child in value.values(): check(child,depth+1)
        elif isinstance(value,list):
            for child in value: check(child,depth+1)
    check(obj)
    return obj

def encode_value(kind,value):
    try:
        kind=Type(kind)
        if kind==Type.BOOL:
            if type(value) is not bool: raise ProtocolError('BOOL requires bool')
            raw=bytes([int(value)])
        elif kind in FORMATS:
            if kind in (Type.FLOAT32,Type.FLOAT64):
                if type(value) not in (int,float) or not math.isfinite(value):
                    raise ProtocolError('Float requires finite numeric value')
            elif type(value) is not int:
                raise ProtocolError('Integer requires int, not bool')
            raw=struct.pack('>'+FORMATS[kind],value)
        elif kind==Type.STRING:
            if type(value) is not str: raise ProtocolError('STRING requires str')
            raw=value.encode('utf-8')
        elif kind==Type.BYTES:
            if not isinstance(value,bytes): raise ProtocolError('BYTES requires bytes')
            raw=value
        else:
            raw=json.dumps(value,separators=(',',':'),allow_nan=False,ensure_ascii=False).encode('utf-8')
            strict_json_loads(raw)
        if len(raw)>65535: raise ProtocolError('Value too large')
        return bytes([kind])+struct.pack('>H',len(raw))+raw
    except (ValueError,TypeError,OverflowError,struct.error,UnicodeError) as exc:
        raise ProtocolError('Invalid typed value') from exc

def decode_value(data,offset=0):
    if offset<0 or offset+3>len(data): raise ProtocolError('Truncated value header')
    try:
        kind=Type(data[offset])
        length=int.from_bytes(data[offset+1:offset+3],'big')
        end=offset+3+length
        if end>len(data): raise ProtocolError('Truncated typed value')
        raw=data[offset+3:end]
        if kind==Type.BOOL:
            if length!=1 or raw[0] not in (0,1): raise ProtocolError('Invalid BOOL')
            value=bool(raw[0])
        elif kind in FORMATS:
            if length!=struct.calcsize('>'+FORMATS[kind]): raise ProtocolError('Wrong scalar width')
            value=struct.unpack('>'+FORMATS[kind],raw)[0]
            if isinstance(value,float) and not math.isfinite(value): raise ProtocolError('Non-finite float')
        elif kind==Type.STRING:
            value=raw.decode('utf-8')
        elif kind==Type.BYTES:
            value=bytes(raw)
        else:
            value=strict_json_loads(raw)
        return kind,value,end
    except (ValueError,UnicodeError,struct.error) as exc:
        raise ProtocolError('Malformed typed value') from exc

def encode_channel(channel,kind,value):
    _int(channel,16)
    if channel>1023: raise ProtocolError('Channel outside V0..V1023')
    return struct.pack('>H',channel)+encode_value(kind,value)

def decode_channel(data,offset=0):
    if offset<0 or offset+2>len(data): raise ProtocolError('Truncated channel')
    channel=int.from_bytes(data[offset:offset+2],'big')
    if channel>1023: raise ProtocolError('Invalid channel')
    kind,value,end=decode_value(data,offset+2)
    return channel,kind,value,end

def _key(key,nonzero=False):
    if not isinstance(key,bytes) or len(key)!=16 or (nonzero and key==bytes(16)):
        raise ProtocolError('Invalid command key')

@dataclass(frozen=True)
class Write:
    command_key: bytes
    desired_revision: int
    expires_at_ms: int
    channel: int
    type: Type
    value: object

def encode_write(write):
    _key(write.command_key,True)
    _int(write.desired_revision,32,True)
    _int(write.expires_at_ms,64)
    return write.command_key+struct.pack('>IQ',write.desired_revision,write.expires_at_ms)+encode_channel(write.channel,write.type,write.value)

def decode_write(data):
    if len(data)<33: raise ProtocolError('Truncated write')
    revision,expiry=struct.unpack('>IQ',data[16:28])
    channel,kind,value,end=decode_channel(data,28)
    if end!=len(data): raise ProtocolError('Trailing write bytes')
    result=Write(bytes(data[:16]),revision,expiry,channel,kind,value)
    _key(result.command_key,True); _int(revision,32,True)
    return result

@dataclass(frozen=True)
class Report:
    sequence: int
    observed_at_ms: int
    applied_command_key: bytes
    desired_revision: int
    channel: int
    type: Type
    value: object

def _report_fields(report):
    _int(report.sequence,32,True)
    _int(report.observed_at_ms,64)
    _int(report.desired_revision,32)
    _key(report.applied_command_key)
    if (report.applied_command_key==bytes(16)) != (report.desired_revision==0):
        raise ProtocolError('Report key/revision association mismatch')

def encode_report(report):
    _report_fields(report)
    return struct.pack('>IQ',report.sequence,report.observed_at_ms)+report.applied_command_key+struct.pack('>I',report.desired_revision)+encode_channel(report.channel,report.type,report.value)

def decode_report(data):
    if len(data)<37: raise ProtocolError('Truncated report')
    sequence,observed=struct.unpack('>IQ',data[:12])
    revision=int.from_bytes(data[28:32],'big')
    channel,kind,value,end=decode_channel(data,32)
    if end!=len(data): raise ProtocolError('Trailing report bytes')
    result=Report(sequence,observed,bytes(data[12:28]),revision,channel,kind,value)
    _report_fields(result)
    return result

@dataclass(frozen=True)
class Ack:
    command_key: bytes
    revision: int
    status: int
    error_code: int = 0

def _ack_fields(ack):
    _key(ack.command_key)
    _int(ack.revision,32); _int(ack.status,8); _int(ack.error_code,16)
    if ack.status not in (0,1,2): raise ProtocolError('Invalid ACK status')
    if (ack.status==2) != (ack.error_code!=0): raise ProtocolError('ACK error/status mismatch')
    if (ack.command_key==bytes(16)) != (ack.revision==0):
        raise ProtocolError('ACK key/revision mismatch')

def encode_ack(ack):
    _ack_fields(ack)
    return ack.command_key+struct.pack('>IBH',ack.revision,ack.status,ack.error_code)

def decode_ack(data):
    if len(data)!=23: raise ProtocolError('ACK must be 23 bytes')
    revision,status,error=struct.unpack('>IBH',data[16:])
    result=Ack(bytes(data[:16]),revision,status,error)
    _ack_fields(result)
    return result

def auth_proof(secret,hello_payload,hello_ack_payload,server_nonce):
    if len(secret)!=32 or len(server_nonce)!=32:
        raise ProtocolError('Authentication secret and nonce must be 32 bytes')
    transcript=b'OmniLink-ONP1-auth\0'+hashlib.sha256(hello_payload).digest()+hashlib.sha256(hello_ack_payload).digest()+server_nonce
    return hmac.new(secret,transcript,hashlib.sha256).digest()

def verify_auth(secret,hello_payload,hello_ack_payload,server_nonce,proof):
    if len(proof)!=32: return False
    return hmac.compare_digest(auth_proof(secret,hello_payload,hello_ack_payload,server_nonce),proof)

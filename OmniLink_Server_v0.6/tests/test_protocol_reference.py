import binascii
import hashlib
import hmac
import random
import struct
import unittest

from omnilink.onp import *
from legacy_probe import parse_legacy, inspect_virtual_write

PING_HEX='4f4e01000800000000010102030400000000ea6c'
WRITE_HEX='4f4e010210000000000101020304000000228e09000102030405060708090a0b0c0d0e0f000000010000000000000000000001000101'
SERIAL_HEX='064f4e010210010101060101020304010104228e09100102030405060708090a0b0c0d0e0f010102010101010101010101010201050101f47000'

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key=bytes(range(16))
        self.write=Write(self.key,1,0,0,Type.BOOL,True)
        self.frame=Frame(0x10,1,0x01020304,encode_write(self.write),ACK_REQUESTED)

    def test_crc_known_vector_and_independent_library(self):
        self.assertEqual(crc16(b'123456789'),0x29B1)
        self.assertEqual(crc16(b''),0xFFFF)
        rng=random.Random(23)
        for size in (1,18,34,254,4096):
            raw=bytes(rng.randrange(256) for _ in range(size))
            self.assertEqual(crc16(raw),binascii.crc_hqx(raw,0xFFFF))

    def test_golden_ping_frame(self):
        frame=Frame(8,1,0x01020304)
        self.assertEqual(encode_frame(frame).hex(),PING_HEX)
        self.assertEqual(decode_frame(bytes.fromhex(PING_HEX)),frame)

    def test_golden_write_and_serial_frames(self):
        self.assertEqual(encode_frame(self.frame).hex(),WRITE_HEX)
        self.assertEqual(encode_serial(self.frame).hex(),SERIAL_HEX)
        self.assertEqual(decode_serial(bytes.fromhex(SERIAL_HEX)),self.frame)
        self.assertEqual(len(bytes.fromhex(WRITE_HEX)),54)

    def test_header_bit_corruption(self):
        raw=bytearray.fromhex(PING_HEX)
        for index in range(20):
            for bit in range(8):
                corrupted=raw.copy(); corrupted[index]^=1<<bit
                with self.subTest(index=index,bit=bit),self.assertRaises(ProtocolError):
                    decode_frame(corrupted)

    def test_invalid_headers_even_with_correct_crc(self):
        for offset,value in ((0,0),(2,2),(3,0x80),(5,9)):
            raw=bytearray.fromhex(PING_HEX); raw[offset]=value
            raw[18:20]=binascii.crc_hqx(raw[:18],0xFFFF).to_bytes(2,'big')
            with self.assertRaises(ProtocolError): decode_frame(raw)
        with self.assertRaises(ProtocolError): encode_frame(Frame(8,0))

    def test_exact_frame_length_and_cap(self):
        raw=bytes.fromhex(WRITE_HEX)
        for invalid in (raw[:-1],raw+b'x',raw[:19]):
            with self.assertRaises(ProtocolError): decode_frame(invalid)
        with self.assertRaises(ProtocolError): encode_frame(Frame(0x20,1,payload=b'x'*237),256)
        self.assertEqual(len(encode_frame(Frame(0x20,1,payload=b'x'*236),256)),256)

    def test_partial_and_coalesced_stream_frames(self):
        raw=bytes.fromhex(WRITE_HEX)+bytes.fromhex(PING_HEX)
        for cut in range(len(raw)+1):
            decoder=StreamDecoder(256)
            results=decoder.feed(raw[:cut])+decoder.feed(raw[cut:])
            self.assertEqual(results,[self.frame,Frame(8,1,0x01020304)])
        decoder=StreamDecoder(256); results=[]
        for byte in raw: results+=decoder.feed(bytes([byte]))
        self.assertEqual(len(results),2)

    def test_reject_huge_claim_from_header_alone(self):
        raw=bytearray.fromhex(PING_HEX)
        raw[14:18]=struct.pack('>I',0xFFFFFFFF)
        raw[18:20]=binascii.crc_hqx(raw[:18],0xFFFF).to_bytes(2,'big')
        decoder=StreamDecoder(256)
        with self.assertRaises(ProtocolError): decoder.feed(raw)
        self.assertEqual(len(decoder.buffer),0)
        with self.assertRaises(ProtocolError): decoder.feed(bytes.fromhex(PING_HEX))

    def test_cobs_known_blocks_and_boundaries(self):
        vectors=[(b'',b'\x01'),(b'\0',b'\x01\x01'),
                 (b'\x11\x22\0\x33',b'\x03\x11\x22\x02\x33')]
        for raw,encoded in vectors:
            self.assertEqual(cobs_encode(raw),encoded)
            self.assertEqual(cobs_decode(encoded),raw)
        for size in (253,254,255,508,1024):
            raw=b'\x41'*size
            encoded=cobs_encode(raw)
            self.assertNotIn(0,encoded)
            self.assertLessEqual(len(encoded),size+size//254+1)
            self.assertEqual(cobs_decode(encoded),raw)

    def test_cobs_invalid_blocks(self):
        for block in (b'',b'\0',b'\x04ab',b'\x01\0'):
            with self.assertRaises(ProtocolError): cobs_decode(block)

    def test_serial_payload_corruption_and_resync(self):
        raw=bytes.fromhex(WRITE_HEX)
        # Keep the header intact but change payload without updating trailer CRC.
        crc=crc16(raw).to_bytes(2,'big')
        bad=bytearray(raw); bad[-1]^=1
        invalid=cobs_encode(bytes(bad)+crc)+b'\0'
        with self.assertRaises(ProtocolError): decode_serial(invalid)
        decoder=SerialDecoder(256)
        good=bytes.fromhex(SERIAL_HEX)
        self.assertEqual(decoder.feed(invalid+good),[self.frame])
        self.assertEqual(decoder.error_count,1)

    def test_serial_oversize_resync_and_split_input(self):
        decoder=SerialDecoder(256)
        self.assertEqual(decoder.feed(b'A'*100000),[])
        self.assertEqual(len(decoder.buffer),0)
        self.assertEqual(decoder.feed(b'\0'+bytes.fromhex(SERIAL_HEX)),[self.frame])
        self.assertEqual(decoder.error_count,1)
        for cut in range(len(bytes.fromhex(SERIAL_HEX))+1):
            decoder=SerialDecoder(256); raw=bytes.fromhex(SERIAL_HEX)
            self.assertEqual(decoder.feed(raw[:cut])+decoder.feed(raw[cut:]),[self.frame])

    def test_all_scalar_types(self):
        cases=[(Type.BOOL,True),(Type.INT8,-128),(Type.UINT8,255),
               (Type.INT16,-32768),(Type.UINT16,65535),(Type.INT32,-2147483648),
               (Type.UINT32,4294967295),(Type.INT64,-(1<<63)),(Type.UINT64,(1<<64)-1),
               (Type.FLOAT32,27.5),(Type.FLOAT64,1.25),(Type.STRING,'filter\0air'),
               (Type.BYTES,b'\0\xff'),(Type.JSON,{'mode':'filter'}),(Type.TIMESTAMP,1790879212000)]
        for kind,value in cases:
            with self.subTest(kind=kind):
                encoded=encode_value(kind,value)
                decoded=decode_value(encoded)
                self.assertEqual(decoded,(kind,value,len(encoded)))
        self.assertEqual(encode_value(Type.UINT16,0x1234).hex(),'0500021234')
        self.assertEqual(encode_value(Type.BOOL,True).hex(),'01000101')

    def test_bad_values_and_channel_bounds(self):
        for kind,value in [(Type.BOOL,1),(Type.UINT8,256),(Type.UINT16,-1),
                           (Type.UINT32,True),(Type.TIMESTAMP,-1),(Type.FLOAT32,float('inf')),
                           (Type.FLOAT64,float('nan')),(Type.STRING,b'x')]:
            with self.subTest(kind=kind),self.assertRaises(ProtocolError): encode_value(kind,value)
        for raw in (bytes.fromhex('01000102'),bytes.fromhex('05000101'),
                    bytes.fromhex('0c0001ff'),bytes.fromhex('ff0000'),bytes.fromhex('010001')):
            with self.assertRaises(ProtocolError): decode_value(raw)
        with self.assertRaises(ProtocolError): encode_channel(1024,Type.BOOL,True)
        with self.assertRaises(ProtocolError): decode_channel(bytes.fromhex('040001000101'))

    def test_json_rejects_duplicate_nonfinite_and_deep_values(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":1e999}','['*10+'0'+']'*10):
            with self.assertRaises(ProtocolError): strict_json_loads(raw)
        self.assertEqual(strict_json_loads('{"a":null}'),{'a':None})

    def test_write_key_revision_and_trailing_bytes(self):
        self.assertEqual(decode_write(encode_write(self.write)),self.write)
        with self.assertRaises(ProtocolError): encode_write(Write(bytes(16),1,0,0,Type.BOOL,True))
        with self.assertRaises(ProtocolError): encode_write(Write(self.key,0,0,0,Type.BOOL,True))
        with self.assertRaises(ProtocolError): decode_write(encode_write(self.write)+b'\0')

    def test_report_association_and_roundtrip(self):
        report=Report(1,0,self.key,1,0,Type.BOOL,True)
        self.assertEqual(decode_report(encode_report(report)),report)
        with self.assertRaises(ProtocolError): encode_report(Report(1,0,bytes(16),1,0,Type.BOOL,True))
        with self.assertRaises(ProtocolError): encode_report(Report(0,0,bytes(16),0,0,Type.BOOL,True))

    def test_ack_semantics(self):
        for ack in (Ack(self.key,1,0),Ack(self.key,1,1),Ack(self.key,1,2,8),Ack(bytes(16),0,0)):
            self.assertEqual(decode_ack(encode_ack(ack)),ack)
        for ack in (Ack(self.key,1,2),Ack(self.key,1,1,8),Ack(bytes(16),1,0)):
            with self.assertRaises(ProtocolError): encode_ack(ack)

    def test_auth_fixed_transcript_and_mutation(self):
        secret=bytes(range(32)); nonce=bytes(range(32,64))
        expected=bytes.fromhex('740259b6f64ffb96389ba49e13e1498f85bf4bf7f7c0b0b6ad1afeba9e8db7ac')
        self.assertEqual(auth_proof(secret,b'hello',b'hello_ack',nonce),expected)
        self.assertTrue(verify_auth(secret,b'hello',b'hello_ack',nonce,expected))
        self.assertFalse(verify_auth(secret,b'hello',b'changed',nonce,expected))
        self.assertFalse(verify_auth(secret,b'hello',b'hello_ack',bytes(32),expected))
        self.assertFalse(verify_auth(secret,b'hello',b'hello_ack',nonce,expected[:-1]))

    def test_hmac_independent_published_primitive_vector(self):
        digest=hmac.new(b'\x0b'*20,b'Hi There',hashlib.sha256).hexdigest()
        self.assertEqual(digest,'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7')

    def test_legacy_hardware_response_and_app_layouts(self):
        frame=parse_legacy(bytes.fromhex('1400010006')+b'vw\x000\x001')
        self.assertEqual(inspect_virtual_write(frame),{'channel':0,'value_text':'1'})
        self.assertEqual(parse_legacy(bytes.fromhex('00000100c8')).status,200)
        app=parse_legacy(bytes.fromhex('14000200000006')+b'vw\x000\x001',application=True)
        self.assertEqual(app.body,frame.body)
        with self.assertRaises(ValueError): parse_legacy(bytes.fromhex('1400010006')+b'vw')

if __name__=='__main__':
    unittest.main(verbosity=2)

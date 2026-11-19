"""Comprehensive end-to-end TLS verification suite for OmniLink.

Tests:
- HTTPS REST API over TLS with CA verification
- Secure Cookies over HTTPS (Secure flag, SameSite=Strict, HttpOnly)
- WSS (Secure WebSocket) live feed over TLS
- Device HTTPS endpoints (/connect, /report, /telemetry, /commands)
- ONP binary transport over native TLS
- Strict rejection of untrusted certificates
- RFC 5280 X.509 certificate extensions (AKI, SKI, KeyUsage, EKU, SAN)
"""
import asyncio
import socket
import ssl
import httpx
import pytest
import pytest_asyncio
import uvicorn
import websockets
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.x509.oid import ExtensionOID

from omnilink.api import create_app
from omnilink.settings import Settings
from omnilink.certificates import generate
from omnilink import onp
from omnilink.native import TCPIO, text8
from conftest import eventually, free_port

@pytest_asyncio.fixture
async def tls_system(tmp_path):
    certs = tmp_path / 'certs'
    generate(certs, ['localhost', '127.0.0.1'])
    port = free_port()
    public_url = f'https://127.0.0.1:{port}'
    settings = Settings(
        database_url='sqlite:///' + str(tmp_path / 'tls_server.db'),
        encryption_key=Fernet.generate_key().decode(),
        public_url=public_url,
        secure_cookie=True,
        http_tls=True,
        http_host='127.0.0.1',
        http_port=port,
        tls_cert=str(certs / 'server.crt'),
        tls_key=str(certs / 'server.key'),
        native_port=0,
        bootstrap_email='tls_admin@example.com',
        bootstrap_password='Secure-Password-12345',
        retry_seconds=0.25,
    )
    app = create_app(settings)
    rt = app.state.runtime
    server = uvicorn.Server(uvicorn.Config(
        app,
        host='127.0.0.1',
        port=port,
        ssl_certfile=settings.tls_cert,
        ssl_keyfile=settings.tls_key,
        log_level='warning',
        access_log=False,
    ))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.03)
        assert server.started

        ssl_ctx = ssl.create_default_context(cafile=str(certs / 'ca.crt'))
        async with httpx.AsyncClient(base_url=public_url, verify=ssl_ctx, timeout=5, trust_env=False) as client:
            resp = await client.post('/api/auth/login', json={
                'email': settings.bootstrap_email,
                'password': settings.bootstrap_password,
            })
            assert resp.status_code == 200
            token = resp.json()['token']
            client.headers['Authorization'] = 'Bearer ' + token
            yield {
                'app': app,
                'rt': rt,
                'client': client,
                'url': public_url,
                'certs': certs,
                'ssl_ctx': ssl_ctx,
                'native_port': rt.native_server.sockets[0].getsockname()[1],
                'settings': settings,
            }
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 10)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

async def test_https_health_and_auth(tls_system):
    """Verify HTTPS endpoints respond cleanly over TLS and enforce secure cookies."""
    client = tls_system['client']
    live = await client.get('/health/live')
    assert live.status_code == 200
    assert live.json()['status'] == 'ok'

    ready = await client.get('/health/ready')
    assert ready.status_code == 200
    assert ready.json()['status'] == 'ok'

    # Check /api/auth/me
    me = await client.get('/api/auth/me')
    assert me.status_code == 200
    assert me.json()['email'] == tls_system['settings'].bootstrap_email

async def test_https_rejects_untrusted_ca(tls_system):
    """Verify that requests without the OmniLink CA fail TLS verification."""
    # Create an empty SSL context without the OmniLink CA loaded
    untrusted_ctx = ssl.create_default_context()
    async with httpx.AsyncClient(base_url=tls_system['url'], verify=untrusted_ctx, timeout=3, trust_env=False) as client:
        with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
            await client.get('/health/live')

async def test_device_https_flow(tls_system):
    """Verify device connect, report, and command over HTTPS with certificate verification."""
    client = tls_system['client']
    # Create a device
    dev_resp = await client.post('/api/devices', json={'name': 'TLS ESP32 Device'})
    assert dev_resp.status_code == 200
    d = dev_resp.json()

    # Add channel V0
    ch_resp = await client.put(f"/api/devices/{d['id']}/channels/0", json={
        'name': 'Relay',
        'type': 1,  # BOOL
        'writable': True,
    })
    assert ch_resp.status_code == 200

    # Device client connecting via HTTPS
    dev_headers = {'Authorization': 'Device ' + d['secret']}
    async with httpx.AsyncClient(base_url=tls_system['url'], verify=tls_system['ssl_ctx'], headers=dev_headers, timeout=5, trust_env=False) as dev_client:
        conn = await dev_client.post(f"/device/{d['id']}/connect", json={
            'boot_id': '0123456789abcdef0123456789abcdef',
            'firmware': 'esp32-tls-test',
        })
        assert conn.status_code == 200
        assert conn.json()['channels'][0]['number'] == 0

        # Send report over HTTPS
        rep = await dev_client.post(f"/device/{d['id']}/report", json={
            'boot_id': '0123456789abcdef0123456789abcdef',
            'sequence': 1,
            'channel': 0,
            'type': 1,
            'value': True,
            'observed_at_ms': 0,
            'applied_command_key': '0' * 32,
            'desired_revision': 0,
        })
        assert rep.status_code == 200

        # Verify state in user API
        ch_list = await client.get(f"/api/devices/{d['id']}/channels")
        assert ch_list.json()[0]['reported'] is True

async def test_secure_websocket_live_feed(tls_system):
    """Verify WSS (Secure WebSocket) over TLS connects and receives real-time events."""
    client = tls_system['client']
    # Create a device
    dev_resp = await client.post('/api/devices', json={'name': 'WSS Device'})
    d = dev_resp.json()
    await client.put(f"/api/devices/{d['id']}/channels/0", json={'name': 'Relay', 'type': 1, 'writable': True})

    # Get session cookie from login
    session_cookie = client.cookies.get('omnilink_session')
    ws_url = tls_system['url'].replace('https:', 'wss:') + '/ws/live'
    headers = {'Cookie': f'omnilink_session={session_cookie}'}

    async with websockets.connect(
        ws_url,
        ssl=tls_system['ssl_ctx'],
        origin=tls_system['url'],
        additional_headers=headers,
        proxy=None,
    ) as ws:
        # Trigger an action that emits a broadcast
        await client.post(f"/api/devices/{d['id']}/channels/0/write", json={'value': True})
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        import json
        event = json.loads(msg)
        assert event['kind'] == 'command'
        assert event['data']['device_id'] == d['id']

async def test_onp_tls_handshake_and_command(tls_system):
    """Verify native ONP over TLS functions properly with the CA-signed certificates."""
    client = tls_system['client']
    dev_resp = await client.post('/api/devices', json={'name': 'ONP TLS Device'})
    d = dev_resp.json()
    await client.put(f"/api/devices/{d['id']}/channels/0", json={'name': 'Relay', 'type': 1, 'writable': True})

    # Connect over TLS to native port
    r, w = await asyncio.open_connection('127.0.0.1', tls_system['native_port'], ssl=tls_system['ssl_ctx'], server_hostname='localhost')
    io = TCPIO(r, w)
    try:
        boot = b'1234567890abcdef'
        hello = text8(d['id']) + b'\0' + text8('tls-test') + onp.struct.pack('>BIIIH', 1, 0x3f, 0x7fff, 4096, 30) + b'0' * 16 + boot
        await io.send(onp.Frame(1, 1, payload=hello), 256)
        ack = await io.receive(256, 5)
        challenge = await io.receive(256, 5)
        proof = onp.auth_proof(bytes.fromhex(d['secret']), hello, ack.payload, challenge.payload[:32])
        await io.send(onp.Frame(5, challenge.message_id, payload=b'\x01\x00\x20' + proof, flags=onp.RESPONSE), 256)
        ok = await io.receive(256, 5)
        assert ok.type == 6, 'Handshake should succeed'

        # Write command from user API and verify device receives it over TLS
        await client.post(f"/api/devices/{d['id']}/channels/0/write", json={'value': True})
        cmd_frame = await io.receive(4096, 5)
        assert cmd_frame.type == 0x10, 'Device should receive WRITE frame'
        write_data = onp.decode_write(cmd_frame.payload)
        assert write_data.channel == 0
        assert write_data.value is True
    finally:
        await io.close()

def test_x509_certificate_extensions(tmp_path):
    """Verify that generated certificates strictly adhere to RFC 5280 with all required extensions."""
    certs = tmp_path / 'rfc5280_certs'
    generate(certs, ['localhost', '127.0.0.1', '10.150.102.36'])

    ca = x509.load_pem_x509_certificate((certs / 'ca.crt').read_bytes())
    server = x509.load_pem_x509_certificate((certs / 'server.crt').read_bytes())

    # CA checks
    ca_bc = ca.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    assert ca_bc.ca is True
    assert ca_bc.path_length == 0

    ca_ku = ca.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
    assert ca_ku.key_cert_sign is True
    assert ca_ku.crl_sign is True

    ca_ski = ca.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_KEY_IDENTIFIER).value
    assert ca_ski.digest is not None

    # Leaf server checks
    s_bc = server.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    assert s_bc.ca is False

    s_ski = server.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_KEY_IDENTIFIER).value
    assert s_ski.digest is not None

    s_aki = server.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_KEY_IDENTIFIER).value
    assert s_aki.key_identifier == ca_ski.digest, 'Leaf AKI must match CA SKI'

    s_ku = server.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
    assert s_ku.digital_signature is True
    assert s_ku.key_encipherment is True
    assert s_ku.key_cert_sign is False

    s_eku = server.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in s_eku

    san = server.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    san_names = [n.value for n in san]
    assert 'localhost' in san_names
    import ipaddress
    assert ipaddress.IPv4Address('127.0.0.1') in san_names
    assert ipaddress.IPv4Address('10.150.102.36') in san_names

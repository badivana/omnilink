"""Configuration; secrets are never generated implicitly at server startup."""
import os
from pathlib import Path
from dataclasses import dataclass

def load_env(path='.env'):
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf8').splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

@dataclass
class Settings:
    database_url: str = 'sqlite:///./data/omnilink.db'
    encryption_key: str = ''
    public_url: str = 'http://localhost:8000'
    client_dir: str = ''
    secure_cookie: bool = False
    native_host: str = '127.0.0.1'
    native_port: int = 7443
    tls_cert: str = 'data/certs/server.crt'
    tls_key: str = 'data/certs/server.key'
    native_enabled: bool = True
    http_host: str = '0.0.0.0'
    http_port: int = 8000
    http_tls: bool = False
    mqtt_enabled: bool = False
    mqtt_host: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_user: str = 'omnilink-server'
    mqtt_password: str = ''
    mqtt_admin_user: str = 'omnilink-admin'
    mqtt_admin_password: str = ''
    mqtt_ca: str = ''
    retention_days: int = 30
    retry_seconds: float = 3.0
    bootstrap_email: str = ''
    bootstrap_password: str = ''
    serial_gateway: str = ''   # e.g. COM7: start the Uno/Nano USB gateway with the server

    @classmethod
    def from_env(cls):
        load_env()
        obj = cls()
        for name in obj.__dataclass_fields__:
            value = os.getenv('OMNILINK_' + name.upper())
            if value is None:
                continue
            old = getattr(obj, name)
            value = value.lower() in ('true', '1', 'yes') if isinstance(old, bool) else type(old)(value)
            setattr(obj, name, value)
        if not obj.encryption_key:
            raise RuntimeError('Run python -m omnilink.setup first (missing encryption key).')
        if obj.secure_cookie and not obj.public_url.startswith('https://'):
            raise RuntimeError('Secure cookies require an HTTPS public URL.')
        return obj

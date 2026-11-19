import time
import threading
from sqlalchemy import create_engine, event, String, Integer, BigInteger, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now_ms():
    return time.time_ns() // 1_000_000

class Base(DeclarativeBase):
    pass

class Tenant(Base):
    __tablename__ = 'tenants'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), default='admin')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_ms: Mapped[int] = mapped_column(BigInteger, index=True)

class Device(Base):
    __tablename__ = 'devices'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    secret_cipher: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    firmware: Mapped[str] = mapped_column(String(32), default='')
    boot_id: Mapped[str] = mapped_column(String(32), default='')
    last_seen_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    transport: Mapped[str] = mapped_column(String(16), default='')
    manual_until_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms)

class Channel(Base):
    __tablename__ = 'channels'
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[int] = mapped_column(Integer)
    writable: Mapped[bool] = mapped_column(Boolean, default=True)
    minimum: Mapped[float | None]
    maximum: Mapped[float | None]
    desired: Mapped[object | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(BigInteger, default=0)
    reported: Mapped[object | None] = mapped_column(JSON, nullable=True)
    reported_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    reported_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    reported_boot: Mapped[str] = mapped_column(String(32), default='')
    reported_seq: Mapped[int] = mapped_column(BigInteger, default=0)

class Command(Base):
    __tablename__ = 'commands'
    __table_args__ = (UniqueConstraint('device_id', 'request_id'),)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[int] = mapped_column(Integer)
    value: Mapped[object] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default='queued', index=True)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    expires_ms: Mapped[int] = mapped_column(BigInteger)
    next_attempt_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[int] = mapped_column(Integer, default=0)
    applied_ms: Mapped[int] = mapped_column(BigInteger, default=0)

class Receipt(Base):
    __tablename__ = 'receipts'
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    boot_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms, index=True)

class Telemetry(Base):
    __tablename__ = 'telemetry'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[object] = mapped_column(JSON)
    type: Mapped[int] = mapped_column(Integer)
    observed_ms: Mapped[int] = mapped_column(BigInteger)
    received_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms, index=True)
    quality: Mapped[int] = mapped_column(Integer, default=0)

class DeviceEvent(Base):
    __tablename__ = 'device_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(1024))
    observed_ms: Mapped[int] = mapped_column(BigInteger)
    received_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms, index=True)

class Rule(Base):
    __tablename__ = 'rules'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    metric: Mapped[str] = mapped_column(String(32))
    op: Mapped[str] = mapped_column(String(8))
    threshold: Mapped[float]
    channel: Mapped[int] = mapped_column(Integer)
    value: Mapped[object] = mapped_column(JSON)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_trigger_ms: Mapped[int] = mapped_column(BigInteger, default=0)

class Schedule(Base):
    __tablename__ = 'schedules'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    channel: Mapped[int] = mapped_column(Integer)
    value: Mapped[object] = mapped_column(JSON)
    alternate_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    interval_s: Mapped[int] = mapped_column(Integer, default=60)
    alternate_interval_s: Mapped[int] = mapped_column(Integer, default=60)
    timezone: Mapped[str] = mapped_column(String(64), default='UTC')
    at: Mapped[str] = mapped_column(String(5), default='00:00')
    weekdays: Mapped[list] = mapped_column(JSON, default=lambda: list(range(7)))
    next_due_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    phase: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class Dashboard(Base):
    __tablename__ = 'dashboards'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    widgets: Mapped[list] = mapped_column(JSON, default=list)
    updated_ms: Mapped[int] = mapped_column(BigInteger, default=now_ms)

class Database:
    def __init__(self, url):
        from pathlib import Path
        if url.startswith('sqlite:///') and ':memory:' not in url:
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 20} if url.startswith('sqlite:') else {}, pool_pre_ping=True)
        if url.startswith('sqlite:'):
            @event.listens_for(self.engine, 'connect')
            def pragmas(conn, record):
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=20000')
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self.lock = threading.RLock()
        from . import platform_models
        Base.metadata.create_all(self.engine)

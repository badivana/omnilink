"""Additive v0.5 tables. Existing device/pin numbers are never rewritten on startup."""
from sqlalchemy import String, Integer, BigInteger, Boolean, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now_ms

class PlatformSetting(Base):
    __tablename__='platform_settings'
    key:Mapped[str]=mapped_column(String(40),primary_key=True)
    value:Mapped[object]=mapped_column(JSON)

class Account(Base):
    __tablename__='accounts'
    tenant_id:Mapped[str]=mapped_column(String(32),primary_key=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True)
    pin_limit:Mapped[int|None]=mapped_column(Integer,nullable=True)

class PinLease(Base):
    __tablename__='pin_leases'
    tenant_id:Mapped[str]=mapped_column(String(32),primary_key=True)
    number:Mapped[int]=mapped_column(Integer,primary_key=True)
    device_id:Mapped[str]=mapped_column(String(64))
    allocation_id:Mapped[str]=mapped_column(String(32))

class Flow(Base):
    __tablename__='flows'
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(String(32),index=True)
    name:Mapped[str]=mapped_column(String(80))
    revision:Mapped[int]=mapped_column(Integer,default=1)
    draft:Mapped[dict]=mapped_column(JSON)
    published:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    trigger_state:Mapped[dict]=mapped_column(JSON,default=dict)
    next_due_ms:Mapped[int]=mapped_column(BigInteger,default=0)

class FlowVisualModel(Base):
    """Optional editor-only mxGraphModel; runtime graphs remain v0.5-compatible JSON."""
    __tablename__='flow_visual_models'
    flow_id:Mapped[str]=mapped_column(String(32),primary_key=True)
    mx_graph_model:Mapped[str]=mapped_column(Text)

class FlowRun(Base):
    __tablename__='flow_runs'
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    flow_id:Mapped[str]=mapped_column(String(32),index=True)
    tenant_id:Mapped[str]=mapped_column(String(32),index=True)
    graph:Mapped[dict]=mapped_column(JSON)
    state:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='running')
    test:Mapped[bool]=mapped_column(Boolean,default=False)
    created_ms:Mapped[int]=mapped_column(BigInteger,default=now_ms)
    updated_ms:Mapped[int]=mapped_column(BigInteger,default=now_ms)

class Alert(Base):
    __tablename__='alerts'
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(String(32),index=True)
    device_id:Mapped[str]=mapped_column(String(64),default='')
    message:Mapped[str]=mapped_column(String(500))
    severity:Mapped[str]=mapped_column(String(16),default='warning')
    acknowledged:Mapped[bool]=mapped_column(Boolean,default=False)
    created_ms:Mapped[int]=mapped_column(BigInteger,default=now_ms)

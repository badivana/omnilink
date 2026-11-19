"""Bounded, typed dashboard configuration; browser readings remain in the browser."""
import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .db import Channel
from .core import DomainError, METRIC

class Widget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    kind: Literal['switch','button','slider','input','value','gauge','led','chart','text',
                  'location','motion','camera','microphone','bluetooth','serial',
                  'selector','joystick','colour','schedule','status','table','navigation','stepper','progress','map','floorplan','process']
    title: str = Field(min_length=1, max_length=80)
    width: Literal[1,2] = 1
    color: Literal['mint','blue','amber','rose'] = 'mint'
    device_id: str = Field(default='',max_length=64)
    channel_y: int | None = Field(default=None,ge=0,le=1023,strict=True)
    options: list[dict] = Field(default_factory=list,max_length=32)
    series: list[dict] = Field(default_factory=list,max_length=8)
    chart_mode: Literal['line','bar','point','state'] = 'line'
    target_dashboard: str = Field(default='',max_length=32)
    image: str = Field(default='',max_length=500000)
    points: list[dict] = Field(default_factory=list,max_length=64)
    zoom: int = Field(default=4,ge=1,le=18)
    map_tiles: bool = False
    channel: int | None = Field(default=None, ge=0, le=1023, strict=True)
    source: Literal['reported','desired','telemetry'] = 'reported'
    metric: str = Field(default='', max_length=32)
    unit: str = Field(default='', max_length=16)
    precision: int = Field(default=2, ge=0, le=6, strict=True)
    minimum: float = 0
    maximum: float = 100
    step: float = 1
    on_value: Any = True
    off_value: Any = False
    on_label: str = Field(default='ON', max_length=24)
    off_label: str = Field(default='OFF', max_length=24)
    text: str = Field(default='', max_length=500)
    service: str = Field(default='', max_length=36)
    characteristic: str = Field(default='', max_length=36)
    baud: Literal[9600,19200,38400,57600,115200,230400] = 115200

    @model_validator(mode='after')
    def bounds(self):
        if not all(math.isfinite(v) for v in (self.minimum,self.maximum,self.step)):
            raise ValueError('Use finite widget limits')
        if self.minimum >= self.maximum or self.step <= 0:
            raise ValueError('Maximum must exceed minimum; step must be positive')
        if self.metric and not METRIC.fullmatch(self.metric):
            raise ValueError('Invalid telemetry metric')
        return self

class DashboardBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1,max_length=80)
    widgets: list[Widget] = Field(default_factory=list,max_length=48)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({w.id for w in self.widgets}) != len(self.widgets):
            raise ValueError('Widget IDs must be unique')
        return self

class DashboardEdit(DashboardBody):
    revision: int = Field(ge=1,strict=True)

CONTROLS = {'switch','button','slider','input','selector','joystick','colour','stepper'}
NUMERIC = {2,3,4,5,6,7,10,11}

def validate_widgets(core, session, device_id, widgets, tenant_id=None):
    if tenant_id is None:
        from .db import Device
        device=session.get(Device,device_id)
        if not device: raise DomainError('Device not found',404)
        tenant_id=device.tenant_id
    result=[]
    for widget in widgets:
        data=widget.model_dump()
        target=widget.device_id or device_id
        if target and target!='*': core.device(session,target,tenant_id)
        data['device_id']=target if target!='*' else ''
        if widget.image and not widget.image.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
            raise DomainError('Floor-plan images must be uploaded PNG, JPEG or WebP images')
        for series in widget.series:
            if set(series)-{'device_id','metric','title'} or not METRIC.fullmatch(series.get('metric','')): raise DomainError('Invalid chart series')
            core.device(session,series.get('device_id') or target,tenant_id)
        for point in widget.points:
            if set(point)-{'device_id','channel','x','y','label','symbol'}:raise DomainError('Invalid process/floor-plan point')
            core.device(session,point.get('device_id') or target,tenant_id)
            if not session.get(Channel,(point.get('device_id') or target,point.get('channel'))):raise DomainError('Choose an existing point pin')
            if any(type(point.get(k)) not in (int,float) or not 0<=point[k]<=100 for k in ('x','y')):raise DomainError('Point coordinates must be 0..100 percent')
        if widget.kind=='navigation':
            from .db import Dashboard
            board=session.get(Dashboard,widget.target_dashboard)
            if not board or board.tenant_id!=tenant_id:raise DomainError('Choose a dashboard from this account')
        if widget.kind in {'status','table','schedule'} and not target:raise DomainError('Choose a device')
        if widget.kind in {'joystick','map'}:
            a=session.get(Channel,(target,widget.channel));b=session.get(Channel,(target,widget.channel_y))
            if not a or not b or a.number==b.number or a.type not in NUMERIC or b.type not in NUMERIC:raise DomainError('Choose two different numeric pins')
            if widget.kind=='joystick':
                if not a.writable or not b.writable:raise DomainError('Joystick requires two writable pins')
                for c in (a,b):
                    for edge in (widget.minimum,widget.maximum):core.validate_channel_value(c,int(edge) if c.type in range(2,8) and edge.is_integer() else edge,True)

        if widget.kind in CONTROLS | {'led','map'}: data['source']='reported'
        if widget.kind in CONTROLS | {'value','gauge','led','progress'}:
            if widget.source=='telemetry' and widget.kind in {'value','gauge','progress'}:
                if not widget.metric: raise DomainError('Choose a telemetry metric')
            else:
                ch=session.get(Channel,(target,widget.channel)) if widget.channel is not None else None
                if not ch: raise DomainError('Choose an existing virtual channel')
                if widget.kind in CONTROLS and not ch.writable:
                    raise DomainError('Control widgets need a writable channel')
                if widget.kind=='colour' and ch.type!=12:raise DomainError('Colour picker requires a STRING pin, using #RRGGBB')
                if widget.kind=='selector':
                    if not widget.options:raise DomainError('Add selector options')
                    for option in widget.options:
                        if set(option)!={'label','value'} or not isinstance(option['label'],str) or len(option['label'])>80:raise DomainError('Use label/value selector options')
                        core.validate_channel_value(ch,option['value'],True)
                if widget.kind in {'switch','button','led'}:
                    data['on_value']=core.validate_channel_value(ch,widget.on_value)
                    if widget.kind=='switch':
                        data['off_value']=core.validate_channel_value(ch,widget.off_value)
                        if data['on_value']==data['off_value']: raise DomainError('Switch values must differ')
                if widget.kind in {'slider','gauge','stepper','progress'} and ch.type not in NUMERIC:
                    raise DomainError('Slider and gauge need a numeric channel (up to 32-bit integers)')
                if widget.kind=='slider':
                    for edge in (widget.minimum,widget.maximum):
                        value=int(edge) if ch.type in range(2,8) and edge.is_integer() else edge
                        core.validate_channel_value(ch,value)
                    if ch.type in range(2,8) and not widget.step.is_integer():
                        raise DomainError('Integer channels need an integer slider step')
        if widget.kind=='chart' and not widget.metric and not widget.series: raise DomainError('Choose a chart metric')
        if widget.kind=='bluetooth':
            import re
            uuid=r'(?:[a-fA-F0-9]{4}|[a-fA-F0-9]{8}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})'
            if not re.fullmatch(uuid,widget.service) or not re.fullmatch(uuid,widget.characteristic):
                raise DomainError('Enter the BLE service and characteristic UUIDs')
        result.append(data)
    return result

def dashboard_obj(row):
    return {'id':row.id,'name':row.name,'device_id':row.device_id,'revision':row.revision,
            'widgets':row.widgets,'updated_ms':str(row.updated_ms)}

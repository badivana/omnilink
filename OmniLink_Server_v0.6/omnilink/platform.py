"""Account management, pin ownership and transactional release/reassignment."""
import secrets
from collections import defaultdict
from sqlalchemy import select,delete,func
from .db import Tenant,User,Device,Channel,Command,Dashboard,Rule,Schedule,Session,now_ms
from .platform_models import PlatformSetting,Account,PinLease,Flow,FlowRun,Alert
from .core import DomainError,obj

DEFAULTS={'signup_enabled':True,'pin_limit':255,'max_devices':64,'max_dashboards':32,'max_flows':64}

def settings(s):
    row=s.get(PlatformSetting,'limits')
    return {**DEFAULTS,**(row.value if row else {})}

def limit(s,tenant):
    account=s.get(Account,tenant)
    return (account.pin_limit if account and account.pin_limit is not None else settings(s)['pin_limit'])

def manager_id(s):
    row=s.get(PlatformSetting,'manager_id');return row.value if row else None

def is_manager(rt,u):
    with rt.db.session() as s:return u.id==manager_id(s)

def manager(request):
    from .auth import user
    u=user(request)
    if not is_manager(request.app.state.runtime,u):raise DomainError('Server manager access required',403)
    return u

def reconcile_pin(s,tenant,number):
    devices=list(s.scalars(select(Channel.device_id).join(Device,Device.id==Channel.device_id).where(Device.tenant_id==tenant,Channel.number==number)))
    lease=s.get(PinLease,(tenant,number))
    if not devices:
        if lease:s.delete(lease)
        return
    owner=devices[0] if len(devices)==1 else ''
    if not lease:s.add(PinLease(tenant_id=tenant,number=number,device_id=owner,allocation_id=secrets.token_hex(16)))
    elif lease.device_id!=owner:lease.device_id=owner;lease.allocation_id=secrets.token_hex(16)

def initialize(rt):
    with rt.db.lock,rt.db.session.begin() as s:
        if not s.get(PlatformSetting,'limits'):s.add(PlatformSetting(key='limits',value=DEFAULTS))
        if not s.get(PlatformSetting,'manager_id'):
            owner=s.scalar(select(User).where(User.email==rt.settings.bootstrap_email.strip().lower()))
            if owner:s.add(PlatformSetting(key='manager_id',value=owner.id))
        for tenant in s.scalars(select(Tenant.id)):
            if not s.get(Account,tenant):s.add(Account(tenant_id=tenant))
        groups=set(s.execute(select(Device.tenant_id,Channel.number).join(Channel,Device.id==Channel.device_id)).all())
        for tenant,number in groups:reconcile_pin(s,tenant,number)
        s.flush()
        for lease in s.scalars(select(PinLease).where(PinLease.device_id=='')):
            ids=select(Device.id).where(Device.tenant_id==lease.tenant_id)
            for command in s.scalars(select(Command).where(Command.device_id.in_(ids),Command.channel==lease.number,Command.status.in_(['queued','sent','accepted']))):command.status='superseded'
        # Legacy layouts gain explicit device bindings, preserving layout IDs and pins.
        for board in s.scalars(select(Dashboard)):
            widgets=[{**w,'device_id':w.get('device_id') or board.device_id} for w in board.widgets]
            if widgets!=board.widgets:board.widgets=widgets;board.revision+=1

def pin_inventory(s,tenant):
    groups=defaultdict(list)
    for channel,device in s.execute(select(Channel,Device).join(Device,Device.id==Channel.device_id).where(Device.tenant_id==tenant)):
        groups[channel.number].append({'device_id':device.id,'device_name':device.name,'channel_name':channel.name,'type':channel.type})
    pool=limit(s,tenant)
    return {'limit':pool,'used':len(groups),'free':[n for n in range(pool) if n not in groups],
            'pins':[{'number':n,'conflict':len(owners)>1,'outside_pool':n>=pool,'owners':owners} for n,owners in sorted(groups.items())]}

def claim(s,tenant,device_id,number):
    if not 0<=number<limit(s,tenant):raise DomainError(f'Choose a pin from V0 to V{limit(s,tenant)-1}')
    lease=s.get(PinLease,(tenant,number))
    if lease and lease.device_id!=device_id:raise DomainError(f'V{number} is already allocated or has an upgrade conflict. Choose a free pin.',409)
    if not lease:
        lease=PinLease(tenant_id=tenant,number=number,device_id=device_id,allocation_id=secrets.token_hex(16));s.add(lease)
    return lease

def widget_refs(w,fallback=''):
    device=w.get('device_id') or fallback
    refs=set()
    if device and w.get('source','reported')!='telemetry':
        for key in ('channel','channel_y'):
            if w.get(key) is not None:refs.add((device,w[key]))
    for point in w.get('points',[]):
        if point.get('channel') is not None:refs.add((point.get('device_id') or device,point['channel']))
    for series in w.get('series',[]):
        if series.get('channel') is not None:refs.add((series.get('device_id') or device,series['channel']))
    return refs

def graph_refs(graph):
    return {(n.get('device_id'),n.get('pin')) for n in (graph or {}).get('nodes',[]) if n.get('device_id') and n.get('pin') is not None}

def dependencies(s,tenant,refs,exclude_board=None):
    found=[]
    for b in s.scalars(select(Dashboard).where(Dashboard.tenant_id==tenant)):
        if b.id==exclude_board:continue
        for w in b.widgets:
            if widget_refs(w,b.device_id)&refs:found.append({'kind':'widget','id':w['id'],'container':b.id,'name':b.name+' / '+w['title']})
    for f in s.scalars(select(Flow).where(Flow.tenant_id==tenant)):
        if (graph_refs(f.draft)|graph_refs(f.published))&refs:found.append({'kind':'flow','id':f.id,'name':f.name})
    for run in s.scalars(select(FlowRun).where(FlowRun.tenant_id==tenant,FlowRun.status=='running',FlowRun.test==False)):
        if graph_refs(run.graph)&refs:found.append({'kind':'execution','id':run.id,'name':'Running flow '+run.flow_id})
    for device,pin in refs:
        for cls,kind in [(Rule,'rule'),(Schedule,'schedule')]:
            for row in s.scalars(select(cls).where(cls.device_id==device,cls.channel==pin)):
                found.append({'kind':kind,'id':row.id,'name':row.name})
    return found

def ensure_releasable(s,tenant,refs,exclude_board=None):
    found=dependencies(s,tenant,refs,exclude_board)
    if found:
        error=DomainError('Pin release blocked by shared references. Remove or rebind the listed dependencies first.',409)
        error.dependencies=found;raise error

def release(s,tenant,refs,exclude_board=None):
    ensure_releasable(s,tenant,refs,exclude_board)
    for device,pin in refs:
        d=s.get(Device,device)
        if not d or d.tenant_id!=tenant:raise DomainError('Device not found',404)
        channel=s.get(Channel,(device,pin))
        if channel:s.delete(channel)
        # Old acknowledgments/commands cannot be inherited by a later allocation.
        s.execute(delete(Command).where(Command.device_id==device,Command.channel==pin))
        s.flush();reconcile_pin(s,tenant,pin)

def update_board(rt,s,row,widgets,name,revision):
    if revision!=row.revision:raise DomainError('Dashboard changed. Reload before saving.',409)
    old_by_id={w['id']:w for w in row.widgets};new_ids={w['id'] for w in widgets}
    removed=set().union(*(widget_refs(w,row.device_id) for key,w in old_by_id.items() if key not in new_ids)) if old_by_id else set()
    remaining=set().union(*(widget_refs(w,row.device_id) for w in widgets)) if widgets else set()
    if removed&remaining:
        error=DomainError('Another widget in this layout still uses a pin being released. Remove or rebind it before saving.',409)
        error.dependencies=[{'kind':'widget','id':w['id'],'name':w['title']} for w in widgets if widget_refs(w,row.device_id)&removed];raise error
    release(s,row.tenant_id,removed,row.id)
    row.widgets=widgets;row.name=name;row.revision+=1;row.updated_ms=now_ms()

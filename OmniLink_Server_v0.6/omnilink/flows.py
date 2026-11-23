"""Bounded, persistent visual workflows. No user code is evaluated."""
import copy,json,math,re,secrets,smtplib,ssl,threading,time
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from datetime import datetime,timezone
from types import SimpleNamespace
import httpx
from sqlalchemy import select,func
from .db import Device,Channel,Telemetry,Command,now_ms,User
from .platform_models import Flow,FlowRun,PinLease,Alert,PlatformSetting,Account
from .platform import graph_refs,limit
from .core import DomainError

KINDS={'trigger','condition','write','delay','wait','calculate','variable','alert','parallel','stop','flow','webhook','email'}
EVENTS={'manual','pin','telemetry','interval','daily','online','offline'}
OPS={'gt','gte','lt','lte','eq','ne'}

def compare(a,op,b):
    try:
        return {'gt':lambda:a>b,'gte':lambda:a>=b,'lt':lambda:a<b,'lte':lambda:a<=b,'eq':lambda:a==b,'ne':lambda:a!=b}[op]()
    except (TypeError,KeyError):return False

def _validate_mx_graph(graph):
    model=graph.get('mxGraphModel')
    if model is None:return
    if not isinstance(model,str) or len(model.encode('utf-8'))>262144 or re.search(r'<!\s*(?:DOCTYPE|ENTITY)',model,re.I):
        raise DomainError('Invalid or oversized mxGraphModel')
    try:root=ET.fromstring(model)
    except ET.ParseError:raise DomainError('Invalid mxGraphModel XML')
    if root.tag!='mxGraphModel':raise DomainError('Expected an mxGraphModel document')
    model_root=root.find('./root')
    if model_root is None:raise DomainError('mxGraphModel needs a root cell')
    if len(model_root)>194 or any(cell.tag!='mxCell' for cell in model_root):raise DomainError('mxGraphModel has too many or unsupported cells')
    native_nodes=[];native_edge_cells=[];cell_ids=set();vertices={}
    for cell in model_root.findall('mxCell'):
        cid=cell.get('id','')
        if not cid or cid in cell_ids:raise DomainError('mxGraphModel cells need unique IDs')
        cell_ids.add(cid)
        if cid not in ('0','1') and cell.get('vertex')!='1' and cell.get('edge')!='1':raise DomainError('Unsupported mxGraphModel cell type')
        if cell.get('vertex')=='1':
            if cell.get('parent')!='1':raise DomainError('mxGraphModel blocks must belong to the root layer')
            try:node=json.loads(cell.get('omni',''))
            except (TypeError,ValueError):raise DomainError('mxGraphModel block data is invalid')
            if not isinstance(node,dict) or not cid.startswith('vertex_') or node.get('id')!=cid[len('vertex_'):]:raise DomainError('mxGraphModel block ID does not match its data')
            geometry=cell.find('./mxGeometry')
            if geometry is None:raise DomainError('mxGraphModel blocks need geometry')
            try:x=float(geometry.get('x','0'));y=float(geometry.get('y','0'))
            except ValueError:raise DomainError('mxGraphModel block position is invalid')
            if not math.isfinite(x) or not math.isfinite(y) or x!=float(node.get('x',0)) or y!=float(node.get('y',0)):
                raise DomainError('mxGraphModel block geometry must match its saved position')
            vertices[cid]=node['id'];native_nodes.append(node)
        elif cell.get('edge')=='1':
            if cell.get('parent')!='1':raise DomainError('mxGraphModel connections must belong to the root layer')
            try:data=json.loads(cell.get('omni','{}'))
            except (TypeError,ValueError):raise DomainError('mxGraphModel connection data is invalid')
            if not isinstance(data,dict):raise DomainError('mxGraphModel connection data is invalid')
            native_edge_cells.append((cell.get('source'),cell.get('target'),data))
    root_cells={cell.get('id'):cell for cell in model_root.findall('mxCell') if cell.get('id') in ('0','1')}
    if set(root_cells)!={'0','1'} or root_cells['0'].get('parent') is not None or root_cells['1'].get('parent')!='0':
        raise DomainError('mxGraphModel needs the standard root and layer cells')
    native_edges=[]
    for source,target,data in native_edge_cells:
        native_edges.append({'from':vertices.get(source),'to':vertices.get(target),'port':data.get('port','next')})
    if not 1<=len(native_nodes)<=64 or len(native_edges)>128:raise DomainError('mxGraphModel must use 1..64 blocks and at most 128 connections')
    if not isinstance(graph.get('nodes'),list) or not all(isinstance(n,dict) for n in graph['nodes']) or not isinstance(graph.get('edges'),list) or not all(isinstance(e,dict) for e in graph['edges']):
        raise DomainError('Flow needs valid blocks and connections')
    def clean_node(n):
        value=copy.deepcopy(n);value.pop('allocation_id',None);return value
    nodes=graph.get('nodes',[])
    edges=[{'from':e.get('from'),'to':e.get('to'),'port':e.get('port','next')} for e in graph.get('edges',[]) if isinstance(e,dict)]
    if [clean_node(n) for n in nodes]!=[clean_node(n) for n in native_nodes] or edges!=native_edges:
        raise DomainError('mxGraphModel and flow blocks/connections do not match')

def validate(rt,s,tenant,graph):
    if not isinstance(graph,dict) or set(graph)-{'nodes','edges'}:raise DomainError('Flow needs nodes and edges')
    nodes=graph.get('nodes',[]);edges=graph.get('edges',[])
    if not isinstance(nodes,list) or not 1<=len(nodes)<=64 or not isinstance(edges,list) or len(edges)>128:raise DomainError('Use 1..64 nodes and at most 128 connections')
    allowed={'id','kind','label','x','y','event','device_id','pin','metric','op','value','value2','variable','operation','seconds','timeout','conditions','logic','at','timezone','weekdays','interval_s','wait_ack','retries','message','severity','flow_id','integration','body','allocation_id'}
    result=copy.deepcopy(graph);ids=set();triggers=[]
    for n in result['nodes']:
        if not isinstance(n,dict) or set(n)-allowed:raise DomainError('Unknown flow node fields')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',str(n.get('id',''))) or n['id'] in ids:raise DomainError('Unique node IDs required')
        ids.add(n['id'])
        if n.get('kind') not in KINDS:raise DomainError('Unknown block type')
        if len(str(n.get('label','')))>80 or len(str(n.get('message','')))>500:raise DomainError('Block label/message too long')
        for key in ('x','y'):
            if type(n.get(key,0)) not in (int,float) or not math.isfinite(n.get(key,0)) or not 0<=n.get(key,0)<=5000:raise DomainError('Invalid block position')
        for key in ('seconds','timeout','interval_s'):
            if key in n and (type(n[key]) is not int or not 1<=n[key]<=86400):raise DomainError('Durations must be 1..86400 seconds')
        if n.get('op','eq') not in OPS:raise DomainError('Invalid comparison')
        if type(n.get('retries',0)) is not int or not 0<=n.get('retries',0)<=3:raise DomainError('Use at most three retries')
        if n['kind']=='trigger':
            triggers.append(n)
            if n.get('event','manual') not in EVENTS:raise DomainError('Invalid trigger')
            if n.get('event')=='daily':
                try:rt.core.calendar_next(SimpleNamespace(at=n.get('at','08:00'),timezone=n.get('timezone','UTC'),weekdays=n.get('weekdays',list(range(7)))),now_ms())
                except Exception:raise DomainError('Invalid daily time, timezone or weekdays')
            if n.get('event') in ('pin','telemetry','online','offline') and not n.get('device_id'):raise DomainError('Choose a trigger device')
            if n.get('event')=='pin' and n.get('pin') is None:raise DomainError('Choose a trigger pin')
            if n.get('event')=='telemetry' and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}',n.get('metric','')):raise DomainError('Choose a telemetry metric')
        if n.get('device_id'):rt.core.device(s,n['device_id'],tenant)
        if n.get('pin') is not None:
            if type(n['pin']) is not int or not n.get('device_id'):raise DomainError('Pin requires a device')
            ch=s.get(Channel,(n['device_id'],n['pin']));lease=s.get(PinLease,(tenant,n['pin']))
            if not ch or not lease or lease.device_id!=n['device_id']:raise DomainError('Resolve the pin allocation before using it in a flow',409)
            n['allocation_id']=lease.allocation_id
            if n['kind']=='write':
                if not ch.writable:raise DomainError('Write block requires a writable pin')
                if not isinstance(n.get('value'),dict) or set(n['value'])!={'var'}:n['value']=rt.core.validate_channel_value(ch,n.get('value'),True)
        elif n['kind'] in ('write','wait'):raise DomainError('Choose a pin for this block')
        if n['kind']=='calculate' and n.get('operation') not in ('add','subtract','multiply','divide','min','max','average'):raise DomainError('Invalid calculation')
        if n['kind'] in ('calculate','variable') and not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,31}',n.get('variable','')):raise DomainError('Choose a variable name')
        if n['kind']=='condition':
            if n.get('logic','and') not in ('and','or','not'):raise DomainError('Choose AND, OR or NOT')
            if not isinstance(n.get('conditions',[]),list) or len(n.get('conditions',[]))>8:raise DomainError('Use at most eight comparisons')
            for c in n.get('conditions',[]):
                if not isinstance(c,dict) or set(c)-{'left','op','right'} or c.get('op') not in OPS:raise DomainError('Invalid condition comparison')
        if n['kind']=='flow':
            other=s.get(Flow,n.get('flow_id',''))
            if not other or other.tenant_id!=tenant:raise DomainError('Choose a flow from this account')
        if n['kind'] in ('webhook','email'):
            cfg=s.get(PlatformSetting,'integrations');integration=(cfg.value if cfg else {}).get(n.get('integration',''))
            if not integration or integration.get('kind')!=n['kind']:raise DomainError('Choose an integration configured by the server manager')
        if n.get('severity','warning') not in ('info','warning','critical'):raise DomainError('Invalid alert severity')
    if len(triggers)!=1:raise DomainError('A flow needs exactly one trigger')
    adj={key:[] for key in ids}
    for edge in edges:
        if not isinstance(edge,dict) or set(edge)-{'from','to','port'} or edge.get('from') not in ids or edge.get('to') not in ids or edge.get('port','next') not in ('next','yes','no','error'):raise DomainError('Invalid connection')
        if edge['to']==triggers[0]['id']:raise DomainError('Cannot connect into a trigger')
        adj[edge['from']].append(edge['to'])
    visiting=set();seen=set()
    def walk(key):
        if key in visiting:raise DomainError('Cycles are not allowed. Use an interval trigger for repeats.')
        if key in seen:return
        visiting.add(key)
        for child in adj[key]:walk(child)
        visiting.remove(key);seen.add(key)
    walk(triggers[0]['id'])
    if seen!=ids:raise DomainError('Connect every block to the trigger')
    return result

def validate_mx_model(graph,model):
    if not isinstance(graph,dict):raise DomainError('Flow needs nodes and edges')
    _validate_mx_graph({**graph,'mxGraphModel':model})

def value(expr,state):
    if isinstance(expr,dict) and set(expr)=={'var'}:return state['variables'].get(expr['var'])
    return expr

def read_pin(s,n,state):
    key=str(n.get('device_id',''))+':'+str(n.get('pin',''))
    if key in state.get('samples',{}):return state['samples'][key]
    ch=s.get(Channel,(n.get('device_id'),n.get('pin')))
    return ch.reported if ch else None

def condition(s,n,state):
    terms=n.get('conditions',[])
    if terms:
        results=[compare(value(c.get('left'),state),c['op'],value(c.get('right'),state)) for c in terms]
        return any(results) if n.get('logic')=='or' else not all(results) if n.get('logic')=='not' else all(results)
    return compare(read_pin(s,n,state) if n.get('pin') is not None else value(n.get('value2',{'var':'trigger'}),state),n.get('op','eq'),value(n.get('value'),state))

class Engine:
    def __init__(self,rt):self.rt=rt
    def launch(self,s,flow,graph=None,test=False,samples=None,trigger=None,depth=0):
        graph=copy.deepcopy(graph or flow.published)
        if not graph:raise DomainError('Publish this flow first')
        if depth>4:raise DomainError('Nested flow limit reached')
        active=s.scalar(select(func.count()).select_from(FlowRun).where(FlowRun.tenant_id==flow.tenant_id,FlowRun.status=='running'))
        recent=s.scalar(select(func.count()).select_from(FlowRun).where(FlowRun.tenant_id==flow.tenant_id,FlowRun.created_ms>now_ms()-60_000))
        if active>=16 or recent>=120:raise DomainError('Account flow execution limit reached',429)
        start=next(n['id'] for n in graph['nodes'] if n['kind']=='trigger')
        run=FlowRun(id=secrets.token_hex(16),flow_id=flow.id,tenant_id=flow.tenant_id,graph=graph,test=test,
                    state={'queue':[{'id':start,'due':now_ms(),'started':now_ms()}],'visited':[],'variables':{'trigger':trigger},'samples':samples or {},'log':[],'depth':depth})
        s.add(run);return run
    def emit(self,tenant,kind,data):
        # Device notifications are raised after ingestion commits.
        with self.rt.db.lock,self.rt.db.session.begin() as s:
            account=s.get(Account,tenant)
            if account and not account.enabled:return
            for flow in s.scalars(select(Flow).where(Flow.tenant_id==tenant,Flow.enabled==True)):
                trigger=next(n for n in flow.published['nodes'] if n['kind']=='trigger')
                if trigger.get('device_id')!=data.get('device_id'):continue
                val=None;matches=False
                if trigger.get('event')=='pin' and kind=='report' and trigger.get('pin')==data.get('channel'):val=data['value'];matches=True
                if trigger.get('event')=='telemetry' and kind=='telemetry':
                    metric=next((m for m in data.get('metrics',[]) if m['name']==trigger.get('metric')),None)
                    if metric:val=metric['value'];matches=True
                if not matches:continue
                previous=flow.trigger_state.get('value');flow.trigger_state={'value':val}
                if previous!=val:
                    try:self.launch(s,flow,trigger=val)
                    except DomainError:pass
    def prepare_external(self,s,n,run,state):
        """Snapshot an integration call inside the transaction; it is sent after commit."""
        cfg=s.get(PlatformSetting,'integrations');entry=(cfg.value if cfg else {}).get(n.get('integration'))
        if not entry:raise DomainError('Integration removed')
        job={'run':run.id,'node':n['id'],'kind':n['kind'],'entry':copy.deepcopy(entry),'message':n.get('message',''),'variables':copy.deepcopy(state['variables'])}
        if n['kind']=='email':
            owner=s.scalar(select(User).where(User.tenant_id==run.tenant_id,User.role=='admin',User.enabled==True).order_by(User.id))
            if not owner:raise DomainError('No enabled account owner email')
            job['to']=owner.email
        return job
    def external(self,job):
        # Runs with no database lock held: a slow receiver must not stall the server.
        entry=job['entry']
        secret=self.rt.core.cipher.decrypt(entry['secret_cipher'].encode()).decode() if entry.get('secret_cipher') else ''
        if job['kind']=='webhook':
            headers={'X-OmniLink-Run':job['run']}
            if secret:headers['Authorization']='Bearer '+secret
            with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as c:
                response=c.post(entry['url'],json={'run_id':job['run'],'message':job['message'],'variables':job['variables']},headers=headers)
                if not 200<=response.status_code<300:raise DomainError(f'Webhook returned HTTP {response.status_code}')
        else:
            msg=EmailMessage();msg['Subject']='OmniLink automation';msg['From']=entry['sender'];msg['To']=job['to'];msg.set_content(job['message'] or 'Automation notification')
            with smtplib.SMTP(entry['host'],entry.get('port',587),timeout=5) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if entry.get('username'):smtp.login(entry['username'],secret)
                smtp.send_message(msg)
    def tick(self):
        jobs=self._tick()
        # Sent in the background so a slow receiver cannot delay the worker's command delivery.
        if jobs:threading.Thread(target=self._send,args=(jobs,),daemon=True,name='omnilink-integrations').start()
    def _send(self,jobs):
        results=[]
        for job in jobs:
            try:self.external(job);results.append((job,'ok'))
            except Exception as error:results.append((job,str(error)[:240] or type(error).__name__))
        with self.rt.db.lock,self.rt.db.session.begin() as s:
            for job,result in results:
                run=s.get(FlowRun,job['run'])
                if not run or run.status!='running':continue
                state=copy.deepcopy(run.state)
                for item in state['queue']:
                    if item['id']==job['node'] and isinstance(item.get('external'),dict):item['external']=result
                run.state=state
    def _tick(self):
        rt=self.rt;now=now_ms()
        with rt.db.lock,rt.db.session.begin() as s:
            for f in s.scalars(select(Flow).where(Flow.enabled==True)):
                account=s.get(Account,f.tenant_id)
                if account and not account.enabled:continue
                t=next(n for n in f.published['nodes'] if n['kind']=='trigger');event=t.get('event','manual')
                fire=False
                if event in ('interval','daily') and f.next_due_ms<=now:
                    fire=f.next_due_ms>0 and now-f.next_due_ms<30000
                    f.next_due_ms=rt.core.calendar_next(SimpleNamespace(at=t.get('at','08:00'),timezone=t.get('timezone','UTC'),weekdays=t.get('weekdays',list(range(7)))),now) if event=='daily' else now+max(1,t.get('interval_s',60))*1000
                if event in ('online','offline'):
                    d=s.get(Device,t['device_id']);online=bool(d and d.enabled and now-d.last_seen_ms<90000)
                    prev=f.trigger_state.get('online');f.trigger_state={'online':online}
                    fire=prev is not None and prev!=online and online==(event=='online')
                if fire:
                    try:self.launch(s,f,trigger=event)
                    except DomainError:pass
            s.flush()
            # Least recently advanced first, so long waits cannot starve newer runs.
            runs=list(s.scalars(select(FlowRun).where(FlowRun.status=='running').order_by(FlowRun.updated_ms,FlowRun.created_ms).limit(128)))
            jobs=[]
            for run in runs:self.advance(s,run,now,jobs)
        return jobs
    def advance(self,s,run,now,jobs):
        state=copy.deepcopy(run.state);nodes={n['id']:n for n in run.graph['nodes']};account=s.get(Account,run.tenant_id)
        if account and not account.enabled:run.status='cancelled';return
        if now-run.created_ms>7*86400_000:run.status='failed';return
        queue=state['queue'];remaining=[]
        for item in queue[:16]:
            if item['due']>now:remaining.append(item);continue
            n=nodes[item['id']]
            if n['id'] in state['visited']:continue
            port='next';waiting=False
            try:
                if n.get('pin') is not None:
                    lease=s.get(PinLease,(run.tenant_id,n['pin']))
                    if not lease or lease.device_id!=n['device_id'] or lease.allocation_id!=n.get('allocation_id'):raise DomainError('Pin allocation changed; publish the flow again')
                kind=n['kind']
                if kind=='condition':port='yes' if condition(s,n,state) else 'no'
                elif kind=='write':
                    if run.test:state['log'].append({'node':n['id'],'status':'simulated','value':value(n.get('value'),state)})
                    elif not item.get('command'):
                        d=self.rt.core.device(s,n['device_id'],run.tenant_id,enabled=True)
                        command=self.rt.core._write(s,d,n['pin'],value(n.get('value'),state),'flow',ttl_s=n.get('timeout',30),request_id='flow:'+run.id+':'+n['id']+':'+str(item.get('attempt',0)))
                        if not command:raise DomainError('Device automation is paused')
                        item['command']=command.key;waiting=n.get('wait_ack',True)
                    elif n.get('wait_ack',True):
                        c=s.get(Command,item['command'])
                        if not c or c.status in ('expired','rejected','superseded','failed'):raise DomainError('Device command failed or expired')
                        waiting=c.status!='applied'
                elif kind=='delay':waiting=not run.test and now<item['started']+n.get('seconds',1)*1000
                elif kind=='wait':
                    waiting=not condition(s,n,state)
                    if run.test and waiting:port='error';waiting=False
                    elif waiting and now>=item['started']+n.get('timeout',60)*1000:raise DomainError('Wait condition timed out')
                elif kind=='variable':state['variables'][n['variable']]=value(n.get('value'),state)
                elif kind=='calculate':
                    a=value(n.get('value'),state);b=value(n.get('value2'),state)
                    if type(a) not in (int,float) or type(b) not in (int,float):raise DomainError('Calculation requires numbers')
                    ops={'add':lambda:a+b,'subtract':lambda:a-b,'multiply':lambda:a*b,'divide':lambda:a/b,'min':lambda:min(a,b),'max':lambda:max(a,b),'average':lambda:(a+b)/2}
                    result=ops[n['operation']]()
                    if not math.isfinite(result):raise DomainError('Non-finite calculation')
                    state['variables'][n['variable']]=result
                elif kind=='alert' and not run.test:s.add(Alert(id=secrets.token_hex(16),tenant_id=run.tenant_id,device_id=n.get('device_id',''),message=n.get('message','Flow alert'),severity=n.get('severity','warning')))
                elif kind in ('webhook','email') and not run.test:
                    # 'external' is unset (not sent), {'at':ms} (sending after commit), 'ok', or an error text.
                    sent=item.get('external')
                    if sent is None:
                        jobs.append(self.prepare_external(s,n,run,state));item['external']={'at':now};waiting=True
                    elif isinstance(sent,dict):
                        if now-sent['at']>60_000:raise DomainError('Integration call did not complete')
                        waiting=True
                    elif sent!='ok':raise DomainError(sent)
                elif kind=='flow':
                    f=s.get(Flow,n['flow_id'])
                    if not f or f.tenant_id!=run.tenant_id or not f.enabled:raise DomainError('Referenced flow is not published and enabled')
                    self.launch(s,f,test=run.test,samples=state['samples'],trigger=state['variables'].get('trigger'),depth=state['depth']+1)
                elif kind=='stop':state['log'].append({'node':n['id'],'status':'completed','at':now});state['queue']=[];run.status='completed';run.state=state;return
            except Exception as error:
                if item.get('attempt',0)<n.get('retries',0):
                    item['attempt']=item.get('attempt',0)+1;item['due']=now+1000*item['attempt'];item['started']=now;item.pop('command',None);item.pop('external',None);remaining.append(item);continue
                port='error';state['log'].append({'node':n['id'],'status':'failed','detail':str(error)[:240],'at':now})
                if not any(e['from']==n['id'] and e.get('port')=='error' for e in run.graph['edges']):run.status='failed';state['queue']=[];run.state=state;return
            if waiting:
                item['due']=now+500;remaining.append(item)
                if not state['log'] or state['log'][-1].get('node')!=n['id']:state['log'].append({'node':n['id'],'status':'waiting','at':now})
                continue
            state['visited'].append(n['id']);state['log'].append({'node':n['id'],'status':port if port!='next' else 'completed','at':now})
            for e in run.graph['edges']:
                if e['from']==n['id'] and e.get('port','next')==port:remaining.append({'id':e['to'],'due':now,'started':now})
        state['queue']=remaining+queue[16:];state['log']=state['log'][-256:]
        if not state['queue']:run.status='completed'
        run.state=state;run.updated_ms=now

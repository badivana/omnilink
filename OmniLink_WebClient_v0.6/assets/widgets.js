'use strict';
/* Account dashboards may combine multiple devices. Sensor sessions are browser-local. */
(() => {
  const catalog = {
    selector:['Selector','Choose among named values.'], joystick:['Joystick','Two numeric axes on two virtual pins.'], colour:['Colour picker','Send #RRGGBB to a STRING pin.'], schedule:['Schedule controls','Create time and repeating schedules for this device.'], status:['Device status','Connection and last contact.'], table:['Device table','Current channel readings for a device.'], navigation:['Navigation','Open another dashboard.'], stepper:['Value stepper','Increase or decrease a value.'], progress:['Progress bar','Show a bounded numeric reading.'], map:['Location map','Two pins provide latitude and longitude. Optional OpenStreetMap tiles.'], floorplan:['Floor plan','Place live pin readings on an uploaded image.'], process:['Process view','Arrange equipment symbols and live readings.'],
    switch:['Switch','Two configured values, such as ON / OFF.'],
    button:['Button','Send a configured value with one tap.'],
    slider:['Slider','Set a numeric channel when you release the slider.'],
    input:['Value input','Enter a value using the channel’s type.'],
    value:['Value display','A reported value, desired value, or telemetry metric.'],
    gauge:['Gauge','A numeric reading with a configured range.'],
    led:['LED indicator','Lights when the reported value matches your configured value.'],
    chart:['Chart','Recent numeric telemetry, updated live.'],
    text:['Text card','A label or instruction on your dashboard.'],
    location:['Browser location','Latitude, longitude, accuracy, and altitude when available.'],
    motion:['Motion / orientation','Acceleration, rotation, and orientation when available.'],
    camera:['Camera preview','Live browser camera preview; no recording or upload.'],
    microphone:['Microphone level','Relative signal level; no recording or upload.'],
    bluetooth:['BLE reader','Read a configured GATT characteristic from a selected sensor.'],
    serial:['Serial monitor','Read UTF-8 lines from a browser-selected Serial port.']
  };
  const widgetHelp={
    selector:'Pick one named option to send its configured value to a writable pin. Add one Label=value pair per line. Choose values that match the pin type; this control sends immediately.',
    joystick:'Control two numeric writable pins. The X and Y axes use the configured minimum, maximum, and step. Select two pins on the same device; releasing the pad sends two separate commands.',
    colour:'Choose a colour to send its #RRGGBB string to a writable STRING pin. The device firmware must understand that format.',
    schedule:'Create or remove a time-based schedule for a writable pin. Schedules are stored by the server and run while the browser is closed. Pick the target pin and local schedule time carefully.',
    status:'Show whether the selected device is connected and when it last contacted the server. This is read-only and does not use a pin.',
    table:'Show current reported readings for the selected device’s pins. This is read-only. Create pins under Devices & pins first.',
    navigation:'Add a button that opens another dashboard in the same account. Create the destination dashboard before selecting it here.',
    stepper:'Increase or decrease a numeric writable pin by the configured step. Set the pin’s valid minimum and maximum so every value stays in range.',
    progress:'Show a pin or telemetry number as progress between the configured minimum and maximum. Use a numeric pin or choose a telemetry metric.',
    map:'Plot latitude and longitude from two numeric pins, or show a location value. Both coordinate pins must belong to the selected device. Optional map tiles load from OpenStreetMap when enabled.',
    floorplan:'Upload a small floor-plan image, then place labelled pin markers by clicking its preview. Each marker reads the pin assigned to that point. Keep the image free of private information you do not want stored with the dashboard.',
    process:'Arrange pin markers over an equipment or process image to make a live process view. Upload an image, place points, and select the relevant device pins and symbols.',
    switch:'Send one of two configured values to a writable pin. Choose the on/off values and labels that your device firmware expects.',
    button:'Send the configured value to a writable pin when pressed. It is a momentary action; use Switch when you need an on/off state.',
    slider:'Set a numeric writable pin by dragging the slider and releasing it. Configure a safe range and step that match the device.',
    input:'Enter a value for a writable pin. The form checks the pin’s data type and configured bounds before sending.',
    value:'Display a pin’s reported or desired value, or a telemetry metric. Pick the correct device, source, and pin or metric.',
    gauge:'Show a numeric reading on a gauge. Select a numeric pin or telemetry metric and set the gauge’s minimum and maximum.',
    led:'Show an indicator that lights when a pin’s reported value equals the configured on value. Set the value to match the firmware output exactly.',
    chart:'Plot numeric telemetry over time. Select a metric, chart style, and optional additional device/metric series. Telemetry is recorded by the server.',
    text:'Show a static note, label, or instruction. Text cards do not read pins or send commands.',
    location:'Ask this browser for location while the dashboard is open. The browser may require HTTPS and user permission. Readings stay on this device and stop when the session ends.',
    motion:'Read motion or orientation sensors exposed by this browser. Device support and permission prompts vary; readings are browser-local and stop when the dashboard session ends.',
    camera:'Show a live camera preview after you choose a camera and grant browser permission. The widget does not record or upload video; closing the dashboard stops the camera.',
    microphone:'Show a relative microphone level after browser permission. The widget does not record or upload audio; closing the dashboard stops microphone access.',
    bluetooth:'Connect to a BLE device and read the configured GATT service/characteristic. Requires a supported browser, HTTPS or localhost, a nearby device, and explicit selection/permission.',
    serial:'Choose a USB/serial device and view incoming UTF-8 lines. Requires a supported browser, HTTPS or localhost, and explicit device permission. Closing the dashboard ends the read session.'
  };
  const controls = new Set(['switch','button','slider','input','selector','joystick','colour','stepper']);
  const sensors = new Set(['location','motion','camera','microphone','bluetooth','serial']);
  const numeric = new Set([2,3,4,5,6,7,10,11]);
  let context=null, boards=[], active='', board=null, draft=null, editing=false, dirty=false;
  let layoutEpoch=0;
  let stamp='', generation=0, dragging='', offline=!navigator.onLine;
  const sessions=new Map(), pending=new Set();
  const id=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  const clone=v=>JSON.parse(JSON.stringify(v));
  const current=()=>draft||board;
  const root=()=>'/api/dashboards';
  const channelOf=(w,pin=w.channel)=>context.channels.find(c=>c.device_id===w.device_id&&c.number===pin);
  const deviceOf=w=>context.devices.find(d=>d.id===w.device_id);
  const widgetPins=w=>[w.channel,w.channel_y].filter(n=>n!=null);
  const element=(wid,part)=>document.querySelector(`[data-widget="${wid}"] [data-part="${part}"]`);
  const short=v=>v==null?'—':typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:6}):fmt(v);
  const display=(v,w)=>typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:w.precision}):fmt(v);
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

  function capability(kind) {
    if(!window.isSecureContext) return {ok:false,label:'Requires HTTPS or localhost'};
    const found={location:!!navigator.geolocation,motion:!!(window.DeviceMotionEvent||window.DeviceOrientationEvent),
      camera:!!navigator.mediaDevices?.getUserMedia,microphone:!!navigator.mediaDevices?.getUserMedia,
      bluetooth:!!navigator.bluetooth?.requestDevice,serial:!!navigator.serial?.requestPort}[kind];
    return {ok:!!found,label:found?'Available · permission may be needed':'Unavailable in this browser'};
  }
  function capabilities() {
    $('browser-capabilities').innerHTML=[...sensors].map(kind=>{
      const c=capability(kind);
      return `<article><strong>${esc(catalog[kind][0])}</strong><span class="${c.ok?'available':'muted'}">${esc(c.label)}</span></article>`;
    }).join('');
  }
  function widgetGuide(kind){
    const entries=kind?[[kind,catalog[kind]]]:Object.entries(catalog);
    return `<div class="widget-guide">${entries.map(([key,[title,short]])=>`<article><h3>${esc(title)}</h3><p>${esc(widgetHelp[key]||short)}</p>${!kind?`<small>${esc(short)}</small>`:''}</article>`).join('')}</div>`;
  }
  function showWidgetHelp(kind){const title=kind?catalog[kind][0]+' help':'Widget guide';if($('modal').open){$('modal-title').textContent=title;$('modal-body').innerHTML=widgetGuide(kind);$('modal-error').textContent='';$('modal-submit').classList.add('hidden');}else modal(title,widgetGuide(kind),null);}
  function make(kind,title,options={}) {
    return {id:id(),kind,title,device_id:selected||'',channel_y:null,options:[],series:[],chart_mode:'line',target_dashboard:'',image:'',points:[],zoom:4,map_tiles:false,width:1,color:'mint',channel:null,source:'reported',metric:'',unit:'',
      precision:2,minimum:0,maximum:100,step:1,on_value:true,off_value:false,on_label:'ON',off_label:'OFF',
      text:'',service:'',characteristic:'',baud:115200,...options};
  }
  function starter() {
    const list=context.channels.slice(0,12).map(c=>{
      if(c.type===1 && c.writable)return make('switch',c.name,{device_id:c.device_id,channel:c.number});
      if(c.writable&&c.minimum===0&&c.maximum===1)return make('switch',c.name,{device_id:c.device_id,channel:c.number,on_value:1,off_value:0,
        on_label:'1',off_label:'0'});
      if(c.writable)return make('input',c.name,{device_id:c.device_id,channel:c.number});
      if(numeric.has(c.type)&&c.minimum!=null&&c.maximum!=null&&c.minimum<c.maximum)return make('gauge',c.name,{device_id:c.device_id,channel:c.number,minimum:c.minimum,maximum:c.maximum});
      return make('value',c.name,{device_id:c.device_id,channel:c.number});
    });
    const metric=context.telemetry.find(t=>typeof t.value==='number')?.metric;
    if(metric){const t=context.telemetry.find(t=>t.metric===metric);list.push(make('chart',metric,{device_id:t.device_id,metric,source:'telemetry',width:2}));}
    return {id:'',name:context.device.name+' dashboard',widgets:list,revision:0};
  }
  async function refresh(data) {
    const changed=context?.device.id!==data.device.id;
    if(changed)reset();
    context=data;
    const myGeneration=generation, myLayoutEpoch=layoutEpoch, deviceId=data.device.id;
    const list=await api(root());
    if(myGeneration!==generation||context?.device.id!==deviceId)return;
    if(myLayoutEpoch!==layoutEpoch){render();return;}
    boards=list;
    if(!boards.some(b=>b.id===active))active=boards[0]?.id||'';
    const latest=boards.find(b=>b.id===active);
    if(!editing){
      const wasPreview=!board?.id;
      board=latest||(!changed&&wasPreview&&board?board:starter());
      draft=null;
    }else if(latest&&latest.revision!==board.revision){
      $('board-caption').textContent='Another session changed this layout. Cancel to load it; your unsaved edits remain here.';
    }
    render();
  }
  function reset() {
    pauseSensors();generation++;layoutEpoch++;context=null;boards=[];active='';board=draft=null;
    editing=dirty=false;stamp='';pending.clear();$('widget-grid').replaceChildren();
  }
  function canLeave() {
    if(!dirty)return true;
    notice(Error('Save or cancel your layout edits before leaving this dashboard.'));
    return false;
  }
  function visibility(view) {
    if(view!=='dashboard')pauseSensors();
    if(view==='settings')capabilities();
    if(view==='dashboard')updateReadings();
  }
  function render() {
    if(!context||!current())return;
    const b=current(), viewer=context.role==='viewer';
    $('board-select').innerHTML=boards.length?boards.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join(''):'<option value="">Starter layout</option>';
    $('board-select').value=active;
    $('board-select').disabled=editing;
    $('board-name').textContent=b.name;
    if(!editing||!boards.find(x=>x.id===active)||boards.find(x=>x.id===active)?.revision===board.revision)
      $('board-caption').textContent=editing?'Arrange and configure widgets, then save your layout.':b.id?'Saved on your server · synced between devices':'Starter layout · Edit and save to sync between devices';
    $('board-mode').textContent=editing?(dirty?'EDIT MODE · UNSAVED':'EDIT MODE'):'RUN MODE';
    $('board-edit').classList.toggle('hidden',editing);
    $('board-save').classList.toggle('hidden',!editing);
    $('board-cancel').classList.toggle('hidden',!editing);
    $('editor-toolbar').classList.toggle('hidden',!editing);
    $('board-edit').disabled=$('board-new').disabled=viewer;
    $('board-new').disabled=viewer||editing;
    $('board-delete').disabled=!board.id;
    $('widget-add').disabled=b.widgets.length>=48;
    $('board-network').textContent=offline?'Offline · controls unavailable':context.device.online?'Device online':'Device offline · commands may expire before delivery';
    $('widget-manual').disabled=editing||viewer;
    const nextStamp=JSON.stringify([b.widgets,editing,context.device.id]);
    if(stamp!==nextStamp){
      pauseSensors();stamp=nextStamp;
      $('widget-grid').innerHTML=b.widgets.map(card).join('')||'<div class="empty widget-empty"><h2>Make this dashboard yours</h2><p>Switch to Edit layout and add your first widget.</p></div>';
      bindCards();
    }
    updateReadings();
  }
  function card(w,i) {
    let body='';
    const title=esc(w.title), disabled=editing||context.role==='viewer'||offline;
    if(w.kind==='switch')body=`<button class="widget-switch" role="switch" aria-checked="false" aria-label="${title}" data-action="switch" ${disabled?'disabled':''}><span class="switch-track"><span class="switch-knob"></span></span><strong data-part="switch-label">—</strong></button>`;
    if(w.kind==='button')body=`<button class="widget-button" data-action="button" ${disabled?'disabled':''}>${esc(w.on_label)}</button><small>Sends ${esc(fmt(w.on_value))}</small>`;
    if(w.kind==='slider')body=`<strong class="widget-value" data-part="reading">—</strong><input data-action="slider" type="range" min="${w.minimum}" max="${w.maximum}" step="${w.step}" aria-label="${title}" ${disabled?'disabled':''}><div class="range-labels"><span>${w.minimum}</span><span>${w.maximum}</span></div>`;
    if(w.kind==='input'){
      const c=channelOf(w);
      body=c?`<form data-action="input" class="widget-input">${valueInput(c)}<button ${disabled?'disabled':''}>Send</button></form>`:'<p>Channel unavailable</p>';
    }
    if(w.kind==='value')body='<strong class="widget-value" data-part="reading">—</strong>';
    if(w.kind==='gauge')body=`<canvas data-part="gauge" height="130" role="img" aria-label="${title} gauge"></canvas><strong class="gauge-value" data-part="reading">—</strong><div class="range-labels"><span>${w.minimum} ${esc(w.unit)}</span><span>${w.maximum} ${esc(w.unit)}</span></div>`;
    if(w.kind==='led')body='<div class="led-row"><span class="widget-led" data-part="led"></span><strong data-part="reading">Waiting</strong></div>';
    if(w.kind==='chart')body=`<strong class="chart-value" data-part="reading">Waiting for measurements</strong><canvas data-part="chart" height="145" role="img" aria-label="${title} telemetry chart"></canvas>`;
    if(extraBody(w,disabled))body=extraBody(w,disabled);
    if(w.kind==='text')body=`<p class="widget-text">${esc(w.text)}</p>`;
    if(sensors.has(w.kind)){
      const cap=capability(w.kind);
      body=(w.kind==='camera'?'<video data-part="video" autoplay muted playsinline></video>':'<pre class="sensor-value" data-part="sensor-reading">No reading yet</pre>')+
        (w.kind==='microphone'?'<meter data-part="meter" min="0" max="100" value="0" aria-label="Relative microphone level"></meter>':'')+
        `<p data-part="sensor-status" class="sensor-status">${esc(cap.label)}</p><div class="sensor-actions"><button data-action="sensor-start" ${!cap.ok||editing?'disabled':''}>${w.kind==='serial'||w.kind==='bluetooth'?'Connect':'Start'}</button><button data-action="sensor-stop" class="secondary" disabled>Stop</button></div><small>Local browser input · never uploaded</small>`;
    }
    const tools=editing?`<div class="widget-edit-tools"><button data-edit="settings" aria-label="Configure ${title}">Configure</button><button data-edit="left" aria-label="Move ${title} earlier" ${i===0?'disabled':''}>←</button><button data-edit="right" aria-label="Move ${title} later" ${i===current().widgets.length-1?'disabled':''}>→</button><button data-edit="remove" aria-label="Remove ${title}">Delete</button></div>`:'';
    return `<article class="widget width-${w.width} color-${w.color} ${editing?'editing':''}" data-widget="${w.id}" draggable="${editing}"><div class="widget-head"><h3>${title}</h3><span>${esc(catalog[w.kind][0])}</span></div>${tools}<div class="widget-body">${body}</div><div class="widget-foot" data-part="foot"></div></article>`;
  }
  function bindCards() {
    current().widgets.forEach(w=>{
      const el=document.querySelector(`[data-widget="${w.id}"]`);
      el.querySelector('[data-action="switch"]')?.addEventListener('click',()=>{
        const c=channelOf(w);
        send(w,equal(c?.desired??c?.reported,w.on_value)?w.off_value:w.on_value);
      });
      el.querySelector('[data-action="button"]')?.addEventListener('click',()=>send(w,w.on_value));
      const slider=el.querySelector('[data-action="slider"]');
      slider?.addEventListener('input',()=>{element(w.id,'reading').textContent=slider.value+' '+w.unit;});
      slider?.addEventListener('change',()=>send(w,Number(slider.value)));
      el.querySelector('[data-action="input"]')?.addEventListener('submit',e=>{
        e.preventDefault();const c=channelOf(w);
        try{send(w,parse(c,new FormData(e.target).get('value')));}catch(error){notice(error);}
      });
      bindExtra(w,el);
      el.querySelector('[data-action="sensor-start"]')?.addEventListener('click',()=>startSensor(w));
      el.querySelector('[data-action="sensor-stop"]')?.addEventListener('click',()=>stopSensor(w.id));
      el.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{
        const index=draft.widgets.findIndex(x=>x.id===w.id);
        if(b.dataset.edit==='settings')return widgetModal(w);
        if(b.dataset.edit==='remove'){return modal('Delete widget and release pins',`<p>Delete “${esc(w.title)}”? Its allocated pins will return to your pool when you save the layout. Shared references will block release and be listed.</p>`,async()=>{draft.widgets.splice(index,1);markDirty();},'Delete widget');}
        else{const to=index+(b.dataset.edit==='left'?-1:1);[draft.widgets[index],draft.widgets[to]]=[draft.widgets[to],draft.widgets[index]];}
        markDirty();
      });
      el.addEventListener('dragstart',e=>{if(!editing||e.target.closest('input,button,select,form')){e.preventDefault();return;}dragging=w.id;e.dataTransfer.setData('text/plain',w.id);e.dataTransfer.effectAllowed='move';});
      el.addEventListener('dragover',e=>{if(editing&&dragging){e.preventDefault();el.classList.add('drag-over');}});
      el.addEventListener('dragleave',()=>el.classList.remove('drag-over'));
      el.addEventListener('drop',e=>{e.preventDefault();el.classList.remove('drag-over');if(!editing||!dragging||dragging===w.id)return;const from=draft.widgets.findIndex(x=>x.id===dragging),to=draft.widgets.findIndex(x=>x.id===w.id);if(from<0)return;const [moved]=draft.widgets.splice(from,1);draft.widgets.splice(to,0,moved);dragging='';markDirty();});
      el.addEventListener('dragend',()=>{dragging='';document.querySelectorAll('.drag-over').forEach(x=>x.classList.remove('drag-over'));});
    });
  }
  async function send(w,value) {
    if(editing||offline||context.role==='viewer'||pending.has(w.id))return;
    const deviceId=w.device_id,myGeneration=generation;
    pending.add(w.id);updateReadings();
    try{
      await api(`/api/devices/${deviceId}/channels/${w.channel}/write`,'POST',{value,manual_s:Number($('widget-manual').value),request_id:requestID(),ttl_s:30});
      if(myGeneration===generation)await reload();
    }catch(error){notice(error);}
    finally{if(myGeneration===generation){pending.delete(w.id);updateReadings();}}
  }
  function reading(w) {
    if(w.source==='telemetry'){const t=context.telemetry.find(x=>x.device_id===w.device_id&&x.metric===w.metric);return {value:t?.value,time:t?.received_ms,quality:t?.quality};}
    const c=channelOf(w);
    return {value:w.source==='desired'?c?.desired:c?.reported,time:c?.reported_ms};
  }
  function updateReadings() {
    if(!context||!current())return;
    current().widgets.forEach(w=>{
      if(sensors.has(w.kind)||w.kind==='text')return;
      if(extraReading(w))return;
      const c=channelOf(w), r=reading(w), value=r.value;
      const el=document.querySelector(`[data-widget="${w.id}"]`);if(!el)return;
      const disabled=editing||offline||context.role==='viewer'||pending.has(w.id)||!c?.writable;
      if(controls.has(w.kind)){
        el.querySelectorAll('.widget-body button,.widget-body input,.widget-body select').forEach(x=>x.disabled=disabled);
        const latest=context.commands.find(x=>x.device_id===w.device_id&&x.channel===w.channel);
        element(w.id,'foot').textContent=`${deviceOf(w)?.name||'Device'} · V${w.channel} · Reported ${fmt(c?.reported)} · Desired ${fmt(c?.desired)}${latest?' · '+latest.status:''}${pending.has(w.id)?' · Sending…':''}`;
        if(w.kind==='switch'){
          const on=equal(c?.desired??c?.reported,w.on_value),button=el.querySelector('[role="switch"]');
          button.setAttribute('aria-checked',String(on));element(w.id,'switch-label').textContent=on?w.on_label:w.off_label;
        }
        if(w.kind==='slider'){
          const input=el.querySelector('input[type="range"]');
          if(document.activeElement!==input){const v=c?.desired??value;input.value=v??w.minimum;element(w.id,'reading').textContent=v==null?'—':display(v,w)+' '+w.unit;}
        }
        return;
      }
      const source=(deviceOf(w)?.name||'')+' · '+(w.source==='telemetry'?w.metric:`V${w.channel} · ${w.source}`);
      element(w.id,'foot').textContent=source+(r.time?' · '+time(r.time):' · no reading')+(r.quality?' · quality '+r.quality:'');
      const output=element(w.id,'reading');
      if(output)output.textContent=display(value,w)+(value!=null&&w.unit?' '+w.unit:'');
      if(w.kind==='led'){
        const lit=value!=null&&equal(value,w.on_value);
        element(w.id,'led').classList.toggle('lit',lit);
        output.textContent=value==null?'Waiting':lit?w.on_label:w.off_label;
      }
      if(w.kind==='gauge')drawGauge(element(w.id,'gauge'),value,w);
      if(w.kind==='chart')drawPlot(element(w.id,'chart'),w);
    });
  }
  function canvasContext(canvas,height) {
    const width=Math.max(1,canvas.clientWidth),dpr=Math.min(2,window.devicePixelRatio||1);
    canvas.width=width*dpr;canvas.height=height*dpr;
    const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);return {ctx,width};
  }
  function accent(w){return {mint:'#62e2bf',blue:'#75bfff',amber:'#ffc16e',rose:'#fa96b5'}[w.color];}
  function drawGauge(canvas,value,w) {
    if(!canvas?.clientWidth)return;
    const {ctx,width}=canvasContext(canvas,130),radius=Math.max(1,Math.min(width/2-20,96)),x=width/2,y=113;
    ctx.lineWidth=13;ctx.lineCap='round';ctx.strokeStyle='#26333c';ctx.beginPath();ctx.arc(x,y,radius,Math.PI,2*Math.PI);ctx.stroke();
    if(typeof value==='number'&&Number.isFinite(value)){
      const ratio=Math.max(0,Math.min(1,(value-w.minimum)/(w.maximum-w.minimum)));
      if(ratio>0){ctx.strokeStyle=accent(w);ctx.beginPath();ctx.arc(x,y,radius,Math.PI,Math.PI+ratio*Math.PI);ctx.stroke();}
    }
  }
  function drawPlot(canvas,w) {
    if(!canvas?.clientWidth)return;
    const {ctx,width}=canvasContext(canvas,160),series=w.series?.length?w.series:[{device_id:w.device_id,metric:w.metric,title:w.metric}];
    const lists=series.map(s=>context.telemetry.filter(t=>t.device_id===(s.device_id||w.device_id)&&t.metric===s.metric&&typeof t.value==='number'&&Number.isFinite(t.value)&&t.quality===0).slice().reverse());
    const all=lists.flat();ctx.fillStyle='#879ca9';ctx.font='10px system-ui';
    if(!all.length){ctx.fillText('No data in the selected time range',15,70);return;}
    let lo=Math.min(...all.map(p=>p.value)),hi=Math.max(...all.map(p=>p.value));if(lo===hi){lo-=1;hi+=1;}
    let start=Math.min(...all.map(p=>Number(p.received_ms))),end=Math.max(...all.map(p=>Number(p.received_ms)));
    ctx.fillText(display(hi,w),0,13);ctx.fillText(display(lo,w),0,118);
    const colours=['#62e2bf','#75bfff','#ffc16e','#fa96b5'];
    lists.forEach((points,j)=>{ctx.strokeStyle=ctx.fillStyle=colours[j%4];ctx.lineWidth=2;ctx.beginPath();let oldY=0;
      points.forEach((p,i)=>{const x=38+(width-50)*(end===start?.5:(Number(p.received_ms)-start)/(end-start)),y=15+100*(hi-p.value)/(hi-lo);
        if(w.chart_mode==='bar')ctx.fillRect(x, y,Math.max(2,(width-50)/Math.max(1,points.length*lists.length)-2),115-y);
        else if(w.chart_mode==='point'){ctx.moveTo(x+2,y);ctx.arc(x,y,2,0,Math.PI*2);}
        else {if(!i)ctx.moveTo(x,y);else {if(w.chart_mode==='state')ctx.lineTo(x,oldY);ctx.lineTo(x,y);}}oldY=y;});
      if(w.chart_mode==='point')ctx.fill();else ctx.stroke();ctx.fillText(series[j].title||series[j].metric,38+j*95,145,90);});
    element(w.id,'reading').textContent=lists.map((ps,i)=>(series[i].title||series[i].metric)+': '+(ps.length?display(ps.at(-1).value,w):'—')).join(' · ');
  }
  function markDirty(){dirty=true;render();}
  $('board-select').onchange=e=>{if(!canLeave()){e.target.value=active;return;}pauseSensors();active=e.target.value;board=boards.find(x=>x.id===active);draft=null;stamp='';render();};
  $('board-edit').onclick=()=>{if(!board)return;pauseSensors();editing=true;dirty=false;draft=clone(board);render();};
  $('board-cancel').onclick=()=>{editing=dirty=false;draft=null;board=boards.find(x=>x.id===active)||board;stamp='';render();};
  $('board-save').onclick=async()=>{
    const button=$('board-save');button.disabled=true;
    try{
      const body={name:draft.name,widgets:draft.widgets};if(board.id)body.revision=board.revision;
      const result=await api(root()+(board.id?'/'+board.id:''),board.id?'PUT':'POST',body);
      layoutEpoch++;boards=[...boards.filter(b=>b.id!==result.id),result];board=result;active=result.id;draft=null;editing=dirty=false;stamp='';await reload();render();
    }catch(error){notice(error);}finally{button.disabled=false;}
  };
  $('board-new').onclick=()=>modal('New dashboard','<label>Name<input name="name" required maxlength="80" placeholder="Living room"></label><label><input type="checkbox" name="starter" checked> Start with this account’s channels</label>',async f=>{
    const base=f.has('starter')?starter():{widgets:[]};
    const result=await api(root(),'POST',{name:f.get('name'),widgets:base.widgets});layoutEpoch++;boards=[...boards.filter(b=>b.id!==result.id),result];active=result.id;board=result;stamp='';
  },'Create dashboard');
  $('widget-help').onclick=()=>showWidgetHelp();
  $('board-rename').onclick=()=>modal('Rename dashboard',`<label>Name<input name="name" required maxlength="80" value="${esc(draft.name)}"></label>`,async f=>{draft.name=f.get('name');markDirty();});
  $('board-delete').onclick=()=>modal('Delete dashboard',`<p>Delete the saved layout “${esc(board.name)}” and release its pins? Shared references will block deletion.</p>`,async()=>{await api(root()+'/'+board.id+'?revision='+board.revision,'DELETE');layoutEpoch++;boards=boards.filter(b=>b.id!==board.id);active='';board=draft=null;editing=dirty=false;stamp='';},'Delete layout');
  $('widget-add').onclick=()=>{
    modal('Add a widget','<div class="widget-library">'+Object.entries(catalog).map(([kind,[title,detail]])=>`<div class="widget-choice"><button type="button" class="secondary" data-kind="${kind}"><strong>${esc(title)}</strong><small>${esc(detail)}</small></button><button type="button" class="text-button" data-kind-help="${kind}" aria-label="How to use ${esc(title)}">Help</button></div>`).join('')+'</div>',null);
    document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{$('modal').close();widgetModal(make(b.dataset.kind,catalog[b.dataset.kind][0]),true);});
    document.querySelectorAll('[data-kind-help]').forEach(b=>b.onclick=()=>showWidgetHelp(b.dataset.kindHelp));
  };
  function widgetModal(w,isNew=false) {
    const choice=(items,current)=>items.map(([v,label])=>`<option value="${esc(v)}" ${String(v)===String(current)?'selected':''}>${esc(label)}</option>`).join('');
    const needsPin=controls.has(w.kind)||['value','gauge','led','progress','map'].includes(w.kind);
    const dev=w.device_id||selected||context.devices[0]?.id||'';
    let html=`<details class="widget-inline-help"><summary>How to use ${esc(catalog[w.kind][0])}</summary><p>${esc(widgetHelp[w.kind]||catalog[w.kind][1])}</p></details><label>Title<input name="title" required maxlength="80" value="${esc(w.title)}"></label><div class="two"><label>Width<select name="width">${choice([[1,'Standard'],[2,'Wide']],w.width)}</select></label><label>Colour<select name="color">${choice(['mint','blue','amber','rose'].map(v=>[v,v]),w.color)}</select></label></div>`;
    if(!sensors.has(w.kind)&&w.kind!=='text'&&w.kind!=='navigation')html+=`<label>Device<select name="device_id" id="widget-device">${choice(context.devices.map(d=>[d.id,d.name]),dev)}</select></label>`;
    if(needsPin)html+='<label>Pin<select name="channel" id="widget-channel"></select></label>';
    if(['joystick','map'].includes(w.kind))html+='<label>Second pin (Y / longitude)<select name="channel_y" id="widget-channel-y"></select></label>';
    if(['value','gauge','progress'].includes(w.kind))html+=`<label>Source<select name="source" id="widget-source">${choice(['reported','desired','telemetry'].map(v=>[v,v]),w.source)}</select></label>`;
    if(['value','gauge','progress','chart'].includes(w.kind))html+=`<label>Telemetry metric<input name="metric" value="${esc(w.metric)}" placeholder="temperature"></label>`;
    if(['value','gauge','progress','slider','stepper','chart'].includes(w.kind))html+=`<div class="two"><label>Unit<input name="unit" value="${esc(w.unit)}" maxlength="16"></label><label>Decimals<input name="precision" type="number" min="0" max="6" value="${w.precision}"></label></div>`;
    if(['slider','gauge','progress','joystick','stepper'].includes(w.kind))html+=`<div class="two"><label>Minimum<input name="minimum" type="number" step="any" value="${w.minimum}"></label><label>Maximum<input name="maximum" type="number" step="any" value="${w.maximum}"></label></div><label>Step<input name="step" type="number" min="0.000001" step="any" value="${w.step}"></label>`;
    if(['switch','button','led'].includes(w.kind))html+='<div id="widget-values"></div>';
    if(w.kind==='selector')html+=`<label>Options, one Label=value per line<textarea name="options" rows="5">${esc((w.options||[]).map(o=>o.label+'='+fmt(o.value)).join('\n'))}</textarea></label>`;
    if(w.kind==='chart')html+=`<label>Chart style<select name="chart_mode">${choice(['line','bar','point','state'].map(v=>[v,v]),w.chart_mode)}</select></label><div id="series-list"></div><button type="button" id="series-add">Add another series</button>`;
    if(w.kind==='navigation')html+=`<label>Dashboard<select name="target_dashboard">${choice(boards.map(b=>[b.id,b.name]),w.target_dashboard)}</select></label>`;
    if(w.kind==='map')html+=`<label>Zoom<input name="zoom" type="number" min="1" max="18" value="${w.zoom||4}"></label><label><input name="map_tiles" type="checkbox" ${w.map_tiles?'checked':''}> Load OpenStreetMap tiles (connects to OpenStreetMap)</label>`;
    if(['floorplan','process'].includes(w.kind))html+='<label>Background image (PNG/JPEG/WebP, up to 350 KB)<input name="image_file" type="file" accept="image/png,image/jpeg,image/webp"></label><p>Click the preview to position a point, then choose a pin.</p><div id="point-preview" class="point-preview"></div><div class="two"><label>Pin<select id="point-pin"></select></label><label>Symbol<select id="point-symbol"><option>sensor</option><option>pump</option><option>valve</option><option>tank</option><option>motor</option></select></label></div><button type="button" id="point-add">Add point</button><div id="point-list"></div>';
    if(w.kind==='text')html+=`<label>Text<textarea name="text" maxlength="500">${esc(w.text)}</textarea></label>`;
    if(w.kind==='bluetooth')html+=`<label>Service UUID<input name="service" value="${esc(w.service)}"></label><label>Characteristic UUID<input name="characteristic" value="${esc(w.characteristic)}"></label>`;
    if(w.kind==='serial')html+=`<label>Baud<select name="baud">${choice([9600,19200,38400,57600,115200,230400].map(n=>[n,n]),w.baud)}</select></label>`;
    let series=clone(w.series||[]),points=clone(w.points||[]),image=w.image||'',pos={x:50,y:50};
    modal(isNew?'Add '+catalog[w.kind][0]:'Configure '+w.title,html,async f=>{
      const next={...w,title:f.get('title'),width:Number(f.get('width')),color:f.get('color'),device_id:f.get('device_id')||'',image,points,series};
      for(const name of ['metric','unit','text','service','characteristic','source','on_label','off_label','chart_mode','target_dashboard'])if(f.has(name))next[name]=f.get(name);
      for(const name of ['channel','channel_y','minimum','maximum','step','precision','baud','zoom'])if(f.has(name))next[name]=f.get(name)===''?null:Number(f.get(name));
      if(controls.has(w.kind)||w.kind==='led')next.source='reported';
      if(w.kind==='chart')next.source='telemetry';
      if(w.kind==='map')next.map_tiles=f.has('map_tiles');
      const ch=context.channels.find(c=>c.device_id===next.device_id&&c.number===next.channel);
      if(['switch','button','led'].includes(w.kind)){if(!ch)throw Error('Choose a pin');next.on_value=parse(ch,f.get('on_value'));if(w.kind==='switch')next.off_value=parse(ch,f.get('off_value'));}
      if(w.kind==='selector')next.options=String(f.get('options')).split('\n').filter(x=>x.trim()).map(line=>{const i=line.indexOf('=');if(i<1)throw Error('Use Label=value');return {label:line.slice(0,i).trim(),value:parse(ch,line.slice(i+1).trim())};});
      if(isNew)draft.widgets.push(next);else draft.widgets[draft.widgets.findIndex(x=>x.id===w.id)]=next;
      markDirty();
    },isNew?'Add widget':'Apply');
    function pins(){const did=$('widget-device')?.value||dev;const available=context.channels.filter(c=>c.device_id===did&&(!controls.has(w.kind)||c.writable)&&(!['slider','gauge','progress','joystick','stepper','map'].includes(w.kind)||numeric.has(c.type))&&(w.kind!=='colour'||c.type===12));for(const key of ['widget-channel','widget-channel-y'])if($(key))$(key).innerHTML=choice(available.map(c=>[c.number,'V'+c.number+' · '+c.name+' ('+types[c.type]+')']),key.endsWith('-y')?w.channel_y:w.channel);values();}
    function values(){if(!$('widget-values'))return;const ch=context.channels.find(c=>c.device_id===($('widget-device')?.value||dev)&&c.number===Number($('widget-channel').value));if(!ch){$('widget-values').textContent='Allocate a compatible pin in Devices first.';return;}$('widget-values').innerHTML=valueInput(ch,'on_value')+(w.kind==='switch'?valueInput(ch,'off_value'):'')+`<label>On label<input name="on_label" value="${esc(w.on_label)}"></label><label>Off label<input name="off_label" value="${esc(w.off_label)}"></label>`;for(const name of ['on_value','off_value']){const field=$('modal-form').elements.namedItem(name);if(field){const v=isNew?(ch.type===1?name==='on_value':name==='on_value'?1:0):w[name];field.value=typeof v==='object'?JSON.stringify(v):String(v);}}}
    if($('widget-device'))$('widget-device').onchange=pins;if($('widget-channel'))$('widget-channel').onchange=values;pins();
    function seriesUI(){$('series-list').innerHTML=series.map((v,i)=>`<div class="two"><label>Device<select data-series-device="${i}">${choice(context.devices.map(d=>[d.id,d.name]),v.device_id)}</select></label><label>Metric<input data-series-metric="${i}" value="${esc(v.metric)}"></label><button type="button" data-series-remove="${i}">Remove series</button></div>`).join('');document.querySelectorAll('[data-series-device]').forEach(e=>e.onchange=()=>series[Number(e.dataset.seriesDevice)].device_id=e.value);document.querySelectorAll('[data-series-metric]').forEach(e=>e.oninput=()=>series[Number(e.dataset.seriesMetric)].metric=e.value);document.querySelectorAll('[data-series-remove]').forEach(e=>e.onclick=()=>{series.splice(Number(e.dataset.seriesRemove),1);seriesUI();});}
    if($('series-add')){$('series-add').onclick=()=>{if(series.length<8){series.push({device_id:dev,metric:''});seriesUI();}};seriesUI();}
    function pointsUI(){$('point-preview').style.backgroundImage=image?`url("${image}")`:'none';$('point-preview').innerHTML=points.map(p=>`<span style="left:${p.x}%;top:${p.y}%">${esc(p.label||p.symbol)} V${p.channel}</span>`).join('');$('point-list').innerHTML=points.map((p,i)=>`<p>${esc(p.label)} · ${p.x.toFixed(0)}%, ${p.y.toFixed(0)}% <button type="button" data-point-remove="${i}">Remove</button></p>`).join('');document.querySelectorAll('[data-point-remove]').forEach(e=>e.onclick=()=>{points.splice(Number(e.dataset.pointRemove),1);pointsUI();});}
    if($('point-preview')){$('point-pin').innerHTML=choice(context.channels.map(c=>[c.device_id+'|'+c.number,(context.devices.find(d=>d.id===c.device_id)?.name||'')+' · V'+c.number+' '+c.name]),'');$('point-preview').onclick=e=>{const r=e.currentTarget.getBoundingClientRect();pos={x:Math.max(0,Math.min(100,100*(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(100,100*(e.clientY-r.top)/r.height))};};$('point-add').onclick=()=>{const [did,pin]=$('point-pin').value.split('|');if(!did)return;points.push({device_id:did,channel:Number(pin),...pos,label:$('point-symbol').value,symbol:$('point-symbol').value});pointsUI();};$('modal-form').elements.image_file.onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>350000){$('modal-error').textContent='Use an image smaller than 350 KB';return;}image=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});pointsUI();};pointsUI();}
  }
  function extraBody(w,disabled){
    if(w.kind==='selector')return `<select data-action="selector" ${disabled?'disabled':''}>${w.options.map((o,i)=>`<option value="${i}">${esc(o.label)}</option>`).join('')}</select>`;
    if(w.kind==='colour')return `<input type="color" data-action="colour" aria-label="${esc(w.title)}" ${disabled?'disabled':''}>`;
    if(w.kind==='joystick')return `<div class="joystick" data-action="joystick" role="group" aria-label="${esc(w.title)}"><span>Drag to position</span><i></i></div><div class="two"><label>X<input type="number" data-axis="x" min="${w.minimum}" max="${w.maximum}" step="${w.step}"></label><label>Y<input type="number" data-axis="y" min="${w.minimum}" max="${w.maximum}" step="${w.step}"></label></div><button data-action="axes">Send axes</button><small>Release to send; X/Y writes are separate commands.</small>`;
    if(w.kind==='stepper')return '<div class="two"><button data-step="-1">−</button><button data-step="1">+</button></div><strong data-part="reading"></strong>';
    if(w.kind==='progress')return '<progress data-part="progress" max="100"></progress><strong data-part="reading"></strong>';
    if(w.kind==='status')return '<strong data-part="reading"></strong><p data-part="status-detail"></p>';
    if(w.kind==='table')return '<div data-part="table" class="table-wrap"></div>';
    if(w.kind==='navigation')return '<button data-action="navigate">Open dashboard →</button>';
    if(w.kind==='schedule')return '<button data-action="schedule">Manage schedules</button><div data-part="schedule-list"></div>';
    if(w.kind==='map')return '<div class="location-map" data-part="map"></div><p data-part="reading"></p>';
    if(['floorplan','process'].includes(w.kind))return `<div class="process-view" data-part="process" style="${w.image?'background-image:url('+esc(w.image)+')':''}"></div>`;
    return '';
  }
  function bindExtra(w,el){
    el.querySelector('[data-action=selector]')?.addEventListener('change',e=>send(w,w.options[Number(e.target.value)].value));
    el.querySelector('[data-action=colour]')?.addEventListener('change',e=>send(w,e.target.value));
    el.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>send(w,Math.max(w.minimum,Math.min(w.maximum,Number(channelOf(w)?.desired??channelOf(w)?.reported??w.minimum)+Number(b.dataset.step)*w.step))));
    async function axes(){const x=el.querySelector('[data-axis=x]'),y=el.querySelector('[data-axis=y]');await send(w,Number(x.value));await send({...w,channel:w.channel_y},Number(y.value));}
    el.querySelector('[data-action=axes]')?.addEventListener('click',axes);
    const joy=el.querySelector('.joystick');if(joy){const set=e=>{if(editing||offline||context.role==='viewer')return;const r=joy.getBoundingClientRect(),x=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y=1-Math.max(0,Math.min(1,(e.clientY-r.top)/r.height));for(const [axis,ratio] of [['x',x],['y',y]])el.querySelector('[data-axis='+axis+']').value=Math.round((w.minimum+ratio*(w.maximum-w.minimum))/w.step)*w.step;joy.querySelector('i').style.cssText=`left:${x*100}%;top:${(1-y)*100}%`;};joy.onpointerdown=e=>{joy.setPointerCapture(e.pointerId);set(e);};joy.onpointermove=e=>{if(joy.hasPointerCapture(e.pointerId))set(e);};joy.onpointerup=e=>{if(joy.hasPointerCapture(e.pointerId)){joy.releasePointerCapture(e.pointerId);axes();}};}
    el.querySelector('[data-action=navigate]')?.addEventListener('click',()=>{if(!canLeave())return;const b=boards.find(b=>b.id===w.target_dashboard);if(b){active=b.id;board=b;draft=null;stamp='';render();}});
    el.querySelector('[data-action=schedule]')?.addEventListener('click',()=>window.OmniApp.schedule(w.device_id));
  }
  function extraReading(w){
    const el=document.querySelector(`[data-widget="${w.id}"]`);if(!el)return true;
    const c=channelOf(w),v=c?.reported,d=deviceOf(w),disabled=editing||offline||context.role==='viewer';
    if(['selector','colour','joystick','stepper'].includes(w.kind)){
      el.querySelectorAll('button,input,select').forEach(x=>{if(!x.closest('.widget-edit-tools'))x.disabled=disabled||!c?.writable;});
      if(w.kind==='selector'&&document.activeElement!==el.querySelector('select'))el.querySelector('select').value=w.options.findIndex(o=>equal(o.value,c?.desired??v));
      if(w.kind==='colour'&&/^#[0-9a-f]{6}$/i.test(c?.desired??v??''))el.querySelector('input[type=color]').value=c.desired??v;
      if(w.kind==='stepper')element(w.id,'reading').textContent=fmt(c?.desired??v);
      element(w.id,'foot').textContent=`${d?.name||''} · V${w.channel}${w.channel_y!=null?' / V'+w.channel_y:''} · Reported ${fmt(v)}`;return true;
    }
    if(w.kind==='progress'){element(w.id,'progress').value=Math.max(0,Math.min(100,100*(Number(reading(w).value)-w.minimum)/(w.maximum-w.minimum)));element(w.id,'reading').textContent=display(reading(w).value,w)+' '+w.unit;return true;}
    if(w.kind==='status'){element(w.id,'reading').textContent=d?.online?'● Online':'○ Offline';element(w.id,'status-detail').textContent=(d?.name||'Device unavailable')+' · Last contact '+time(d?.last_seen_ms);return true;}
    if(w.kind==='table'){element(w.id,'table').innerHTML='<table><thead><tr><th>Pin</th><th>Name</th><th>Reported</th><th>Desired</th></tr></thead><tbody>'+context.channels.filter(c=>c.device_id===w.device_id).map(c=>`<tr><td>V${c.number}</td><td>${esc(c.name)}</td><td>${esc(fmt(c.reported))}</td><td>${esc(fmt(c.desired))}</td></tr>`).join('')+'</tbody></table>';return true;}
    if(w.kind==='navigation')return true;
    if(w.kind==='schedule'){el.querySelector('[data-action=schedule]').disabled=disabled;return true;}
    if(w.kind==='map'){
      const lat=Number(c?.reported),lon=Number(channelOf(w,w.channel_y)?.reported),map=element(w.id,'map');if(c?.reported==null||channelOf(w,w.channel_y)?.reported==null||Math.abs(lat)>90||Math.abs(lon)>180){map.textContent='Waiting for valid latitude / longitude pins';return true;}
      element(w.id,'reading').textContent=lat.toFixed(5)+', '+lon.toFixed(5);
      const fingerprint=[lat,lon,w.zoom,w.map_tiles].join('|');if(map.dataset.position===fingerprint)return true;map.dataset.position=fingerprint;
      if(!w.map_tiles){map.innerHTML='<span class="map-marker">●</span><p>Coordinates available. Enable map tiles in widget settings for a geographic background.</p>';return true;}
      const z=w.zoom,N=2**z,x=(lon+180)/360*N,y=(1-Math.asinh(Math.tan(Math.max(-85,Math.min(85,lat))*Math.PI/180))/Math.PI)/2*N;
      map.innerHTML='<div class="tile-centre">'+[-1,0,1].flatMap(dy=>[-1,0,1].map(dx=>{const tx=(Math.floor(x)+dx+N)%N,ty=Math.floor(y)+dy;return ty<0||ty>=N?'':`<img alt="Map tile" referrerpolicy="origin" loading="lazy" src="https://tile.openstreetmap.org/${z}/${tx}/${ty}.png" style="left:${(Math.floor(x)+dx-x)*256}px;top:${(Math.floor(y)+dy-y)*256}px">`;})).join('')+'</div><span class="map-marker">●</span><a class="map-credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>';return true;
    }
    if(['floorplan','process'].includes(w.kind)){element(w.id,'process').innerHTML=w.points.map(p=>{const c=context.channels.find(c=>c.device_id===p.device_id&&c.number===p.channel);const symbol={pump:'◉',valve:'⋈',tank:'▤',motor:'⚙',sensor:'●'}[p.symbol]||'●';return `<button class="process-point ${c?.reported?'active':''}" style="left:${p.x}%;top:${p.y}%" title="${esc(p.label)}"><strong>${symbol}</strong><span>${esc(p.label)} · V${p.channel}<br>${esc(fmt(c?.reported))}</span></button>`;}).join('');return true;}
    return false;
  }

  function sensorStatus(wid,message){const el=element(wid,'sensor-status');if(el)el.textContent=message;}
  function sensorValue(wid,message){const el=element(wid,'sensor-reading');if(el)el.textContent=message;}
  async function startSensor(w) {
    if(sessions.has(w.id)||editing)return;
    const cap=capability(w.kind);if(!cap.ok)return sensorStatus(w.id,cap.label);
    const state={active:true,cleanup:()=>{},started:Date.now()};sessions.set(w.id,state);
    const el=document.querySelector(`[data-widget="${w.id}"]`);
    el.querySelector('[data-action="sensor-start"]').disabled=true;
    el.querySelector('[data-action="sensor-stop"]').disabled=false;
    sensorStatus(w.id,'Waiting for permission or a device…');
    try{
      if(w.kind==='location'){
        const watch=navigator.geolocation.watchPosition(p=>{
          if(!state.active)return;
          const c=p.coords;
          sensorValue(w.id,`Latitude  ${short(c.latitude)}°\nLongitude ${short(c.longitude)}°\nAccuracy  ±${short(c.accuracy)} m\nAltitude  ${short(c.altitude)} m\nSpeed     ${short(c.speed)} m/s`);
          sensorStatus(w.id,'Receiving location · '+time(p.timestamp));
        },e=>{if(state.active){stopSensor(w.id);sensorStatus(w.id,e.message||'Location unavailable');}},{enableHighAccuracy:true,maximumAge:10000,timeout:15000});
        state.cleanup=()=>navigator.geolocation.clearWatch(watch);
      }
      if(w.kind==='motion'){
        // Start permission requests together, inside the click's user activation.
        const requested=[window.DeviceOrientationEvent,window.DeviceMotionEvent].filter(x=>typeof x?.requestPermission==='function').map(x=>x.requestPermission());
        const permissions=await Promise.all(requested);
        if(permissions.some(x=>x!=='granted'))throw Error('Motion permission denied');
        if(!state.active)return;
        let orientation='',motion='',last=0,updateTimer=0;
        const publish=()=>{
          if(!state.active)return;
          const delay=100-(Date.now()-last);
          if(delay>0){if(!updateTimer)updateTimer=setTimeout(()=>{updateTimer=0;publish();},delay);return;}
          last=Date.now();sensorValue(w.id,orientation+'\n'+motion);sensorStatus(w.id,'Receiving motion · '+time(Date.now()));
        };
        const onOrientation=e=>{if([e.alpha,e.beta,e.gamma].every(x=>x==null))return;orientation=`Orientation α ${short(e.alpha)}°\nTilt β ${short(e.beta)}° / γ ${short(e.gamma)}°`+(e.webkitCompassHeading!=null?`\nCompass ${short(e.webkitCompassHeading)}°`:'');publish();};
        const onMotion=e=>{const a=e.accelerationIncludingGravity||e.acceleration,r=e.rotationRate;if(!a&&!r)return;motion=`Acceleration${e.accelerationIncludingGravity?' incl. gravity':''} (m/s²)\nX ${short(a?.x)}  Y ${short(a?.y)}  Z ${short(a?.z)}\nRotation (°/s) ${short(r?.alpha)} / ${short(r?.beta)} / ${short(r?.gamma)}`;publish();};
        window.addEventListener('deviceorientation',onOrientation);window.addEventListener('devicemotion',onMotion);
        const timeout=setTimeout(()=>{if(state.active&&!last)sensorStatus(w.id,'No motion data received. This device may not have accessible sensors.');},5000);
        state.cleanup=()=>{clearTimeout(timeout);clearTimeout(updateTimer);window.removeEventListener('deviceorientation',onOrientation);window.removeEventListener('devicemotion',onMotion);};
        sensorStatus(w.id,'Waiting for motion data…');
      }
      if(w.kind==='camera'||w.kind==='microphone'){
        const stream=await navigator.mediaDevices.getUserMedia(w.kind==='camera'?{video:{facingMode:'environment'},audio:false}:{audio:true,video:false});
        if(!state.active){stream.getTracks().forEach(t=>t.stop());return;}
        state.cleanup=()=>stream.getTracks().forEach(t=>t.stop());
        stream.getTracks().forEach(t=>t.addEventListener('ended',()=>{if(state.active){stopSensor(w.id);sensorStatus(w.id,'Input disconnected');}}));
        if(w.kind==='camera'){
          const video=element(w.id,'video');video.srcObject=stream;
          state.cleanup=()=>{stream.getTracks().forEach(t=>t.stop());video.srcObject=null;};
          await video.play();if(!state.active)return;sensorStatus(w.id,'Camera active · preview only');
        }else{
          const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Error('Web Audio is unavailable');
          const audio=new Audio(),source=audio.createMediaStreamSource(stream),analyser=audio.createAnalyser();analyser.fftSize=256;source.connect(analyser);
          const samples=new Uint8Array(analyser.fftSize);let frame=0;
          state.cleanup=()=>{cancelAnimationFrame(frame);source.disconnect();audio.close().catch(()=>{});stream.getTracks().forEach(t=>t.stop());};
          await audio.resume();if(!state.active)return;
          const sample=()=>{if(!state.active)return;analyser.getByteTimeDomainData(samples);let sum=0;for(const n of samples)sum+=((n-128)/128)**2;const level=Math.min(100,Math.sqrt(sum/samples.length)*100);sensorValue(w.id,level.toFixed(1)+'% relative RMS\nThis is not a calibrated dB reading.');element(w.id,'meter').value=level;frame=requestAnimationFrame(sample);};sample();sensorStatus(w.id,'Microphone active · level only');
        }
      }
      if(w.kind==='bluetooth'){
        const uuid=s=>/^[a-f0-9]{4,8}$/i.test(s)?Number.parseInt(s,16):s.toLowerCase();
        const device=await navigator.bluetooth.requestDevice({acceptAllDevices:true,optionalServices:[uuid(w.service)]});
        if(!state.active)return;
        const disconnected=()=>{if(state.active){stopSensor(w.id);sensorStatus(w.id,'BLE device disconnected');}};
        device.addEventListener('gattserverdisconnected',disconnected);
        state.cleanup=()=>{device.removeEventListener('gattserverdisconnected',disconnected);if(device.gatt.connected)device.gatt.disconnect();};
        const server=await device.gatt.connect();if(!state.active){state.cleanup();return;}
        const service=await server.getPrimaryService(uuid(w.service)),characteristic=await service.getCharacteristic(uuid(w.characteristic));
        const show=view=>{if(!state.active)return;const bytes=new Uint8Array(view.buffer,view.byteOffset,view.byteLength),text=new TextDecoder().decode(bytes);sensorValue(w.id,(text&&!/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]/.test(text)?text.slice(0,500)+'\n':'')+'HEX '+Array.from(bytes.slice(0,200),b=>b.toString(16).padStart(2,'0')).join(' '));sensorStatus(w.id,'Connected · '+(device.name||'BLE sensor')+' · '+time(Date.now()));};
        const handler=e=>show(e.target.value);let polling=0;
        state.cleanup=()=>{clearInterval(polling);characteristic.removeEventListener('characteristicvaluechanged',handler);device.removeEventListener('gattserverdisconnected',disconnected);if(device.gatt.connected)device.gatt.disconnect();};
        if(characteristic.properties.read)show(await characteristic.readValue());
        if(!state.active){state.cleanup();return;}
        if(characteristic.properties.notify||characteristic.properties.indicate){characteristic.addEventListener('characteristicvaluechanged',handler);await characteristic.startNotifications();}
        else if(characteristic.properties.read){let busy=false;polling=setInterval(async()=>{if(busy||!state.active)return;busy=true;try{show(await characteristic.readValue());}catch(error){stopSensor(w.id);sensorStatus(w.id,error.message);}finally{busy=false;}},1000);}
        else throw Error('This characteristic cannot be read or notify');
        if(!state.active)state.cleanup();
      }
      if(w.kind==='serial'){
        const port=await navigator.serial.requestPort();if(!state.active)return;
        await port.open({baudRate:w.baud});if(!state.active){await port.close();return;}
        state.cleanup=()=>port.close().catch(()=>{});
        if(!port.readable)throw Error('Serial port has no readable stream');
        const reader=port.readable.getReader(),decoder=new TextDecoder(),lines=[];let buffer='';
        state.cleanup=()=>{reader.cancel().catch(()=>{});};
        sensorStatus(w.id,'Serial connected · '+w.baud+' baud');
        (async()=>{
          try{while(state.active){const {value,done}=await reader.read();if(done)break;buffer=(buffer+decoder.decode(value,{stream:true})).slice(-4096);const pieces=buffer.split(/\r?\n/);buffer=pieces.pop();lines.push(...pieces);lines.splice(0,Math.max(0,lines.length-12));sensorValue(w.id,(lines.join('\n')+'\n'+buffer).slice(-4096));}}
          catch(error){if(state.active)sensorStatus(w.id,error.message);}
          finally{reader.releaseLock();await port.close().catch(()=>{});if(state.active)stopSensor(w.id);}
        })();
      }
    }catch(error){if(state.active){stopSensor(w.id);sensorStatus(w.id,error.name==='NotAllowedError'?'Permission denied. You can retry after changing browser permissions.':error.message||'Input unavailable');}}
  }
  function stopSensor(wid) {
    const state=sessions.get(wid);if(!state)return;state.active=false;sessions.delete(wid);state.cleanup();
    const el=document.querySelector(`[data-widget="${wid}"]`);
    if(el){const w=current()?.widgets.find(x=>x.id===wid);el.querySelector('[data-action="sensor-start"]').disabled=editing||!w||!capability(w.kind).ok;el.querySelector('[data-action="sensor-stop"]').disabled=true;sensorStatus(wid,'Stopped · readings remain local');}
  }
  function pauseSensors(){for(const wid of [...sessions.keys()])stopSensor(wid);}
  window.addEventListener('resize',updateReadings);
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  window.addEventListener('pagehide',pauseSensors);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseSensors();});
  window.addEventListener('offline',()=>{offline=true;render();});
  window.addEventListener('online',()=>{offline=false;render();reload().catch(notice);});
  window.OmniWidgets={refresh,reset,canLeave,visibility,pauseSensors,exportBoard:()=>clone(board),openBoard:bid=>{if(!canLeave())return;active=bid;board=boards.find(b=>b.id===bid);draft=null;stamp='';render();}};
  capabilities();
})();

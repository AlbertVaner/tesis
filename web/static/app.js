'use strict';
const $=id=>document.getElementById(id);
const form=$('session-form');
let current=null, token='', initialized=false, cameraShown=false, pending=false, lastRtt=null, noticeUntil=0;
const names={drone1:'Dron 1',drone2:'Dron 2',both:'Ambos drones',off:'Sin asignar'};
const directions={forward:[.10,0,0],back:[-.10,0,0],left:[0,.10,0],right:[0,-.10,0],up:[0,0,.08],down:[0,0,-.08]};
const gestures={REPOSO:'Reposo',DESPEGAR:'Despegar',ATERRIZAR:'Aterrizar',STOP:'Puño · emergencia',SEGUIR_MARKER:'Dedo medio · seguir marker 65',DETENER_SEGUIMIENTO:'Rock · detener seguimiento',ADELANTE:'Adelante',ATRAS:'Atrás',IZQUIERDA:'Izquierda',DERECHA:'Derecha',ARRIBA:'Subir',ABAJO:'Bajar'};
function notice(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);if(error)noticeUntil=Date.now()+8000;}
function fmt(value,decimals=3){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(decimals):'—';}
function field(name){return form.elements.namedItem(name);}
function options(select,values,preferred){const old=preferred??select.value;select.replaceChildren(...values.map(v=>{const o=document.createElement('option');o.value=v;o.textContent=names[v]||v;return o;}));select.value=values.includes(old)?old:values[0];}
function routes(){
 const drones=field('drones').value;const values=drones==='both'?['drone1','drone2','both']: [drones];
 options(field('left_target'),[...values,'off'],field('left_target').value||values[0]);
 options(field('right_target'),[...values,'off'],field('right_target').value||(drones==='both'?'drone2':drones));
 options(field('joystick_target'),drones==='both'?['both','drone1','drone2']:[drones]);
 const hand=field('control').value==='hands',marker=field('control').value==='joystick';
 $('hands-settings').hidden=!hand;$('joystick-settings').hidden=!marker;
 $('one-hand-setting').hidden=field('hands').value!=='one';$('two-hand-settings').hidden=field('hands').value==='one';
}
function graphs(){return [...document.querySelectorAll('[data-graph]:checked')].map(el=>el.dataset.graph);}
function config(){return {name:field('name').value,drones:field('drones').value,dry_run:field('dry_run').value==='true',control:field('control').value,hands:field('hands').value,single_hand:field('single_hand').value,left_target:field('left_target').value,right_target:field('right_target').value,joystick_target:field('joystick_target').value,marker_id:Number(field('marker_id').value),camera_index:Number(field('camera_index').value),save_csv:field('save_csv').checked,auto_graphs:field('auto_graphs').checked,graphs:graphs()};}
function fillConfig(c){for(const [k,v] of Object.entries(c)){const el=field(k);if(!el)continue;if(el.type==='checkbox')el.checked=v;else el.value=String(v);}routes();for(const k of ['left_target','right_target','joystick_target'])field(k).value=c[k];document.querySelectorAll('[data-graph]').forEach(el=>el.checked=c.graphs.includes(el.dataset.graph));routes();}
async function post(path,body={}){const started=performance.now();const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':token},body:JSON.stringify(body)});const data=await response.json();lastRtt=performance.now()-started;if(!response.ok)throw new Error(data.error||'No se pudo completar la operación');if(data.snapshot)render(data);return data;}
async function action(fn){if(pending)return;pending=true;try{await fn();}catch(e){notice(e.message,true);}finally{pending=false;}}
function makeCards(){for(const [i,key] of ['drone1','drone2'].entries()){$('drone-cards').insertAdjacentHTML('beforeend',`<article class="drone-card ${i?'d2':'d1'}" id="card-${key}"><header><h3>${names[key]}</h3><span class="state" id="state-${key}">Desconectado</span></header><div class="coordinates">${['x','y','z'].map(axis=>`<span><small>${axis.toUpperCase()} · m</small><b id="${key}-${axis}">—</b></span>`).join('')}</div><div class="drone-details"><span>Batería <b id="${key}-battery">—</b></span><span>MoCap <b id="${key}-age">—</b></span><span>EKF <b id="${key}-ekf">—</b></span></div></article>`);}}
function render(state){
 current=state;if(state.control_token)token=state.control_token;
 if(!initialized){fillConfig(state.config);initialized=true;}
 const s=state.snapshot,c=state.config,ready=s.ready&&!state.busy&&!s.emergency;
 $('real-option').disabled=!state.allow_hardware;
 $('config-fields').disabled=s.connected||state.busy;
 $('session-name').textContent=c.name;
 $('mode-badge').textContent=c.dry_run?'SIMULACIÓN':'ROBOTAT REAL';$('mode-badge').classList.toggle('real',!c.dry_run);
 $('footer-mode').textContent=c.dry_run?'Panel local · Simulación':'Panel local · Hardware real';
 $('connection-state').textContent=state.busy?'Operación en curso':s.connected?'Sistema conectado':'Sin conexión de vuelo';
 $('flight-status').textContent=s.emergency?'Emergencia enclavada':state.busy?'Procesando…':s.ready?'Preflight correcto':s.connected?'Sistema conectado':'Esperando preflight';
 $('config-state').textContent=s.connected?'Configuración fija durante la sesión':'Puedes cambiar la configuración';
 $('hardware-note').textContent=state.allow_hardware?'Modo real disponible. El preflight conserva la comprobación EKF / MoCap.':'La simulación no abre cámara, radios ni Robotat.';
 $('connect').disabled=s.connected||state.busy;
 $('finish').disabled=state.busy||!s.connected;
 const targets=c.drones==='both'?['both','drone1','drone2']:[c.drones];options($('command-target'),targets);
 const target=$('command-target').value,keys=target==='both'?['drone1','drone2']:[target];
 const anyAir=keys.some(k=>s[k].airborne),allAir=keys.every(k=>s[k].airborne);
 $('takeoff').disabled=!ready||anyAir;$('land').disabled=!ready||!anyAir;
 document.querySelectorAll('[data-direction]').forEach(b=>b.disabled=!ready||!allAir);
 for(const key of ['drone1','drone2']){const u=s[key];$('card-'+key).classList.toggle('inactive',!u.enabled);$('state-'+key).textContent=!u.enabled?'Fuera de sesión':u.airborne?'En vuelo':s.ready?'Listo':'Sin vuelo';$('state-'+key).title=u.status||'';['x','y','z'].forEach((axis,i)=>$(key+'-'+axis).textContent=fmt(u.pose?.[i]));$(key+'-battery').textContent=fmt(u.battery_v,2)+' V';$(key+'-age').textContent=fmt(u.mocap_age_s==null?null:u.mocap_age_s*1000,0)+' ms';$(key+'-ekf').textContent=fmt(u.ekf_mocap_error_m)+' m';}
 $('separation').textContent=c.drones==='both'?'Separación: '+fmt(s.separation_m)+' m':'Sesión de un dron';
 $('input-status').textContent=state.input.message;
 $('request-latency').textContent='Respuesta del panel: '+fmt(lastRtt,0)+' ms';
 $('input-panel').hidden=c.control==='buttons';$('input-title').textContent=c.control==='joystick'?'Joystick · marker '+c.marker_id:'Control con '+(c.hands==='one'?'una mano':'dos manos');
 $('input-help').textContent=c.control==='joystick'?'El marker dirige '+names[c.joystick_target]+'. Establece cero antes de moverlo.':c.hands==='one'?`${c.single_hand==='Right'?'Mano derecha':'Mano izquierda'} → ${names[c.drones]}`:`Izquierda → ${names[c.left_target]} · Derecha → ${names[c.right_target]}`;
 $('input-start').disabled=!ready||state.input.active;$('input-stop').disabled=!state.input.active;
 $('input-zero').hidden=c.control!=='joystick';$('input-zero').disabled=!state.input.active;
 $('demo-controls').hidden=!c.dry_run||!state.input.active;$('demo-hands').hidden=c.control!=='hands';$('demo-marker').hidden=c.control!=='joystick';
 $('demo-left').disabled=c.hands==='one'&&c.single_hand!=='Left';$('demo-right').disabled=c.hands==='one'&&c.single_hand!=='Right';
 const camera=state.input.camera;
 $('camera-empty').hidden=camera;$('camera-feed').classList.toggle('active',camera);
 if(camera&&!cameraShown)$('camera-feed').src='/api/camera/stream';if(!camera&&cameraShown)$('camera-feed').removeAttribute('src');cameraShown=camera;
 $('export').disabled=!state.session_id||state.exporting;$('export').textContent=state.exporting?'Generando gráficas…':'↓ Guardar gráficas';
 $('downloads').replaceChildren(...state.artifacts.slice().reverse().map(f=>{const a=document.createElement('a');a.href='/api/files/'+encodeURIComponent(f.id);a.textContent=f.name;a.title=f.path;return a;}));
 if(!state.artifacts.length){const p=document.createElement('p');p.className='empty-state';p.textContent='Los archivos de la sesión aparecerán aquí.';$('downloads').append(p);}
 $('events').replaceChildren(...state.events.slice().reverse().map(event=>{const li=document.createElement('li');li.classList.toggle('error',event.error);const t=document.createElement('time');t.textContent=event.time;const span=document.createElement('span');span.textContent=event.message;li.append(t,span);return li;}));
 if(!pending&&Date.now()>noticeUntil)notice(state.message,state.message===state.error&&!!state.error);
 drawTrajectory();
}
function drawTrajectory(){
 const canvas=$('trajectory'),rect=canvas.getBoundingClientRect();if(!rect.width)return;
 const ratio=window.devicePixelRatio||1;canvas.width=rect.width*ratio;canvas.height=rect.height*ratio;
 const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);const w=rect.width,h=rect.height;
 const data=current?.history||[];const points=data.flatMap(row=>['drone1','drone2'].filter(k=>row[k]?.enabled&&row[k]?.pose).map(k=>row[k].pose));
 $('plot-empty').hidden=points.length>0;
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);let minX=Math.min(-.2,...xs)-.2,maxX=Math.max(.2,...xs)+.2,minY=Math.min(-.2,...ys)-.2,maxY=Math.max(1.1,...ys)+.2;
 const margin={left:49,right:20,top:46,bottom:36},pw=w-margin.left-margin.right,ph=h-margin.top-margin.bottom;
 const scale=Math.min(pw/(maxX-minX),ph/(maxY-minY));const cx=(minX+maxX)/2,cy=(minY+maxY)/2;
 const x=v=>margin.left+pw/2+(v-cx)*scale,y=v=>margin.top+ph/2-(v-cy)*scale;
 ctx.font='12px Segoe UI';ctx.strokeStyle='#355346';ctx.fillStyle='#8daf9c';ctx.lineWidth=1;
 for(let i=0;i<=4;i++){let xv=minX+(maxX-minX)*i/4,yv=minY+(maxY-minY)*i/4;ctx.beginPath();ctx.moveTo(x(xv),margin.top);ctx.lineTo(x(xv),h-margin.bottom);ctx.stroke();ctx.fillText(xv.toFixed(2),x(xv)-12,h-13);ctx.beginPath();ctx.moveTo(margin.left,y(yv));ctx.lineTo(w-margin.right,y(yv));ctx.stroke();ctx.fillText(yv.toFixed(2),6,y(yv)+4);}
 for(const [key,color] of [['drone1','#b8e686'],['drone2','#67b9e5']]){const ps=data.filter(row=>row[key]?.enabled&&row[key]?.pose).map(row=>row[key].pose);if(!ps.length)continue;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ps.forEach((p,i)=>i?ctx.lineTo(x(p[0]),y(p[1])):ctx.moveTo(x(p[0]),y(p[1])));ctx.stroke();const p=ps.at(-1);ctx.fillStyle=color;ctx.beginPath();ctx.arc(x(p[0]),y(p[1]),5,0,Math.PI*2);ctx.fill();ctx.fillText(names[key],x(p[0])+10,y(p[1])-9);}
}
function command(action,delta=[0,0,0]){return post('/api/command',{action,target:$('command-target').value,dx:delta[0],dy:delta[1],dz:delta[2]});}
form.addEventListener('submit',event=>{event.preventDefault();action(async()=>{await post('/api/config',config());notice('Configuración guardada');});});
for(const key of ['drones','control','hands'])field(key).addEventListener('change',routes);
$('connect').onclick=()=>action(async()=>{if(!form.reportValidity())return;await post('/api/config',config());await post('/api/connect');});
$('finish').onclick=()=>action(()=>post('/api/finish'));
$('takeoff').onclick=()=>action(()=>command('takeoff'));$('land').onclick=()=>action(()=>command('land'));
$('emergency').onclick=()=>post('/api/emergency').catch(e=>notice(e.message,true));
$('command-target').onchange=()=>{if(current)render(current);};
for(const b of document.querySelectorAll('[data-direction]'))b.onclick=()=>action(()=>command('move',directions[b.dataset.direction]));
for(const [id,path] of [['input-start','start'],['input-stop','stop'],['input-zero','zero']])$(id).onclick=()=>action(()=>post('/api/input/'+path));
$('export').onclick=()=>action(()=>post('/api/export',{graphs:graphs()}));
$('demo-send').onclick=()=>action(()=>{if(current.config.control==='hands'){const hands={};if(!$('demo-left').disabled)hands.Left=$('demo-left').value;if(!$('demo-right').disabled)hands.Right=$('demo-right').value;return post('/api/input/demo',{hands});}const speed=a=>Math.sign(a)*.12*Math.max(0,Math.min(1,(Math.abs(a)-12)/16));return post('/api/input/demo',{vx:speed(Number($('demo-pitch').value)),vy:speed(Number($('demo-roll').value)),dz:Number($('demo-z').value)});});
for(const id of ['demo-left','demo-right'])for(const [value,text] of Object.entries(gestures)){const o=document.createElement('option');o.value=value;o.textContent=text;$(id).append(o);}
function view(camera){$('plot-view').hidden=camera;$('camera-view').hidden=!camera;for(const [id,selected] of [['view-chart',!camera],['view-camera',camera]]){$(id).classList.toggle('selected',selected);$(id).setAttribute('aria-pressed',String(selected));}if(!camera)drawTrajectory();}
$('view-chart').onclick=()=>view(false);$('view-camera').onclick=()=>view(true);
window.addEventListener('resize',drawTrajectory);
window.addEventListener('keydown',event=>{if(event.key==='Escape'&&token){event.preventDefault();$('emergency').click();}});
makeCards();routes();
async function refresh(){try{const response=await fetch('/api/status');if(!response.ok)throw new Error('El servidor no responde');const data=await response.json();render(data);if(token)await fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':token},body:'{}'});}catch(e){notice('Se perdió la conexión con el panel. '+e.message,true);$('connection-state').textContent='Panel sin conexión';document.querySelectorAll('[data-direction],#takeoff,#land,#connect').forEach(b=>b.disabled=true);}finally{setTimeout(refresh,750);}}
refresh();

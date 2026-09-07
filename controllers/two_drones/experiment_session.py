"""Sesion de experimento headless: coordina backend, entradas y resultados."""
from argparse import Namespace
from collections import deque
from pathlib import Path
import threading
import time
import sys

from cruz_highlevel_backend import (SimulatedBackend,HardwareBackend,DEFAULT_URI_1,DEFAULT_URI_2,DEFAULT_TOPIC_1,DEFAULT_TOPIC_2)
from cruz_highlevel_protocol import Command,decode_command
from session_config import SessionConfig,GRAPH_TYPES
from session_recording import SessionRecording
from hand_commands import gesture_command,GESTURES,FOLLOW_START,FOLLOW_STOP
from camera_marker_runtime import HighlevelCameraMarkerRuntime

ROOT=Path(__file__).resolve().parents[2]

class ExperimentSession:
    def __init__(self,*,allow_hardware=False,results_root=None):
        self.allow_hardware=allow_hardware; self.results_root=Path(results_root or ROOT/'results')
        self.config=SessionConfig(); self.backend=SimulatedBackend(); self.recording=None
        self.lock=threading.RLock(); self.operation=threading.Lock(); self.export_lock=threading.Lock()
        self.busy=False; self.exporting=False; self.message='Configura la sesion y ejecuta preflight'; self.error=''
        self.events=deque(maxlen=40); self.history=deque(maxlen=300); self.artifacts=[]
        self.source=None; self.marker_runtime=None; self.input_active=False; self.input_status='Control manual'; self.jpeg=None
        self.input_generation=0; self.last_input=time.monotonic(); self.last_heartbeat=time.monotonic()
        self.cooldowns={}; self.joystick_base={}; self.marker_calibrated=False; self.lost_since=None; self.emergency_requested=False
        self.stop_event=threading.Event()
        self.monitor=threading.Thread(target=self._monitor,name='ExperimentMonitor',daemon=True); self.monitor.start()

    def note(self,message,*,error=False):
        with self.lock:
            self.message=message
            if error: self.error=message
            self.events.append({'time':time.strftime('%H:%M:%S'),'message':message,'error':error})

    def configure(self,payload):
        c=SessionConfig.parse(payload,allow_hardware=self.allow_hardware)
        if not self.operation.acquire(blocking=False): raise ValueError('Espera a que termine la operacion actual')
        try:
            if self.backend.snapshot()['connected'] or self.busy: raise ValueError('Finaliza la sesion antes de cambiar su configuracion')
            self.stop_input()
            if self.recording:
                self.recording.close(); self.collect_artifacts(); self.recording=None
            self.config=c; self.backend=SimulatedBackend(None if c.drones=='both' else c.drones)
            self.history.clear(); self.error=''; self.note('Configuracion guardada; lista para preflight')
        finally: self.operation.release()

    def heartbeat(self): self.last_heartbeat=time.monotonic()

    def background(self,task):
        if not self.operation.acquire(blocking=False): raise ValueError('Hay otra operacion en curso')
        self.busy=True
        def run():
            try: task()
            except Exception as exc: self.note(str(exc),error=True)
            finally: self.busy=False; self.operation.release()
        threading.Thread(target=run,name='ExperimentOperation',daemon=True).start()

    def connect(self):
        def task():
            if self.backend.snapshot()['connected']: return
            self.emergency_requested=False; self.error=''; self.stop_input()
            if self.recording: self.recording.close()
            c=self.config
            self.backend=SimulatedBackend(None if c.drones=='both' else c.drones) if c.dry_run else HardwareBackend(Namespace(single=None if c.drones=='both' else c.drones,uri1=DEFAULT_URI_1,uri2=DEFAULT_URI_2,topic1=DEFAULT_TOPIC_1,topic2=DEFAULT_TOPIC_2))
            self.recording=SessionRecording(self.results_root,c)
            self.history.clear(); self.cooldowns.clear(); self.heartbeat()
            try:
                self.backend.connect(lambda ok,event,message,snapshot:self.note(message,error=not ok))
                if self.emergency_requested:
                    self.backend.close(); raise RuntimeError('Preflight cancelado por emergencia')
                self.note('Preflight correcto. Listo para controlar '+('ambos drones' if c.drones=='both' else c.drones))
                self.recording.sample(self.backend.snapshot())
            except Exception:
                self.backend.close(); self.recording.close(); self.collect_artifacts(); raise
        self.background(task)

    def execute(self,command,*,source='web'):
        target=self.config.validate_target(command.target)
        command=Command(command.action,target,command.dx,command.dy,command.dz)
        if command.action=='emergency': return self.emergency('Paro desde '+source)
        if not self.operation.acquire(blocking=False): raise ValueError('Operacion en curso; orden descartada')
        started=time.monotonic(); ok=False; message=''
        try:
            snapshot=self.backend.snapshot()
            if not snapshot['ready'] or self.emergency_requested: raise ValueError('Ejecuta preflight antes de dar ordenes')
            keys=self.backend.active_keys if target=='both' else (target,)
            if any('LANDING' in snapshot[k].get('mode','') or 'Aterrizando' in snapshot[k].get('status','') for k in keys):
                raise ValueError('Espera a que termine el aterrizaje')
            getattr(self.backend,command.action)(command)
            ok=True; message=f'{command.action.upper()} · {target}'; self.note(message)
            if command.action=='land': self.joystick_base.clear()
        except Exception as exc:
            message=str(exc); raise
        finally:
            self.operation.release()
            if self.recording: self.recording.add(kind='command',drone=target,action=command.action,source=source,ok=ok,message=message,processing_ms=(time.monotonic()-started)*1000)

    def emergency(self,reason='Paro de emergencia'):
        self.emergency_requested=True
        # El corte no espera a que termine preflight, exportacion u otra orden.
        self.input_active=False; self.input_generation+=1
        if self.marker_runtime: self.marker_runtime.cancel()
        self.backend.emergency(reason)
        self.note(reason,error=True)
        if self.recording: self.recording.add(kind='command',action='emergency',source='web',ok=True,message=reason)

    def finish(self):
        def task():
            self.stop_input(); self.backend.close()
            # El simulador no ejecuta un aterrizaje en close().
            if self.config.dry_run: self.backend.land(Command('land',self.config.drones))
            if self.recording:
                self.recording.sample(self.backend.snapshot()); self.recording.close(); self.collect_artifacts()
                if self.config.auto_graphs and self.config.graphs: self.export(self.config.graphs)
            self.note('Sesion finalizada. Resultados disponibles para descargar')
        self.background(task)

    def collect_artifacts(self):
        if self.recording:
            with self.recording.lock: paths=list(self.recording.artifacts)
            for path in paths:
                if path not in self.artifacts: self.artifacts.append(path)

    def export(self,selected):
        if not isinstance(selected,list) or not selected or any(g not in GRAPH_TYPES for g in selected): raise ValueError('Selecciona graficas validas')
        if not self.recording: raise ValueError('Inicia una sesion para guardar resultados')
        if not self.export_lock.acquire(blocking=False): raise ValueError('Ya se estan generando graficas')
        recording=self.recording; self.exporting=True
        def run():
            try:
                paths=recording.export(list(dict.fromkeys(selected)))
                with self.lock:
                    for path in paths:
                        if path not in self.artifacts: self.artifacts.append(path)
                self.note('Graficas PNG y PDF guardadas')
            except Exception as exc: self.note('No se pudieron guardar las graficas: '+str(exc),error=True)
            finally: self.exporting=False; self.export_lock.release()
        threading.Thread(target=run,name='ExperimentExport',daemon=True).start()

    def start_input(self):
        if self.busy or self.emergency_requested or not self.backend.snapshot()['ready']: raise ValueError('Completa preflight antes de activar la entrada')
        if self.config.control=='buttons': raise ValueError('La sesion usa botones')
        self.stop_input(); self.input_active=True; self.last_input=time.monotonic(); generation=self.input_generation
        self.input_status='Entrada simulada lista' if self.config.dry_run else 'Iniciando entrada'
        if self.config.dry_run: return
        if self.config.control=='hands':
            from session_hands import HandsSource
            self.marker_runtime=HighlevelCameraMarkerRuntime(enabled=True)
            self.marker_runtime.start()
            self.source=HandsSource(self.config.camera_index,lambda hands,ms:self.handle_hands(hands,ms,generation),lambda data:self.set_frame(data,generation),lambda message:self.input_failed(message,generation))
        else:
            directory=ROOT/'controllers'/'joystick'
            if str(directory) not in sys.path: sys.path.insert(0,str(directory))
            from marker_input import MarkerInput
            self.source=MarkerInput(self.config.marker_id)
        self.source.start()

    def stop_input(self):
        self.input_active=False; self.input_generation+=1
        source,self.source=self.source,None
        if source: source.stop()
        marker_runtime,self.marker_runtime=self.marker_runtime,None
        if marker_runtime: marker_runtime.stop()
        self.jpeg=None; self.input_status='Entrada detenida'; self.joystick_base.clear(); self.marker_calibrated=False; self.lost_since=None

    def set_frame(self,data,generation):
        if generation==self.input_generation and self.input_active: self.jpeg=data

    def input_failed(self,message,generation):
        if generation!=self.input_generation: return
        self.input_active=False; self.note('Entrada detenida: '+message,error=True)
        try:
            if any(self.backend.snapshot()[k]['airborne'] for k in self.backend.active_keys): self.execute(Command('land',self.config.drones),source='proteccion de entrada')
        except Exception: self.emergency('Fallo de entrada y aterrizaje')

    def handle_hands(self,hands,processing_ms=0,generation=None):
        if not self.input_active or (generation is not None and generation!=self.input_generation): return
        if not isinstance(hands,dict) or any(h not in ('Left','Right') or g not in GESTURES for h,g in hands.items()): raise ValueError('Gestos no validos')
        self.last_input=time.monotonic(); self.input_status=' · '.join(f'{h}: {g}' for h,g in hands.items()) or 'Sin manos visibles'
        snapshot=self.backend.snapshot(); commands={}; conflicts=set()
        for hand,target in self.config.hand_routes().items():
            target=self.config.validate_target(target)
            gesture=hands.get(hand)
            if gesture==FOLLOW_START:
                try:
                    if self.config.dry_run:
                        self.input_status='Seguimiento del marker 65 disponible solamente en Robotat real'
                    elif self.marker_runtime:
                        self.input_status=self.marker_runtime.activate(target,snapshot)
                except Exception as exc: self.input_status=str(exc)
                continue
            if gesture==FOLLOW_STOP:
                if self.marker_runtime: self.input_status=self.marker_runtime.deactivate(target,snapshot)
                else: self.input_status='Seguimiento detenido (simulación)'
                continue
            if gesture!='STOP' and self.marker_runtime and self.marker_runtime.active_for(target,snapshot):
                continue
            cmd=gesture_command(gesture,target,snapshot)
            if cmd is None: continue
            if cmd.action=='emergency': self.emergency('Puno: emergencia'); return
            keys=self.backend.active_keys if cmd.target=='both' else (cmd.target,)
            for key in keys:
                individual=Command(cmd.action,key,cmd.dx,cmd.dy,cmd.dz)
                if key in commands and commands[key]!=individual: conflicts.add(key)
                commands[key]=individual
        if conflicts:
            self.input_status='Gestos en conflicto; mantén una sola orden por dron'; return
        # Un mismo gesto con ambas manos no duplica movimientos sobre el dron.
        for key,cmd in commands.items():
            now=time.monotonic()
            if now-self.cooldowns.get(key,0)<1.25: continue
            try:
                self.execute(cmd,source='manos'); self.cooldowns[key]=now
            except Exception as exc: self.input_status=str(exc)
        if self.recording and hands:
            self.recording.add(kind='input',source='manos',message=self.input_status,processing_ms=processing_ms)

    def calibrate_marker(self):
        if self.config.control!='joystick' or not self.input_active: raise ValueError('Activa el joystick primero')
        if self.config.dry_run:
            self.marker_calibrated=True; self.joystick_base.clear()
            self.input_status='Cero simulado establecido'; self.last_input=time.monotonic(); return
        self.source.calibrate(); self.marker_calibrated=True; self.joystick_base.clear(); self.note('Cero del marker establecido')

    def marker_step(self,data):
        if not self.input_active: return
        self.input_status=data.get('message','Joystick activo')
        if not data.get('fresh'):
            if self.lost_since is None: self.lost_since=time.monotonic()
            if time.monotonic()-self.lost_since>1: self.input_failed('Marker perdido',self.input_generation)
            return
        self.lost_since=None
        if not data.get('calibrated'): return
        self.last_input=time.monotonic()
        target=self.config.validate_target(self.config.joystick_target); snapshot=self.backend.snapshot()
        keys=self.backend.active_keys if target=='both' else (target,)
        if not all(snapshot[k]['airborne'] for k in keys): return
        if data.get('land'):
            self.execute(Command('land',target),source='joystick'); return
        first=keys[0]; current=snapshot[first]['target'][2]
        if first not in self.joystick_base: self.joystick_base[first]=current
        dx=max(-.03,min(.03,float(data.get('vx',0))*.25)); dy=max(-.03,min(.03,float(data.get('vy',0))*.25))
        dz=max(-.08,min(.08,self.joystick_base[first]+float(data.get('dz',0))-current))
        if any(abs(v)>.001 for v in (dx,dy,dz)): self.execute(Command('move',target,dx,dy,dz),source='joystick')

    def demo_input(self,data):
        if not self.config.dry_run: raise ValueError('Las entradas de ensayo solo existen en simulacion')
        if not self.input_active: raise ValueError('Activa la entrada de ensayo')
        if self.config.control=='hands': self.handle_hands(data.get('hands',{}))
        elif self.config.control=='joystick':
            if not self.marker_calibrated: raise ValueError('Establece cero del marker antes de enviar movimientos')
            values={k:float(data.get(k,0)) for k in ('vx','vy','dz')}
            import math
            if any(not math.isfinite(v) for v in values.values()): raise ValueError('Valores no finitos')
            self.marker_step(dict(values,fresh=True,calibrated=True,message='Orden de marker simulada'))
        else: raise ValueError('La sesion utiliza botones')

    def status(self):
        snapshot=self.backend.snapshot(); self.collect_artifacts()
        if not snapshot['connected']:
            # No presentar posiciones del simulador como telemetria real antes del preflight.
            for key in ('drone1','drone2'):
                for field in ('pose','target','origin','battery_v','mocap_age_s','ekf_age_s','ekf_mocap_error_m'):
                    snapshot[key][field]=None
        with self.lock:
            following=[] if self.marker_runtime is None else list(self.marker_runtime.active_keys)
            return {'snapshot':snapshot,'config':self.config.to_dict(),'allow_hardware':self.allow_hardware,'busy':self.busy,'exporting':self.exporting,'message':self.message,'error':self.error,'input':{'active':self.input_active,'message':self.input_status,'camera':self.jpeg is not None,'following':following},'events':list(self.events),'history':list(self.history),'artifacts':[{'id':str(i),'name':p.name,'path':str(p.relative_to(self.results_root))} for i,p in enumerate(self.artifacts)],'session_id':None if not self.recording else self.recording.id}

    def artifact(self,identifier):
        try:
            index=int(identifier)
            if index<0: raise ValueError('Indice no valido')
            path=self.artifacts[index].resolve()
        except (ValueError,IndexError): raise ValueError('Archivo no encontrado')
        if not path.is_relative_to(self.results_root.resolve()) or not path.is_file(): raise ValueError('Archivo no disponible')
        return path

    def _monitor(self):
        while not self.stop_event.wait(.25):
            try:
                snapshot=self.backend.snapshot()
                if snapshot['connected']:
                    if self.recording: self.recording.sample(snapshot)
                    with self.lock:
                        self.history.append({'t':time.time(),**{k:{f:snapshot[k].get(f) for f in ('enabled','pose','target','battery_v','ekf_mocap_error_m','mocap_age_s')} for k in ('drone1','drone2')}})
                    airborne=any(snapshot[k]['airborne'] for k in self.backend.active_keys)
                    if airborne and time.monotonic()-self.last_heartbeat>5 and not self.busy:
                        self.stop_input(); self.execute(Command('land',self.config.drones),source='panel sin respuesta'); self.heartbeat()
                    if self.input_active and not self.config.dry_run:
                        if self.config.control=='joystick' and self.source: self.marker_step(self.source.read())
                        elif self.config.control=='hands':
                            if self.marker_runtime and self.marker_runtime.active_keys:
                                try:
                                    details=self.marker_runtime.update(self.backend)
                                    if details: self.input_status=' | '.join(details)
                                except Exception as exc: self.input_status=str(exc); self.note(str(exc),error=True)
                            if airborne and time.monotonic()-self.last_input>2:
                                self.input_failed('La camara dejo de responder',self.input_generation)
            except Exception as exc:
                if str(exc)!=self.error: self.note(str(exc),error=True)

    def close(self):
        self.stop_event.set(); self.stop_input()
        with self.operation:
            self.backend.close()
            if self.recording: self.recording.close()
        self.monitor.join(timeout=2)

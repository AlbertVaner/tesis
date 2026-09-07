"""Registro y graficas de sesiones; mide tiempos del software, no de la radio."""
import csv
import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

FIELDS = ('t_s','kind','drone','action','source','ok','message','x','y','z','target_x','target_y','target_z','ekf_error_m','battery_v','mocap_age_ms','ekf_age_ms','source_latency_ms','processing_ms')

class SessionRecording:
    def __init__(self, root, config):
        self.root=Path(root)
        self.config=config
        now=datetime.now()
        self.id=now.strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:6]
        self.day=now.strftime('%Y-%m-%d')
        self.start=time.monotonic()
        self.rows=[]
        self.lock=threading.RLock()
        self.file=None
        self.artifacts=[]
        folder=self.root/'data'/'panel_web'/self.day/self.id
        folder.mkdir(parents=True,exist_ok=True)
        meta=folder/'sesion.json'
        meta.write_text(json.dumps(config.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
        self.artifacts.append(meta)
        if config.save_csv:
            path=folder/'telemetria.csv'
            self.file=path.open('w',newline='',encoding='utf-8')
            self.writer=csv.DictWriter(self.file,fieldnames=FIELDS)
            self.writer.writeheader()
            self.artifacts.append(path)

    def add(self,**values):
        row={k:'' for k in FIELDS}
        row.update(t_s=round(time.monotonic()-self.start,4),**values)
        with self.lock:
            self.rows.append(row)
            if self.file:
                self.writer.writerow(row)
                self.file.flush()

    def sample(self,snapshot):
        for key in ('drone1','drone2'):
            u=snapshot[key]
            if not u.get('enabled'): continue
            pose=u.get('pose') or [None]*3
            target=u.get('target') or [None]*3
            ms=lambda value: None if value is None else value*1000
            self.add(kind='sample',drone=key,x=pose[0],y=pose[1],z=pose[2],target_x=target[0],target_y=target[1],target_z=target[2],ekf_error_m=u.get('ekf_mocap_error_m'),battery_v=u.get('battery_v'),mocap_age_ms=ms(u.get('mocap_age_s')),ekf_age_ms=ms(u.get('ekf_age_s')),source_latency_ms=ms(u.get('mqtt_source_latency_s')))

    def close(self):
        with self.lock:
            if self.file:
                self.file.close()
                self.file=None

    def export(self, selected):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        with self.lock: rows=list(self.rows)
        if not any(r['kind']=='sample' for r in rows):
            raise ValueError('Todavia no hay telemetria para graficar')
        out=self.root/'graphs'/'panel_web'/self.day/self.id/datetime.now().strftime('%H%M%S_%f')
        out.mkdir(parents=True,exist_ok=True)
        titles={'position':'Posicion y objetivo Z','trajectory':'Trayectoria XY','latency':'Tiempos del software y antiguedad MoCap','ekf':'Diferencia EKF / MoCap','battery':'Voltaje de bateria'}
        for kind in selected:
            fig=Figure(figsize=(9,5),layout='constrained'); FigureCanvasAgg(fig)
            ax=fig.subplots()
            for key,color in (('drone1','#25804b'),('drone2','#367dc4')):
                sample=[r for r in rows if r['kind']=='sample' and r['drone']==key]
                series={'position':(('x','X'),('y','Y'),('z','Z'),('target_z','Objetivo Z')),'trajectory':(('y','XY'),),'latency':(('mocap_age_ms','Edad MoCap'),('ekf_age_ms','Edad EKF'),('source_latency_ms','Tiempo fuente MQTT')),'ekf':(('ekf_error_m','Error'),),'battery':(('battery_v','Bateria'),)}[kind]
                for i,(field,label) in enumerate(series):
                    valid=[r for r in sample if isinstance(r.get(field),(int,float)) and math.isfinite(r[field]) and (kind!='trajectory' or isinstance(r.get('x'),(int,float)))]
                    if valid: ax.plot([r['x' if kind=='trajectory' else 't_s'] for r in valid],[r[field] for r in valid],label=f'{key} · {label}',color=color,linestyle=('-','--',':','-.')[i%4])
            if kind=='latency':
                commands=[r for r in rows if r['kind']=='command' and isinstance(r.get('processing_ms'),(int,float))]
                if commands: ax.scatter([r['t_s'] for r in commands],[r['processing_ms'] for r in commands],label='Procesamiento de orden',s=12,color='#a25120')
                inputs=[r for r in rows if r['kind']=='input' and isinstance(r.get('processing_ms'),(int,float))]
                if inputs: ax.scatter([r['t_s'] for r in inputs],[r['processing_ms'] for r in inputs],label='Procesamiento de entrada',s=8,color='#72599a',alpha=.5)
            ax.set_title(titles[kind]+(' · SIMULACION' if self.config.dry_run else ''))
            ax.set_xlabel('X (m)' if kind=='trajectory' else 'Tiempo de sesion (s)')
            ax.set_ylabel('V' if kind=='battery' else 'ms' if kind=='latency' else 'Y (m)' if kind=='trajectory' else 'm')
            ax.grid(alpha=.2)
            if ax.has_data(): ax.legend(fontsize=8)
            else: ax.text(.5,.5,'Sin mediciones disponibles',transform=ax.transAxes,ha='center')
            if kind=='trajectory': ax.set_aspect('equal',adjustable='datalim')
            for ext in ('png','pdf'):
                path=out/f'{kind}.{ext}'; fig.savefig(path,dpi=150)
                with self.lock: self.artifacts.append(path)
            fig.clear()
        return list(self.artifacts)

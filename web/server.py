"""Panel HTTP de experimentos. La logica de vuelo pertenece a controllers/."""
from __future__ import annotations
import argparse
import ipaddress
import json
import math
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
CONTROLLERS=ROOT/'controllers'/'two_drones'
if str(CONTROLLERS) not in sys.path: sys.path.insert(0,str(CONTROLLERS))
from experiment_session import ExperimentSession
from cruz_highlevel_protocol import Command,decode_command

STATIC_DIR=Path(__file__).resolve().parent/'static'


def finite_json(value):
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,dict): return {k:finite_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [finite_json(v) for v in value]
    return value

class PanelServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,session):
        self.session=session; self.control_token=secrets.token_urlsafe(32)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def valid_host(self):
        host=self.headers.get('Host','')
        name=urlparse('//'+host).hostname
        if name=='localhost': return True
        try: return ipaddress.ip_address(name).is_private or ipaddress.ip_address(name).is_loopback
        except ValueError: return False
    def headers_for(self,status,kind,size=None):
        self.send_response(status); self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if size is not None: self.send_header('Content-Length',str(size))
    def send_json(self,payload,status=200):
        data=json.dumps(finite_json(payload),ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.headers_for(status,'application/json; charset=utf-8',len(data)); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if not self.valid_host(): return self.send_json({'error':'Host no permitido'},403)
        path=urlparse(self.path).path
        if path=='/api/status':
            return self.send_json({**self.server.session.status(),'control_token':self.server.control_token})
        if path=='/api/camera/stream':
            session=self.server.session
            if not session.input_active or session.config.dry_run or session.config.control!='hands': return self.send_json({'error':'Camara inactiva'},409)
            self.headers_for(200,'multipart/x-mixed-replace; boundary=frame'); self.end_headers()
            try:
                while session.input_active and not session.stop_event.is_set():
                    data=session.jpeg
                    if data:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n'+f'Content-Length: {len(data)}\r\n\r\n'.encode()+data+b'\r\n'); self.wfile.flush()
                    time.sleep(.08)
            except (BrokenPipeError,ConnectionResetError): pass
            return
        if path.startswith('/api/files/'):
            try: target=self.server.session.artifact(path.rsplit('/',1)[-1])
            except ValueError as exc: return self.send_json({'error':str(exc)},404)
            data=target.read_bytes(); self.headers_for(200,mimetypes.guess_type(target.name)[0] or 'application/octet-stream',len(data))
            self.send_header('Content-Disposition',f'attachment; filename="{target.name}"'); self.end_headers(); self.wfile.write(data); return
        target=(STATIC_DIR/('index.html' if path=='/' else path.lstrip('/'))).resolve()
        if not target.is_relative_to(STATIC_DIR.resolve()) or not target.is_file(): return self.send_json({'error':'No encontrado'},404)
        data=target.read_bytes(); self.headers_for(200,(mimetypes.guess_type(target.name)[0] or 'application/octet-stream')+'; charset=utf-8',len(data)); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        # Consumir cuerpos pequenos antes de responder evita resets TCP en Windows.
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=16384: raise ValueError('Solicitud demasiado grande')
            self.connection.settimeout(3)
            body=self.rfile.read(size)
        except (ValueError, OSError) as exc:
            return self.send_json({'error':str(exc)},400)
        if not self.valid_host(): return self.send_json({'error':'Host no permitido'},403)
        origin=self.headers.get('Origin')
        if (origin and origin!='http://'+self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site')=='cross-site':
            return self.send_json({'error':'Origen no permitido'},403)
        if not secrets.compare_digest(self.headers.get('X-Control-Token',''),self.server.control_token): return self.send_json({'error':'Actualiza el panel antes de enviar ordenes'},403)
        if self.headers.get_content_type()!='application/json': return self.send_json({'error':'Se requiere JSON'},415)
        try:
            data=json.loads(body or b'{}')
            if not isinstance(data,dict): raise ValueError('Se requiere un objeto JSON')
            session=self.server.session; path=urlparse(self.path).path
            if path=='/api/config': session.configure(data)
            elif path=='/api/connect': session.connect()
            elif path in ('/api/finish','/api/disconnect'): session.finish()
            elif path=='/api/emergency': session.emergency()
            elif path=='/api/command':
                command=decode_command(json.dumps(data))
                if command.action not in ('takeoff','move','land','emergency'): raise ValueError('Orden no disponible')
                session.execute(command)
            elif path in ('/api/input/start','/api/camera/start'): session.start_input()
            elif path in ('/api/input/stop','/api/camera/stop'): session.stop_input()
            elif path=='/api/input/zero': session.calibrate_marker()
            elif path=='/api/input/demo': session.demo_input(data)
            elif path=='/api/export': session.export(data.get('graphs',session.config.graphs))
            elif path=='/api/heartbeat':
                session.heartbeat(); return self.send_json({'ok':True})
            else: return self.send_json({'error':'Ruta no encontrada'},404)
            return self.send_json(session.status())
        except (ValueError,RuntimeError,TypeError,KeyError) as exc: return self.send_json({'error':str(exc)},400)
        except Exception as exc: return self.send_json({'error':str(exc)},500)


def main():
    parser=argparse.ArgumentParser(description='Panel web Robotat para uno o dos Crazyflies')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true',help='solo simulacion (predeterminado)')
    mode.add_argument('--hardware',action='store_true',help='permite seleccionar modo real; el preflight se inicia desde la web')
    parser.add_argument('--host',choices=('127.0.0.1','0.0.0.0'),default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    session=ExperimentSession(allow_hardware=args.hardware)
    server=PanelServer((args.host,args.port),session)
    print(f'UVG Drone Lab: http://127.0.0.1:{server.server_port}',flush=True)
    print('Modo real habilitado para seleccion desde el panel.' if args.hardware else 'SIMULACION: no se abrira radio, MQTT ni camara.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nCerrando panel...',flush=True)
    finally: server.server_close(); session.close()
    return 0

if __name__=='__main__': raise SystemExit(main())

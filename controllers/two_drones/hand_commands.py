"""Conversion de gestos filtrados a comandos high-level, sin camara."""
from cruz_highlevel_protocol import Command

MOVEMENTS={'DERECHA':(0,-.10,0),'IZQUIERDA':(0,.10,0),'ARRIBA':(0,0,.08),'ABAJO':(0,0,-.08),'ADELANTE':(.10,0,0),'ATRAS':(-.10,0,0)}
FOLLOW_START='SEGUIR_MARKER'
FOLLOW_STOP='DETENER_SEGUIMIENTO'
GESTURES=(*MOVEMENTS,'DESPEGAR','ATERRIZAR','STOP',FOLLOW_START,FOLLOW_STOP,'REPOSO','SIN_DETECCION')

def gesture_command(gesture,target,snapshot):
    keys=tuple(k for k in ('drone1','drone2') if snapshot[k].get('enabled',True)) if target=='both' else (target,)
    states=[bool(snapshot[k].get('airborne')) for k in keys]
    if gesture=='STOP': return Command('emergency') if any(states) else None
    if gesture=='DESPEGAR': return Command('takeoff',target) if not any(states) else None
    if gesture=='ATERRIZAR': return Command('land',target) if any(states) else None
    if gesture in MOVEMENTS and all(states): return Command('move',target,*MOVEMENTS[gesture])
    return None

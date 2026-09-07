"""Adaptador headless del marker joystick; no abre radios ni controla drones."""
import time
from marker_mocap import MocapReceiver
from control_with_marker import (angle_delta_deg,tilt_to_speed,PITCH_TO_X_SIGN,ROLL_TO_Y_SIGN,VERTICAL_DEADZONE_M,LAND_MARKER_BELOW_M,LAND_HOLD_S,MOCAP_TIMEOUT_S)

class MarkerInput:
    def __init__(self,marker_id):
        self.receiver=MocapReceiver('mocap/all',required_identifier=marker_id)
        self.zero=None; self.below_since=None
    def start(self): self.receiver.start()
    def stop(self): self.receiver.stop()
    def calibrate(self):
        pose=self.receiver.snapshot()
        if pose is None or pose.age_s>MOCAP_TIMEOUT_S: raise ValueError('No hay una pose reciente del marker seleccionado')
        self.zero=pose; self.below_since=None
    def read(self):
        pose=self.receiver.snapshot()
        if pose is None or pose.age_s>MOCAP_TIMEOUT_S:
            return {'fresh':False,'calibrated':self.zero is not None,'message':self.receiver.error or 'Esperando marker'}
        if self.zero is None: return {'fresh':True,'calibrated':False,'message':'Coloca el marker a nivel y establece cero'}
        roll=angle_delta_deg(pose.roll_deg,self.zero.roll_deg); pitch=angle_delta_deg(pose.pitch_deg,self.zero.pitch_deg); dz=pose.z-self.zero.z
        if dz<LAND_MARKER_BELOW_M:
            if self.below_since is None: self.below_since=time.monotonic()
        else: self.below_since=None
        return {'fresh':True,'calibrated':True,'roll':roll,'pitch':pitch,'dz':0 if abs(dz)<=VERTICAL_DEADZONE_M else dz,'vx':PITCH_TO_X_SIGN*tilt_to_speed(pitch),'vy':ROLL_TO_Y_SIGN*tilt_to_speed(roll),'land':self.below_since is not None and time.monotonic()-self.below_since>=LAND_HOLD_S,'message':'Marker activo'}

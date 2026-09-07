"""Adaptación high-level del seguimiento, sin radio ni MQTT."""
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_marker_runtime import HighlevelCameraMarkerRuntime
from cruz_highlevel_backend import BridgeError, SimulatedBackend
from cruz_highlevel_protocol import Command


class Follower:
    def __init__(self): self.offsets={}; self.started=self.stopped=False
    @property
    def active_keys(self): return tuple(self.offsets)
    def start(self): self.started=True
    def stop(self): self.stopped=True
    def activate(self,keys,positions): self.offsets.update({k:positions[k] for k in keys})
    def deactivate(self,keys=None):
        for key in tuple(self.offsets) if keys is None else keys: self.offsets.pop(key,None)
    def highlevel_delta(self,key,target): return (.02,-.01,0)


class Backend:
    def __init__(self): self.commands=[]
    def snapshot(self):
        return {'drone1':{'enabled':True,'airborne':True,'pose':[0,0,.4],'target':[0,0,.4]},
                'drone2':{'enabled':True,'airborne':True,'pose':[0,.9,.4],'target':[0,.9,.4]}}
    def move(self,command): self.commands.append(command)
    def follow_move(self,command): self.commands.append(command)


class RuntimeTests(unittest.TestCase):
    def test_follow_safety_sphere_blocks_targets_closer_than_point_three(self):
        backend = SimulatedBackend()
        backend.ready = True
        backend.units['drone1'].update(airborne=True, target=[0, 0, .4], pose=[0, 0, .4])
        backend.units['drone2'].update(airborne=True, target=[0, .4, .4], pose=[0, .4, .4])
        with self.assertRaisesRegex(BridgeError, 'esfera de seguridad'):
            backend.follow_move(Command('follow_move', 'drone1', 0, .15, 0))

    def test_activation_update_and_rock_stop_are_per_target(self):
        follower=Follower(); runtime=HighlevelCameraMarkerRuntime(enabled=False,follower=follower)
        backend=Backend(); snapshot=backend.snapshot()
        runtime.start(); runtime.activate('drone1',snapshot); runtime.update(backend)
        self.assertEqual([c.target for c in backend.commands],['drone1'])
        self.assertEqual(backend.commands[0].action, 'follow_move')
        self.assertTrue(runtime.active_for('drone1',snapshot))
        runtime.deactivate('drone1',snapshot); runtime.stop()
        self.assertFalse(runtime.active_keys)
        self.assertTrue(follower.started and follower.stopped)

    def test_both_requires_every_drone_airborne(self):
        runtime=HighlevelCameraMarkerRuntime(enabled=False,follower=Follower())
        snapshot=Backend().snapshot(); snapshot['drone2']['airborne']=False
        with self.assertRaisesRegex(Exception,'Despega'):
            runtime.activate('both',snapshot)

    def test_both_moves_as_one_command_to_preserve_formation(self):
        follower=Follower(); runtime=HighlevelCameraMarkerRuntime(enabled=False,follower=follower)
        backend=Backend(); runtime.activate('both',backend.snapshot()); runtime.update(backend)
        self.assertEqual([command.target for command in backend.commands],['both'])


if __name__=='__main__': unittest.main()

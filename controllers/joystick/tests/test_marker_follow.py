"""Seguimiento relativo del marker, sin MQTT ni drones."""
from pathlib import Path
import math
import sys
import time
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marker_follow import (
    CameraMarkerFollower,
    FollowUnavailable,
    world_to_body,
)
from marker_mocap import Pose


class Receiver:
    instances = {}

    def __init__(self, topic, **kwargs):
        self.topic = topic
        self.kwargs = kwargs
        self.pose = None
        self.error = ""
        self.started = self.stopped = False
        self.instances[topic] = self

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def snapshot(self): return self.pose


def pose(x=0, y=0, z=1, yaw=0, age=0):
    return Pose(x, y, z, 0, 0, yaw, time.monotonic() - age)


class MarkerFollowTests(unittest.TestCase):
    def setUp(self):
        Receiver.instances = {}
        self.follow = CameraMarkerFollower(
            drone_topics={'drone1':'drone'}, receiver_factory=Receiver)
        self.marker = Receiver.instances['mocap/all']
        self.drone = Receiver.instances['drone']

    def test_start_stop_owns_all_receivers(self):
        self.follow.start()
        self.assertTrue(self.marker.started and self.drone.started)
        self.follow.stop()
        self.assertTrue(self.marker.stopped and self.drone.stopped)

    def test_default_follow_marker_is_65(self):
        self.assertEqual(self.marker.kwargs['required_identifier'], 65)

    def test_relative_xy_target_preserves_height(self):
        self.marker.pose = pose(1, 2, .8)
        self.drone.pose = pose(1.5, 2.2, .4)
        self.follow.activate(('drone1',))
        self.marker.pose = pose(1.2, 1.9, 1.3)
        desired = self.follow.desired('drone1')
        self.assertAlmostEqual(math.dist(desired, (1.2, 1.9, 1.3)), .45)
        delta = self.follow.highlevel_delta('drone1', (1.5,2.2,.4))
        self.assertEqual(delta, (.025, -.025, .025))

    def test_velocity_uses_robotat_yaw_and_deadzone(self):
        self.marker.pose = pose()
        self.drone.pose = pose(yaw=90)
        self.follow.activate(('drone1',))
        self.marker.pose = pose(x=.2)
        world = self.follow.world_velocity('drone1')
        self.assertAlmostEqual(world[0], .1)
        self.assertAlmostEqual(world[1], 0)
        self.assertAlmostEqual(world[2], .1)
        vx, vy, vz = self.follow.body_velocity('drone1')
        self.assertAlmostEqual(vx, 0, places=7)
        self.assertAlmostEqual(vy, -.1)
        self.assertAlmostEqual(vz, .1)
        self.marker.pose = pose(x=.02)
        self.drone.pose = pose(z=1.2,yaw=90)
        self.assertEqual(self.follow.body_velocity('drone1'), (0,0,.1))

    def test_stale_marker_stops_but_large_travel_is_allowed(self):
        self.marker.pose = pose()
        self.drone.pose = pose()
        self.follow.activate(('drone1',))
        self.marker.pose = pose(age=2)
        with self.assertRaises(FollowUnavailable): self.follow.desired('drone1')
        self.assertFalse(self.follow.active_keys)
        self.marker.pose = pose(); self.follow.activate(('drone1',))
        self.marker.pose = pose(x=5,z=3)
        desired = self.follow.desired('drone1')
        self.assertAlmostEqual(math.dist(desired, (5,0,3)), .45)

    def test_activation_is_atomic_for_two_drones(self):
        follow = CameraMarkerFollower(
            drone_topics={'drone1':'d1','drone2':'d2'}, receiver_factory=Receiver)
        Receiver.instances['mocap/all'].pose = pose()
        Receiver.instances['d1'].pose = pose()
        Receiver.instances['d2'].pose = None
        with self.assertRaises(FollowUnavailable): follow.activate(('drone1','drone2'))
        self.assertFalse(follow.active_keys)

    def test_world_to_body(self):
        self.assertAlmostEqual(world_to_body(1, 0, 90)[1], -1)


if __name__ == '__main__':
    unittest.main()

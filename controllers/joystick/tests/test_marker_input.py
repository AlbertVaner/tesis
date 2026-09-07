"""Traduccion de marker con receptor falso: sin conexion MQTT ni radio."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marker_input import MarkerInput
from marker_mocap import MOCAP_TIMEOUT_S, MocapReceiver, Pose


class MarkerInputTests(unittest.TestCase):
    def setUp(self):
        self.factory = patch('marker_input.MocapReceiver')
        self.receiver_type = self.factory.start()
        self.receiver = self.receiver_type.return_value
        self.receiver.error = ''
        # La frescura la decide el receptor real sobre el snapshot falso.
        self.receiver.fresh_pose.side_effect = (
            lambda timeout_s=MOCAP_TIMEOUT_S: MocapReceiver.fresh_pose(self.receiver, timeout_s)
        )
        self.source = MarkerInput(73)

    def tearDown(self):
        self.factory.stop()

    def pose(self, z=1, roll=0, pitch=0, age=0):
        return Pose(0, 0, z, roll, pitch, 0, time.monotonic()-age)

    def test_selected_id_is_passed_to_receiver(self):
        self.receiver_type.assert_called_once_with('mocap/all', required_identifier=73)
        self.source.start()
        self.source.stop()
        self.receiver.start.assert_called_once()
        self.receiver.stop.assert_called_once()

    def test_zero_requires_recent_marker(self):
        for pose in (None, self.pose(age=2)):
            self.receiver.snapshot.return_value = pose
            with self.assertRaises(ValueError):
                self.source.calibrate()
            self.assertFalse(self.source.read()['fresh'])

    def test_deadzone_and_direction_follow_existing_controller(self):
        self.receiver.snapshot.return_value = self.pose()
        self.assertFalse(self.source.read()['calibrated'])
        self.source.calibrate()
        self.receiver.snapshot.return_value = self.pose(z=1.04, roll=8, pitch=-8)
        sample = self.source.read()
        self.assertEqual((sample['vx'],sample['vy'],sample['dz']), (0,0,0))
        self.receiver.snapshot.return_value = self.pose(z=1.12, roll=-28, pitch=28)
        sample = self.source.read()
        self.assertAlmostEqual(sample['vx'], .12)
        self.assertAlmostEqual(sample['vy'], -.12)
        self.assertAlmostEqual(sample['dz'], .12)

    def test_lowering_marker_requires_sustained_hold_to_land(self):
        self.receiver.snapshot.return_value = self.pose()
        self.source.calibrate()
        self.receiver.snapshot.return_value = self.pose(z=.85)
        self.assertFalse(self.source.read()['land'])
        self.source.below_since = time.monotonic()-.6
        self.assertTrue(self.source.read()['land'])
        self.receiver.snapshot.return_value = self.pose()
        self.assertFalse(self.source.read()['land'])
        self.assertIsNone(self.source.below_since)


if __name__ == '__main__':
    unittest.main()

"""Diagnostico EKF/MoCap con datos sinteticos; no abre radios ni MQTT."""
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prueba_estabilidad_dos_drones_lowlevel as flight


class AlignmentDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.unit = flight.DroneUnit('Dron 2', 'radio://prueba', 'mocap/prueba')
        self.unit.cf = SimpleNamespace(
            extpos=Mock(),
            param=SimpleNamespace(values={'stabilizer': {'estimator': '2'}, 'kalman': {'resetEstimation': '0'}}),
        )

    def message(self):
        return SimpleNamespace(payload=json.dumps({'payload': {'pose': {'position': {'x': .148, 'y': .564, 'z': .031}}}}).encode())

    def test_timeout_reports_live_zero_estimate_and_preserves_block(self):
        self.unit.pose = flight.Pose(.148, .564, .031, 9.984)
        self.unit.estimate = flight.Pose(0, 0, 0, 9.968)
        with patch.object(flight.time, 'monotonic', return_value=10), \
             patch.object(flight, 'EKF_ALIGNMENT_TIMEOUT_S', 0):
            with self.assertRaises(RuntimeError) as raised:
                self.unit.wait_for_ekf_alignment()
        message = str(raised.exception)
        self.assertIn('(< 0.07 m)', message)
        self.assertIn('diferencia=0.584 m', message)
        self.assertIn('edad=0.032 s', message)
        self.assertIn('stabilizer.estimator=2', message)
        self.assertIn('kalman.resetEstimation=0', message)
        self.unit.cf.extpos.send_extpos.assert_not_called()

    def test_missing_data_diagnostic_does_not_require_link(self):
        self.unit.cf = None
        result = self.unit.ekf_alignment_diagnostic()
        self.assertIn('MoCap: sin datos', result)
        self.assertIn('EKF: sin datos', result)
        self.assertIn('estimator=desconocido', result)

    def test_extpos_failures_remain_visible_after_recovery(self):
        self.unit.cf.extpos.send_extpos.side_effect = [OSError('enlace cerrado'), None]
        with patch.object(flight.time, 'monotonic', return_value=10):
            self.unit._on_mocap(None, None, self.message())
        with patch.object(flight.time, 'monotonic', return_value=11):
            self.unit._on_mocap(None, None, self.message())
        self.assertEqual(self.unit.extpos_errors, 1)
        self.assertEqual(self.unit.extpos_submitted, 1)
        self.assertEqual(self.unit.mqtt_accepted_msgs, 2)
        self.assertIn('OSError: enlace cerrado', self.unit.ekf_alignment_diagnostic())
        self.assertIn('sin acuse del dron', self.unit.ekf_alignment_diagnostic())

    def test_extpos_rate_limit_is_unchanged(self):
        with patch.object(flight.time, 'monotonic', return_value=10):
            self.unit._on_mocap(None, None, self.message())
            self.unit._on_mocap(None, None, self.message())
        self.unit.cf.extpos.send_extpos.assert_called_once_with(.148, .564, .031)
        self.assertEqual(self.unit.extpos_submitted, 1)


if __name__ == '__main__':
    unittest.main()

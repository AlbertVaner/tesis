"""Seleccion Robotat/Flow Deck con firmware falso; sin MQTT, camara ni radio."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
for path in ('controllers/shared', 'controllers/two_drones', 'controllers/joystick', 'controllers/single_drone/flowdeck'):
    sys.path.insert(0, str(ROOT / path))

import flowdeck_feedback as selection
import prueba_estabilidad_dos_drones_lowlevel as low
import cruz_highlevel_backend as high
import control_with_marker as marker
import hover_flowdeck_dron1 as flow_hover


class FakeParam:
    def __init__(self, *, attached=True, patched=True):
        self.values = {
            'deck': {'bcFlow': '0', 'bcFlow2': str(int(attached)), 'bcZRanger': '0', 'bcZRanger2': str(int(attached))},
            'motion': {'disable': '0'},
            'kalman': {'resetEstimation': '0'},
        }
        if patched:
            self.values['range'] = {'disable': '0'}
        self.toc = SimpleNamespace(get_element_by_complete_name=self.element)
        self.callbacks = {}
        self.writes = []
        self.silent = set()
        self.rejected = set()

    def element(self, complete_name):
        group, name = complete_name.split('.')
        return object() if name in self.values.get(group, {}) else None

    def get_value(self, complete_name, timeout=None):
        group, name = complete_name.split('.')
        return self.values[group][name]

    def add_update_callback(self, *, group, name, cb):
        self.callbacks[group + '.' + name] = cb

    def remove_update_callback(self, *, group, name, cb):
        self.callbacks.pop(group + '.' + name)

    def set_value(self, complete_name, value):
        self.writes.append((complete_name, value))
        if complete_name in self.silent:
            return
        actual = '0' if complete_name in self.rejected else value
        group, name = complete_name.split('.')
        self.values.setdefault(group, {})[name] = actual
        if complete_name in self.callbacks:
            self.callbacks[complete_name](complete_name, actual)


def fake_cf(**options):
    return SimpleNamespace(param=FakeParam(**options))


class FeedbackTests(unittest.TestCase):
    def test_robotat_excludes_both_measurements_for_both_deck_versions(self):
        for version in ('bcFlow', 'bcFlow2'):
            with self.subTest(version=version):
                cf = fake_cf(attached=False)
                cf.param.values['deck'][version] = '1'
                selection.configure_flowdeck_feedback(cf, enabled=False)
                self.assertEqual(cf.param.writes, [('motion.disable', '1'), ('range.disable', '1')])
                self.assertFalse(cf.param.callbacks)

    def test_stock_firmware_blocks_before_partial_configuration(self):
        cf = fake_cf(patched=False)
        with self.assertRaisesRegex(RuntimeError, 'range.disable'):
            selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertEqual(cf.param.writes, [])

    def test_no_deck_needs_no_custom_firmware(self):
        cf = fake_cf(attached=False, patched=False)
        selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertEqual(cf.param.writes, [])

    def test_standalone_zranger_excludes_only_tof(self):
        cf = fake_cf(attached=False)
        cf.param.values['deck']['bcZRanger2'] = '1'
        selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertEqual(cf.param.writes, [('range.disable', '1')])

    def test_unknown_deck_identification_blocks(self):
        cf = fake_cf()
        cf.param.values.pop('deck')
        with self.assertRaisesRegex(RuntimeError, 'sin identificacion'):
            selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertFalse(cf.param.writes)

    def test_missing_ack_blocks_and_removes_callback(self):
        cf = fake_cf()
        cf.param.silent.add('range.disable')
        with patch.object(selection, 'PARAM_CONFIRM_TIMEOUT_S', 0):
            with self.assertRaisesRegex(RuntimeError, 'Sin confirmacion de range.disable'):
                selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertFalse(cf.param.callbacks)

    def test_wrong_firmware_value_blocks(self):
        cf = fake_cf()
        cf.param.rejected.add('motion.disable')
        with self.assertRaisesRegex(RuntimeError, 'Firmware devolvio motion.disable=0'):
            selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertNotIn(('range.disable', '1'), cf.param.writes)
        self.assertFalse(cf.param.callbacks)

    def test_transport_exception_is_not_hidden(self):
        cf = fake_cf()
        cf.param.set_value = Mock(side_effect=OSError('radio cerrada'))
        with self.assertRaisesRegex(OSError, 'radio cerrada'):
            selection.configure_flowdeck_feedback(cf, enabled=False)
        self.assertFalse(cf.param.callbacks)

    def test_flow_mode_restores_both_after_robotat(self):
        cf = fake_cf()
        selection.configure_flowdeck_feedback(cf, enabled=False)
        selection.configure_flowdeck_feedback(cf, enabled=True)
        self.assertEqual(cf.param.writes[-2:], [('motion.disable', '0'), ('range.disable', '0')])

    def test_flow_mode_still_works_with_stock_firmware(self):
        cf = fake_cf(patched=False)
        selection.configure_flowdeck_feedback(cf, enabled=True)
        self.assertEqual(cf.param.writes, [('motion.disable', '0')])


class ControllerIntegrationTests(unittest.TestCase):
    def unit(self, cf):
        unit = low.DroneUnit('Dron prueba', 'radio://fake', 'mocap/fake')
        unit.cf = cf
        unit.pose = low.Pose(.1, .2, .03, time.monotonic())
        unit._start_ekf_log = Mock()
        return unit

    def run_setup(self, controller, cf):
        unit = self.unit(cf)
        with patch.object(time, 'sleep'):
            if controller == 'low':
                unit.configure()
            elif controller == 'high':
                backend = object.__new__(high.HardwareBackend)
                backend._configure_highlevel(unit)
            else:
                marker.configure_for_mocap(cf)

    def test_every_robotat_setup_excludes_deck_before_reset(self):
        for controller in ('low', 'high', 'marker'):
            with self.subTest(controller=controller):
                cf = fake_cf()
                self.run_setup(controller, cf)
                self.assertEqual(cf.param.writes[:2], [('motion.disable', '1'), ('range.disable', '1')])
                self.assertGreater(cf.param.writes.index(('kalman.resetEstimation', '1')), 1)

    def test_incompatible_firmware_stops_all_robotat_setups(self):
        for controller in ('low', 'high', 'marker'):
            with self.subTest(controller=controller):
                cf = fake_cf(patched=False)
                with self.assertRaisesRegex(RuntimeError, 'range.disable'):
                    self.run_setup(controller, cf)
                self.assertEqual(cf.param.writes, [])

    def test_flow_flight_preparation_restores_feedback_before_reset(self):
        cf = fake_cf()
        selection.configure_flowdeck_feedback(cf, enabled=False)
        cf.param.writes.clear()

        @contextmanager
        def fake_logger(*_args):
            yield [(0, {'kalman.varPX': .001, 'kalman.varPY': .001, 'kalman.varPZ': .001}, None)] * 10

        with patch.object(flow_hover, 'SyncLogger', fake_logger), patch.object(time, 'sleep'):
            flow_hover.reset_and_wait_for_estimator(cf)
        self.assertEqual(cf.param.writes[:3], [('motion.disable', '0'), ('range.disable', '0'), ('kalman.resetEstimation', '1')])


if __name__ == '__main__':
    unittest.main()

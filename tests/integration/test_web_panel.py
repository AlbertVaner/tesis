"""Integracion HTTP y sesiones: todo simulado, sin radios, MQTT ni camara."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'web'))
from server import PanelServer, ExperimentSession
from session_config import SessionConfig
from cruz_highlevel_protocol import Command


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('La operacion no termino a tiempo')


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = ExperimentSession(results_root=self.temp.name)
        self.no_hardware = patch('experiment_session.HardwareBackend', side_effect=AssertionError('No abrir hardware'))
        self.no_hardware.start()

    def tearDown(self):
        wait_until(lambda: not self.session.exporting)
        self.session.close()
        self.no_hardware.stop()
        self.temp.cleanup()

    def connect(self, **config):
        self.session.configure(dict(auto_graphs=False, **config))
        self.session.connect()
        wait_until(lambda: not self.session.busy)
        self.assertTrue(self.session.backend.snapshot()['ready'], self.session.error)

    def test_hardware_is_explicitly_gated(self):
        with self.assertRaisesRegex(ValueError, 'solo permite simulacion'):
            self.session.configure({'dry_run': False})
        self.assertTrue(SessionConfig.parse({}).dry_run)
        self.assertIsNone(self.session.status()['snapshot']['drone1']['pose'])

    def test_invalid_mapping_and_ids(self):
        for values in ({'marker_id': True}, {'marker_id': -1}, {'graphs':['invalid']},
                       {'control':'hands', 'left_target':'off', 'right_target':'off'},
                       {'control':'joystick', 'drones':'drone1', 'joystick_target':'drone2'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                SessionConfig.parse(values)

    def test_each_single_drone_rejects_disabled_target(self):
        for selected, other in [('drone1', 'drone2'), ('drone2', 'drone1')]:
            self.connect(drones=selected)
            self.session.execute(Command('takeoff', 'both'))
            self.assertTrue(self.session.backend.snapshot()[selected]['airborne'])
            self.assertFalse(self.session.backend.snapshot()[other]['airborne'])
            with self.assertRaises(ValueError):
                self.session.execute(Command('takeoff', other))
            self.session.finish()
            wait_until(lambda: not self.session.busy)

    def test_one_hand_controls_both(self):
        self.connect(control='hands', hands='one', single_hand='Left')
        self.session.start_input()
        self.session.demo_input({'hands': {'Right':'DESPEGAR'}})
        self.assertFalse(self.session.backend.snapshot()['drone1']['airborne'])
        self.session.demo_input({'hands': {'Left':'DESPEGAR'}})
        self.assertTrue(all(self.session.backend.snapshot()[k]['airborne'] for k in ('drone1','drone2')))
        self.session.cooldowns.clear()
        self.session.demo_input({'hands': {'Left':'SEGUIR_MARKER'}})
        self.assertIn('solamente en Robotat real', self.session.input_status)
        self.session.demo_input({'hands': {'Left':'DETENER_SEGUIMIENTO'}})
        self.assertIn('Seguimiento detenido', self.session.input_status)

    def test_two_hands_separate_drones(self):
        self.connect(control='hands')
        self.session.start_input()
        self.session.demo_input({'hands': {'Left':'DESPEGAR'}})
        s = self.session.backend.snapshot()
        self.assertTrue(s['drone1']['airborne'])
        self.assertFalse(s['drone2']['airborne'])
        self.session.demo_input({'hands': {'Right':'DESPEGAR'}})
        self.assertTrue(self.session.backend.snapshot()['drone2']['airborne'])

    def test_two_hands_one_drone_deduplicates_and_blocks_conflict(self):
        self.connect(control='hands', drones='drone1', left_target='drone1', right_target='drone1')
        self.session.start_input()
        self.session.demo_input({'hands': {'Left':'DESPEGAR', 'Right':'DESPEGAR'}})
        self.session.cooldowns.clear()
        self.session.demo_input({'hands': {'Left':'ADELANTE', 'Right':'ADELANTE'}})
        self.assertAlmostEqual(self.session.backend.snapshot()['drone1']['pose'][0], .1)
        self.session.cooldowns.clear()
        self.session.demo_input({'hands': {'Left':'ADELANTE', 'Right':'ATRAS'}})
        self.assertAlmostEqual(self.session.backend.snapshot()['drone1']['pose'][0], .1)
        self.assertIn('conflicto', self.session.input_status)
        self.session.demo_input({'hands': {'Left':'STOP', 'Right':'ADELANTE'}})
        self.assertTrue(self.session.backend.snapshot()['emergency'])

    def test_marker_requires_zero_and_moves_selected_drone(self):
        self.connect(control='joystick', marker_id=73, joystick_target='drone2')
        self.session.start_input()
        self.session.execute(Command('takeoff', 'drone2'))
        with self.assertRaisesRegex(ValueError, 'Establece cero'):
            self.session.demo_input({'vx': .12})
        self.session.calibrate_marker()
        self.session.demo_input({'vx': .12, 'dz': .04})
        s = self.session.backend.snapshot()
        self.assertAlmostEqual(s['drone2']['pose'][0], .03)
        self.assertAlmostEqual(s['drone2']['pose'][2], .44)
        self.assertEqual(s['drone1']['pose'][0], 0)
        with self.assertRaises(ValueError):
            self.session.demo_input({'vx': float('nan')})
        self.session.stop_input()
        self.session.start_input()
        with self.assertRaises(ValueError):
            self.session.demo_input({'vx': .12})

    def test_marker_both_preserves_relative_position(self):
        self.connect(control='joystick')
        self.session.start_input()
        self.session.calibrate_marker()
        self.session.execute(Command('takeoff'))
        self.session.demo_input({'vx': .12, 'vy': .1})
        s = self.session.backend.snapshot()
        self.assertAlmostEqual(s['drone1']['pose'][0], .03)
        self.assertAlmostEqual(s['drone2']['pose'][0], .03)
        self.assertAlmostEqual(s['separation_m'], .9)

    def test_emergency_does_not_wait_for_operation_lock(self):
        self.connect()
        marker_runtime=MagicMock()
        self.session.marker_runtime=marker_runtime
        self.session.operation.acquire()
        try:
            self.session.emergency()
            self.assertTrue(self.session.backend.snapshot()['emergency'])
            marker_runtime.cancel.assert_called_once_with()
        finally:
            self.session.operation.release()
        with self.assertRaises(ValueError):
            self.session.execute(Command('takeoff'))

    def test_input_failure_lands_and_old_camera_callback_is_ignored(self):
        self.connect(control='hands')
        self.session.start_input()
        generation = self.session.input_generation
        self.session.execute(Command('takeoff'))
        self.session.input_failed('Camara no disponible', generation)
        self.assertFalse(self.session.backend.snapshot()['drone1']['airborne'])
        self.session.stop_input()
        self.session.set_frame(b'old frame', generation)
        self.assertIsNone(self.session.jpeg)

    def test_lost_panel_heartbeat_lands(self):
        self.connect()
        self.session.execute(Command('takeoff'))
        self.session.last_heartbeat = time.monotonic() - 6
        wait_until(lambda: not self.session.backend.snapshot()['drone1']['airborne'])
        self.assertFalse(self.session.backend.snapshot()['drone2']['airborne'])

    def test_config_locked_while_connected_then_clears_session(self):
        self.connect()
        with self.assertRaises(ValueError):
            self.session.configure({})
        self.session.finish()
        wait_until(lambda: not self.session.busy)
        self.session.configure({'drones':'drone2'})
        self.assertIsNone(self.session.status()['session_id'])
        self.assertTrue(self.session.status()['artifacts'])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = ExperimentSession(results_root=self.temp.name)
        self.server = PanelServer(('127.0.0.1', 0), self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.token = self.request('/api/status')[1]['control_token']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        wait_until(lambda: not self.session.exporting)
        self.session.close()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        h = {'Content-Type':'application/json', 'X-Control-Token':getattr(self,'token','')}
        h.update(headers or {})
        req = Request(self.url+path, None if body is None else json.dumps(body).encode(), h)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            if 'application/json' in response.headers.get('Content-Type',''):
                payload = json.loads(payload)
            return response.status, payload

    def test_static_and_request_guards(self):
        code, page = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn(b'ID del marker', page)
        self.assertEqual(self.request('/api/connect', {}, {'X-Control-Token':''})[0], 403)
        self.assertEqual(self.request('/api/connect', {}, {'Origin':'https://example.com'})[0], 403)
        self.assertEqual(self.request('/api/status', headers={'Host':'example.com'})[0], 403)
        self.assertEqual(self.request('/../../web/server.py')[0], 404)
        self.assertEqual(self.request('/api/config', {'dry_run':False})[0], 400)
        self.assertEqual(self.request('/api/heartbeat', {})[1], {'ok':True})

    def test_http_lifecycle_csv_and_all_graph_downloads(self):
        self.assertEqual(self.request('/api/config', {'auto_graphs':False})[0], 200)
        self.assertEqual(self.request('/api/connect', {})[0], 200)
        wait_until(lambda: not self.session.busy)
        self.assertTrue(self.request('/api/status')[1]['snapshot']['ready'])
        self.assertEqual(self.request('/api/command', {'action':'takeoff'})[0], 200)
        self.assertEqual(self.request('/api/command', {'action':'move','dx':1})[0], 400)
        self.assertEqual(self.request('/api/command', {'action':'move','dx':.1})[0], 200)
        self.session.recording.sample(self.session.backend.snapshot())
        self.assertEqual(self.request('/api/finish', {})[0], 200)
        wait_until(lambda: not self.session.busy)
        self.assertEqual(self.request('/api/export', {})[0], 200)
        wait_until(lambda: not self.session.exporting, timeout=30)
        files = self.request('/api/status')[1]['artifacts']
        self.assertEqual(len(files), 12, self.session.error)
        for item in files:
            code, data = self.request('/api/files/'+item['id'])
            self.assertEqual(code, 200)
            if item['name'].endswith('.png'): self.assertTrue(data.startswith(b'\x89PNG'))
            elif item['name'].endswith('.pdf'): self.assertTrue(data.startswith(b'%PDF'))
            elif item['name'].endswith('.csv'):
                self.assertIn(b'processing_ms', data)
                self.assertIn(b'takeoff', data)
            else: self.assertTrue(data['dry_run'])
        self.assertEqual(self.request('/api/files/-1')[0], 404)
        self.assertEqual(self.request('/api/files/9999')[0], 404)

    def test_disable_csv_keeps_config_and_optional_graphs(self):
        self.request('/api/config', {'save_csv':False, 'auto_graphs':False})
        self.request('/api/connect', {})
        wait_until(lambda: not self.session.busy)
        self.request('/api/finish', {})
        wait_until(lambda: not self.session.busy)
        self.assertEqual([f['name'] for f in self.request('/api/status')[1]['artifacts']], ['sesion.json'])


if __name__ == '__main__':
    unittest.main()

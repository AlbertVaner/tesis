"""Regresiones de Ctrl+C con sockets locales y dobles; sin camara ni radios."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control_dos_drones_cruz_multiprocessing as runtime
import control_dos_drones_cruz_camara_multiprocessing as camera


class ProcessBackendCloseTests(unittest.TestCase):
    def setUp(self):
        self.client, self.peer = socket.socketpair()
        self.client.settimeout(2)
        self.peer.settimeout(2)
        self.addCleanup(self.client.close)
        self.addCleanup(self.peer.close)
        self.peer.sendall(b'{"snapshot": {}}\n')
        self.process = Mock()
        self.process.is_alive.return_value = False
        with patch.object(runtime.ProcessBackend, '_wait_for_server', return_value=self.client):
            self.backend = runtime.ProcessBackend(self.process, 'unused', 0)
        self.addCleanup(self.backend.reader.close)

    def test_eof_during_shutdown_still_closes_and_joins(self):
        # Reproduce un hijo que ya cerro su salida al atender Ctrl+C.
        self.peer.shutdown(socket.SHUT_WR)
        self.backend.close()
        self.assertTrue(self.backend.reader.closed)
        self.assertEqual(self.client.fileno(), -1)
        self.process.join.assert_called_once_with(timeout=12.0)
        self.process.terminate.assert_not_called()
        self.backend.close()
        self.process.join.assert_called_once()

    def test_eof_outside_close_is_reported(self):
        self.peer.shutdown(socket.SHUT_WR)
        with self.assertRaisesRegex(ConnectionError, 'cerro la conexion'):
            self.backend.snapshot()

    def test_normal_shutdown_gets_acknowledgement(self):
        self.peer.sendall(b'{"ok": true, "event": "shutdown", "snapshot": {}}\n')
        self.backend.close()
        request = json.loads(self.peer.recv(4096))
        self.assertEqual(request['action'], 'shutdown')
        self.process.terminate.assert_not_called()

    def test_rejected_shutdown_is_not_hidden(self):
        self.peer.sendall(b'{"ok": false, "event": "error", "message": "rechazo de prueba"}\n')
        with self.assertRaisesRegex(RuntimeError, 'rechazo de prueba'):
            self.backend.close()
        self.assertTrue(self.backend.reader.closed)
        self.assertEqual(self.client.fileno(), -1)
        self.process.join.assert_called_once_with(timeout=12.0)

    def test_socket_write_failure_is_tolerated_only_on_close(self):
        self.client.close()
        with patch.object(self.backend, '_request', side_effect=BrokenPipeError('cerrado')):
            self.backend.close()
        self.process.join.assert_called_once_with(timeout=12.0)


class InterruptTests(unittest.TestCase):
    def test_backend_interrupt_stops_simulated_flight_and_closes(self):
        backend = runtime.SimulatedBackend(None)
        backend.connect(lambda *_args: None)
        backend.takeoff(runtime.Command('takeoff', 'drone2'))
        args = argparse.Namespace(dry_run=True, single=None, host='unused', port=0)
        with patch.object(runtime, 'SimulatedBackend', return_value=backend), \
             patch.object(runtime, 'HardwareBackend') as hardware, \
             patch.object(runtime, 'JsonLineServer') as server:
            server.return_value.serve.side_effect = KeyboardInterrupt
            runtime.backend_process(args)
        state = backend.snapshot()
        self.assertTrue(state['emergency'])
        self.assertFalse(state['drone2']['airborne'])
        self.assertFalse(state['connected'])
        hardware.assert_not_called()

    def test_backend_closes_even_if_emergency_raises(self):
        backend = Mock()
        backend.emergency.side_effect = RuntimeError('fallo de emergencia')
        args = argparse.Namespace(dry_run=True, single=None, host='unused', port=0)
        with patch.object(runtime, 'SimulatedBackend', return_value=backend), \
             patch.object(runtime, 'JsonLineServer') as server:
            server.return_value.serve.side_effect = KeyboardInterrupt
            with self.assertRaisesRegex(RuntimeError, 'fallo de emergencia'):
                runtime.backend_process(args)
        backend.close.assert_called_once()

    def test_camera_interrupt_with_live_or_disconnected_backend(self):
        for disconnected in (False, True):
            with self.subTest(disconnected=disconnected):
                args = argparse.Namespace(host='unused', port=0, target='hands')
                backend = Mock()
                if disconnected:
                    backend.emergency.side_effect = ConnectionError('cerrado')
                with patch.object(camera, 'parse_args', return_value=args), \
                     patch.object(camera.mp, 'get_context'), \
                     patch.object(camera, 'ProcessBackend', return_value=backend), \
                     patch.object(camera, 'camera_loop', side_effect=KeyboardInterrupt), \
                     patch.object(camera.cv2, 'VideoCapture') as capture:
                    self.assertEqual(camera.main(), 130)
                backend.emergency.assert_called_once()
                backend.close.assert_called_once()
                backend.land.assert_not_called()
                capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Pruebas sin hardware para el planificador de gestos sostenidos."""

from __future__ import annotations

import argparse
import queue
import time
import unittest

from drone_control.dual_multiprocess.supervisor import Supervisor


class _Logger:
    def write(self, _message, _source) -> None:
        pass


def _state(timestamp: float, requested: list[float], pose: list[float]) -> dict:
    return {
        "timestamp": timestamp,
        "phase": "HOVER",
        "requested": requested,
        "pose": pose,
    }


class GestureSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        supervisor = Supervisor.__new__(Supervisor)
        supervisor.args = argparse.Namespace(mode="both")
        supervisor.gestures = queue.Queue()
        supervisor.logger = _Logger()
        supervisor.held_gestures = {}
        supervisor.held_expected = {}
        supervisor.held_attempt_signature = {}
        supervisor.latest = {
            "Dron 1": _state(1.0, [0.0, 0.0, 0.4], [0.0, 0.0, 0.4]),
            # El primer paso debe salir incluso con la oscilacion de 8 cm
            # observada en el vuelo dual.
            "Dron 2": _state(1.0, [0.0, 1.0, 0.4], [0.0, 0.92, 0.4]),
        }
        self.calls = 0
        self.messages = []

        def execute(message):
            self.calls += 1
            self.messages.append(message)
            candidates = {}
            for name in ("Dron 1", "Dron 2"):
                requested = supervisor.latest[name]["requested"]
                candidates[name] = [requested[0], requested[1] + 0.07, requested[2]]
            return "OK", candidates

        supervisor._execute_gesture = execute
        self.supervisor = supervisor

    def test_held_gesture_waits_for_physical_arrival(self) -> None:
        now = time.monotonic()
        self.supervisor.gestures.put(
            {
                "kind": "gesture",
                "timestamp": now,
                "hand": "Right",
                "command": "DERECHA",
            }
        )
        self.supervisor._drain_gestures()
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.messages[-1]["first_step"])

        # Muchos frames de camara no crean nuevas transacciones.
        for index in range(20):
            self.supervisor.gestures.put(
                {"kind": "gesture_sample", "timestamp": now + index / 100.0}
            )
        self.supervisor._drain_gestures()
        self.assertEqual(self.calls, 1)

        # Aunque llegue telemetria nueva, no avanza hasta observar el objetivo
        # confirmado y la pose fisicamente asentada en ambos drones.
        for name in ("Dron 1", "Dron 2"):
            self.supervisor.latest[name]["timestamp"] = 2.0
        self.supervisor._drain_gestures()
        self.assertEqual(self.calls, 1)

        expected = self.supervisor.held_expected["Right"]
        for name in ("Dron 1", "Dron 2"):
            self.supervisor.latest[name] = _state(3.0, expected[name], expected[name])
        self.supervisor._drain_gestures()
        self.assertEqual(self.calls, 2)
        self.assertFalse(self.messages[-1]["first_step"])

    def test_release_cancels_continuous_movement(self) -> None:
        now = time.monotonic()
        self.supervisor.gestures.put(
            {
                "kind": "gesture",
                "timestamp": now,
                "hand": "Right",
                "command": "DERECHA",
            }
        )
        self.supervisor._drain_gestures()
        self.supervisor.gestures.put(
            {
                "kind": "gesture_release",
                "timestamp": now + 0.1,
                "hand": "Right",
                "command": "DERECHA",
            }
        )
        self.supervisor._drain_gestures()
        for name in ("Dron 1", "Dron 2"):
            expected = self.supervisor.held_expected.get("Right", {}).get(name)
            if expected is not None:
                self.supervisor.latest[name] = _state(4.0, expected, expected)
            else:
                self.supervisor.latest[name]["timestamp"] = 4.0
        self.supervisor._drain_gestures()
        self.assertEqual(self.calls, 1)
        self.assertNotIn("Right", self.supervisor.held_gestures)

    def test_first_step_flag_reaches_worker_payload(self) -> None:
        captured = {}

        def transaction(targets, action, payload):
            captured.update(targets=targets, action=action, payload=payload)
            return True, "ok", {}

        self.supervisor._transaction = transaction
        text, _candidates = Supervisor._execute_gesture(
            self.supervisor,
            {
                "hand": "Right",
                "command": "DERECHA",
                "first_step": True,
            },
        )
        self.assertIn("OK", text)
        self.assertEqual(captured["action"], "MOVER")
        self.assertTrue(captured["payload"]["allow_unsettled"])
        self.assertAlmostEqual(captured["payload"]["dy"], 0.10)


if __name__ == "__main__":
    unittest.main()

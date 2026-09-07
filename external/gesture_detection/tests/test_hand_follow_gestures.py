"""Clasificación de los dos gestos de seguimiento, sin cámara."""
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hand_gesture_detector import HandGestureDetector


class DummyLandmarks:
    pass


class FollowGestureTests(unittest.TestCase):
    def setUp(self):
        self.detector = HandGestureDetector(DummyLandmarks)

    def classify(self, **extended):
        fingers = {name: False for name in ('thumb','index','middle','ring','pinky')}
        fingers.update(extended)
        return self.detector._classify(None, fingers, 'up', 1.0)

    def test_middle_finger_alone_starts_following(self):
        self.assertEqual(self.classify(middle=True), self.detector.SEGUIR_MARKER)
        self.assertEqual(self.classify(thumb=True,middle=True), self.detector.SEGUIR_MARKER)

    def test_rock_stops_with_thumb_open_or_closed(self):
        self.assertEqual(self.classify(index=True,pinky=True), self.detector.DETENER_SEGUIMIENTO)
        self.assertEqual(self.classify(thumb=True,index=True,pinky=True), self.detector.DETENER_SEGUIMIENTO)

    def test_existing_shaka_and_pistol_are_preserved(self):
        self.assertEqual(self.classify(thumb=True,pinky=True), self.detector.ATRAS)
        self.assertEqual(self.classify(thumb=True,index=True), self.detector.ADELANTE)


if __name__ == '__main__':
    unittest.main()

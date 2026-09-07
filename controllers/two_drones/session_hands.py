"""Fuente de manos para sesiones duales; la coordinacion recibe gestos filtrados."""
import threading
import time
from pathlib import Path
import sys

class HandsSource:
    def __init__(self,index,on_gestures,on_frame,on_error):
        self.index=index; self.on_gestures=on_gestures; self.on_frame=on_frame; self.on_error=on_error
        self.stop_event=threading.Event(); self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self._run,name='SessionHands',daemon=True); self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread(): self.thread.join(timeout=2)
    def _run(self):
        cap=tracker=None
        try:
            import cv2
            folder=Path(__file__).resolve().parents[2]/'external'/'gesture_detection'
            if str(folder) not in sys.path: sys.path.insert(0,str(folder))
            from hand_tracker import HandTracker
            from hand_gesture_detector import HandGestureDetector
            cap=cv2.VideoCapture(self.index)
            if not cap.isOpened(): raise RuntimeError('No se pudo abrir la camara seleccionada')
            tracker=HandTracker(max_num_hands=2)
            detectors={hand:HandGestureDetector(tracker.landmark_enum) for hand in ('Left','Right')}
            while not self.stop_event.is_set():
                started=time.monotonic(); ok,frame=cap.read()
                if not ok: raise RuntimeError('La camara dejo de entregar imagenes')
                annotated,hands=tracker.process_hands(cv2.flip(frame,1))
                observed={}
                for landmarks,hand in hands:
                    if hand in detectors:
                        raw,filtered,_=detectors[hand].detect(landmarks,hand)
                        observed[hand]=filtered
                for hand in detectors:
                    if hand not in observed: detectors[hand].detect(None,hand)
                if self.stop_event.is_set(): break
                self.on_gestures(observed,(time.monotonic()-started)*1000)
                ok,jpeg=cv2.imencode('.jpg',annotated,[cv2.IMWRITE_JPEG_QUALITY,80])
                if ok: self.on_frame(jpeg.tobytes())
        except Exception as exc:
            if not self.stop_event.is_set(): self.on_error(str(exc))
        finally:
            if cap is not None: cap.release()
            if tracker is not None: tracker.close()

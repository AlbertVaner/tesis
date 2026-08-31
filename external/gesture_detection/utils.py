import time
import cv2

def distance_2d(p1, p2):
    if p1 is None or p2 is None:
        return float("inf")
    dx = p1.x - p2.x
    dy = p1.y - p2.y
    return (dx * dx + dy * dy) ** 0.5

def put_text_panel(frame, command, fps):
    panel_height = 100
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], panel_height), (20, 20, 20), -1)
    alpha = 0.65
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    text_color = (240, 240, 240)
    cv2.putText(frame, "MODO SIMULACION - NO CONECTADO AL DRON", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    cv2.putText(frame, f"Comando: {command}", (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (12, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)

def calculate_fps(prev_time):
    current_time = time.time()
    fps = 1.0 / (current_time - prev_time) if current_time > prev_time else 0.0
    return fps, current_time

def safe_get_landmark(landmarks, landmark_enum):
    if landmarks is None:
        return None
    try:
        return landmarks[landmark_enum]
    except (IndexError, TypeError):
        return None

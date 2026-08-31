import cv2
from datetime import datetime

from config import (
    CAMERA_INDEX,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
    MAX_NUM_HANDS,
    SAVE_CSV,
    HAND_CSV_PATH,
)
from hand_tracker import HandTracker
from hand_gesture_detector import HandGestureDetector
from logger_hand_csv import HandGestureLogger
from utils import calculate_fps


def put_hand_panel(frame, command, raw_command, handedness, fps, debug):
    panel_height = 150
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], panel_height), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    text_color = (240, 240, 240)

    cv2.putText(
        frame,
        "MODO SIMULACION - TRACKING DE MANO",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        text_color,
        2,
    )

    cv2.putText(
        frame,
        f"Comando filtrado: {command}",
        (12, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        text_color,
        2,
    )

    cv2.putText(
        frame,
        f"Raw: {raw_command} | Mano: {handedness} | FPS: {fps:.1f}",
        (12, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        text_color,
        2,
    )

    debug_text = (
        f"Orientacion: {debug.get('orientation')} | "
        f"T:{int(debug.get('thumb', False))} "
        f"I:{int(debug.get('index', False))} "
        f"M:{int(debug.get('middle', False))} "
        f"A:{int(debug.get('ring', False))} "
        f"m:{int(debug.get('pinky', False))}"
    )

    cv2.putText(
        frame,
        debug_text,
        (12, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        text_color,
        2,
    )

    cv2.putText(
        frame,
        "T=pulgar, I=indice, M=medio, A=anular, m=menique | q = salir",
        (12, 143),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        text_color,
        1,
    )


def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print("Error: no se puede abrir la cámara. Prueba cambiar CAMERA_INDEX a 1 en config.py.")
        return

    tracker = HandTracker(
        max_num_hands=MAX_NUM_HANDS,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )

    detector = HandGestureDetector(tracker.landmark_enum)
    logger = HandGestureLogger(HAND_CSV_PATH) if SAVE_CSV else None

    prev_time = 0.0

    print("Tracking de mano iniciado. Presiona 'q' para salir.")
    print("Sistema en modo simulación. No se conecta al Crazyflie.")

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Error: no se recibió imagen de la cámara.")
                break

            # Imagen en espejo para que sea más natural al usuario.
            frame = cv2.flip(frame, 1)

            annotated_frame, landmarks, handedness = tracker.process(frame)
            raw_command, filtered_command, debug = detector.detect(landmarks, handedness)

            fps, prev_time = calculate_fps(prev_time)

            put_hand_panel(
                annotated_frame,
                filtered_command,
                raw_command,
                handedness if handedness is not None else "None",
                fps,
                debug,
            )

            if logger is not None:
                logger.log(
                    timestamp=datetime.utcnow().isoformat(),
                    handedness=handedness,
                    command_raw=raw_command,
                    command_filtered=filtered_command,
                    landmarks=landmarks,
                    debug=debug,
                )

            cv2.imshow("Reconocimiento de gestos de mano - Simulacion", annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()


if __name__ == "__main__":
    main()

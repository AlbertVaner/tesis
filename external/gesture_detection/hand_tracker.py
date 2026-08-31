import cv2
import mediapipe as mp

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles



class HandTracker:
    """
    Encapsula MediaPipe Hands.

    Devuelve:
    - frame anotado
    - landmarks de la primera mano detectada
    - handedness: 'Left' o 'Right' según MediaPipe

    Nota:
    En main_hands.py se hace cv2.flip(frame, 1), por lo que la imagen se
    muestra como espejo para que sea más natural al usuario.
    """

    def __init__(
        self,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6,
    ):
        self.hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_num_hands,
            model_complexity=1,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    @property
    def landmark_enum(self):
        return mp_hands.HandLandmark

    def process_hands(self, frame):
        """Devuelve todas las manos detectadas, conservando su handedness."""
        # OpenCV usa BGR; MediaPipe usa RGB.
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self.hands.process(rgb_frame)
        rgb_frame.flags.writeable = True

        annotated_frame = frame.copy()
        detected = []
        if not results.multi_hand_landmarks:
            return annotated_frame, detected

        for index, hand_landmarks in enumerate(results.multi_hand_landmarks):
            handedness = None
            if results.multi_handedness and index < len(results.multi_handedness):
                handedness = results.multi_handedness[index].classification[0].label
            mp_drawing.draw_landmarks(
                annotated_frame,
                hand_landmarks,
                mp_hands.HAND_CONNECTIONS,
                mp_styles.get_default_hand_landmarks_style(),
                mp_styles.get_default_hand_connections_style(),
            )
            detected.append((hand_landmarks.landmark, handedness))
        return annotated_frame, detected

    def process(self, frame):
        """Compatibilidad: devuelve solo la primera mano como antes."""
        annotated_frame, detected = self.process_hands(frame)
        if not detected:
            return annotated_frame, None, None
        landmarks, handedness = detected[0]
        return annotated_frame, landmarks, handedness

    def close(self):
        self.hands.close()

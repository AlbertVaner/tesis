from collections import deque, Counter
from config import COMMAND_HISTORY_SIZE, HAND_UP_MARGIN, ARM_EXTENDED_FACTOR, HANDS_CLOSE_FACTOR, MIN_SHOULDER_WIDTH
from utils import distance_2d, safe_get_landmark

class GestureDetector:
    SIN_DETECCION = "SIN_DETECCION"
    REPOSO = "REPOSO"
    STOP = "STOP"
    DESPEGUE = "DESPEGUE"
    ATERRIZAJE = "ATERRIZAJE"
    SUBIR = "SUBIR"
    BAJAR = "BAJAR"
    IZQUIERDA = "IZQUIERDA"
    DERECHA = "DERECHA"

    def __init__(self, landmark_enum):
        self.landmark_enum = landmark_enum
        self.history = deque(maxlen=COMMAND_HISTORY_SIZE)

    def detect(self, landmarks):
        if landmarks is None:
            raw_command = self.SIN_DETECCION
            return raw_command, self._smooth(raw_command)

        right_wrist = safe_get_landmark(landmarks, self.landmark_enum.RIGHT_WRIST)
        left_wrist = safe_get_landmark(landmarks, self.landmark_enum.LEFT_WRIST)
        right_shoulder = safe_get_landmark(landmarks, self.landmark_enum.RIGHT_SHOULDER)
        left_shoulder = safe_get_landmark(landmarks, self.landmark_enum.LEFT_SHOULDER)
        right_hip = safe_get_landmark(landmarks, self.landmark_enum.RIGHT_HIP)
        left_hip = safe_get_landmark(landmarks, self.landmark_enum.LEFT_HIP)

        if None in (right_wrist, left_wrist, right_shoulder, left_shoulder, right_hip, left_hip):
            raw_command = self.REPOSO
            return raw_command, self._smooth(raw_command)

        shoulder_width = distance_2d(right_shoulder, left_shoulder)
        if shoulder_width < MIN_SHOULDER_WIDTH:
            raw_command = self.REPOSO
            return raw_command, self._smooth(raw_command)

        both_hands_above = (
            right_wrist.y < right_shoulder.y - HAND_UP_MARGIN
            and left_wrist.y < left_shoulder.y - HAND_UP_MARGIN
        )

        right_hand_above = right_wrist.y < right_shoulder.y - HAND_UP_MARGIN
        left_hand_above = left_wrist.y < left_shoulder.y - HAND_UP_MARGIN
        both_hands_below = (
            right_wrist.y > max(right_hip.y, left_hip.y) + HAND_UP_MARGIN
            and left_wrist.y > max(right_hip.y, left_hip.y) + HAND_UP_MARGIN
        )

        wrist_distance = distance_2d(right_wrist, left_wrist)
        hands_close = wrist_distance < (shoulder_width * HANDS_CLOSE_FACTOR)

        right_arm_extended = (
            right_wrist.x > right_shoulder.x + shoulder_width * ARM_EXTENDED_FACTOR
            and abs(right_wrist.y - right_shoulder.y) < shoulder_width * 0.35
        )
        left_arm_extended = (
            left_wrist.x < left_shoulder.x - shoulder_width * ARM_EXTENDED_FACTOR
            and abs(left_wrist.y - left_shoulder.y) < shoulder_width * 0.35
        )

        if both_hands_above:
            raw_command = self.DESPEGUE
        elif hands_close:
            raw_command = self.STOP
        elif both_hands_below:
            raw_command = self.ATERRIZAJE
        elif right_hand_above and not left_hand_above:
            raw_command = self.SUBIR
        elif left_hand_above and not right_hand_above:
            raw_command = self.BAJAR
        elif right_arm_extended:
            raw_command = self.DERECHA
        elif left_arm_extended:
            raw_command = self.IZQUIERDA
        else:
            raw_command = self.REPOSO

        return raw_command, self._smooth(raw_command)

    def _smooth(self, command):
        self.history.append(command)
        votes = Counter(self.history)
        most_common, count = votes.most_common(1)[0]
        if count >= (len(self.history) // 2) + 1:
            return most_common
        return command

import time
from collections import deque, Counter

from config import (
    COMMAND_HISTORY_SIZE,
    FINGER_EXTENSION_MARGIN,
    HAND_ORIENTATION_MARGIN,
    THUMB_HORIZONTAL_MARGIN,
    ENABLE_CRITICAL_HOLD,
    CRITICAL_HOLD_SECONDS,
)
from utils import distance_2d


class HandGestureDetector:
    """
    Detector de gestos de mano basado en MediaPipe Hands.

    Vocabulario implementado:

    DESPEGAR:
        índice + medio extendidos, mano hacia arriba.
        Por seguridad puede requerir sostener el gesto.

    ATERRIZAR:
        índice + medio extendidos, mano hacia abajo.
        Por seguridad puede requerir sostener el gesto.

    STOP:
        puño cerrado, sin dedos extendidos.

    DERECHA:
        pulgar extendido hacia la derecha, demás dedos cerrados.

    IZQUIERDA:
        meñique extendido, mano hacia arriba.

    ARRIBA:
        índice extendido, mano hacia arriba.

    ABAJO:
        índice extendido, mano hacia abajo.

    ADELANTE:
        índice + anular extendidos, mano hacia arriba.

    ATRÁS:
        índice + anular extendidos, mano hacia abajo.
    """

    SIN_DETECCION = "SIN_DETECCION"
    REPOSO = "REPOSO"
    STOP = "STOP"
    DESPEGAR = "DESPEGAR"
    ATERRIZAR = "ATERRIZAR"
    DERECHA = "DERECHA"
    IZQUIERDA = "IZQUIERDA"
    ARRIBA = "ARRIBA"
    ABAJO = "ABAJO"
    ADELANTE = "ADELANTE"
    ATRAS = "ATRAS"

    def __init__(self, landmark_enum):
        self.L = landmark_enum
        self.history = deque(maxlen=COMMAND_HISTORY_SIZE)

        # Para confirmación temporal de despegue/aterrizaje
        self.critical_candidate = None
        self.critical_start_time = None

    def detect(self, landmarks, handedness=None):
        if landmarks is None:
            self._reset_critical_hold()
            raw = self.SIN_DETECCION
            return raw, self._smooth(raw), self._debug_empty()

        hand_scale = self._hand_scale(landmarks)
        if hand_scale <= 1e-6:
            raw = self.REPOSO
            return raw, self._smooth(raw), self._debug_empty()

        fingers = self._finger_states(landmarks, hand_scale)
        orientation = self._hand_orientation(landmarks, fingers)

        raw = self._classify(landmarks, fingers, orientation, hand_scale)
        raw = self._apply_critical_hold(raw)

        filtered = self._smooth(raw)

        debug = {
            "orientation": orientation,
            "thumb": fingers["thumb"],
            "index": fingers["index"],
            "middle": fingers["middle"],
            "ring": fingers["ring"],
            "pinky": fingers["pinky"],
            "extended_count": sum(1 for v in fingers.values() if v),
        }

        return raw, filtered, debug

    def _classify(self, landmarks, fingers, orientation, hand_scale):
        thumb = fingers["thumb"]
        index = fingers["index"]
        middle = fingers["middle"]
        ring = fingers["ring"]
        pinky = fingers["pinky"]

        extended_count = sum(1 for v in fingers.values() if v)

        # 1. STOP tiene prioridad máxima.
        if extended_count == 0:
            return self.STOP

        # 2. Derecha: pulgar extendido horizontalmente a la derecha.
        if thumb and not index and not middle and not ring and not pinky:
            thumb_dir = self._thumb_direction(landmarks, hand_scale)
            if thumb_dir == "right":
                return self.DERECHA
            # Si el pulgar está extendido pero no suficientemente horizontal,
            # no forzamos dirección.
            return self.REPOSO

        # 3. Despegar / aterrizar: índice + medio.
        if index and middle and not thumb and not ring and not pinky:
            if orientation == "up":
                return self.DESPEGAR
            if orientation == "down":
                return self.ATERRIZAR
            return self.REPOSO

        # Adelante: pulgar + índice extendidos.
        # Gesto tipo "L" o "pistola".
        if thumb and index and not middle and not ring and not pinky:
            return self.ADELANTE

        # Atrás: pulgar + meñique extendidos.
        # Gesto tipo "shaka".
        if thumb and pinky and not index and not middle and not ring:
            return self.ATRAS

        # 5. Arriba / abajo: solo índice.
        if index and not thumb and not middle and not ring and not pinky:
            if orientation == "up":
                return self.ARRIBA
            if orientation == "down":
                return self.ABAJO
            return self.REPOSO

        # 6. Izquierda: solo meñique y mano hacia arriba.
        if pinky and not thumb and not index and not middle and not ring:
            if orientation == "up":
                return self.IZQUIERDA
            return self.REPOSO

        return self.REPOSO

    def _hand_scale(self, landmarks):
        """
        Escala aproximada de la mano.
        Se usa la distancia muñeca -> MCP del dedo medio.
        """
        wrist = landmarks[self.L.WRIST.value]
        middle_mcp = landmarks[self.L.MIDDLE_FINGER_MCP.value]
        return distance_2d(wrist, middle_mcp)

    def _finger_states(self, landmarks, hand_scale):
        """
        Determina dedos extendidos usando distancias desde la muñeca.

        Esto es más estable que solo comparar coordenadas y, porque los gestos
        también pueden apuntar hacia abajo.
        """
        L = self.L
        margin = FINGER_EXTENSION_MARGIN * hand_scale

        def extended(tip, pip, mcp):
            wrist = landmarks[L.WRIST.value]
            tip_p = landmarks[tip.value]
            pip_p = landmarks[pip.value]
            mcp_p = landmarks[mcp.value]

            # Dedo extendido si la punta está más lejos de la muñeca que PIP/MCP.
            return (
                distance_2d(wrist, tip_p) > distance_2d(wrist, pip_p) + margin
                and distance_2d(wrist, tip_p) > distance_2d(wrist, mcp_p) + margin
            )

        index = extended(
            L.INDEX_FINGER_TIP,
            L.INDEX_FINGER_PIP,
            L.INDEX_FINGER_MCP,
        )
        middle = extended(
            L.MIDDLE_FINGER_TIP,
            L.MIDDLE_FINGER_PIP,
            L.MIDDLE_FINGER_MCP,
        )
        ring = extended(
            L.RING_FINGER_TIP,
            L.RING_FINGER_PIP,
            L.RING_FINGER_MCP,
        )
        pinky = extended(
            L.PINKY_TIP,
            L.PINKY_PIP,
            L.PINKY_MCP,
        )

        thumb = self._thumb_extended(landmarks, hand_scale)

        return {
            "thumb": thumb,
            "index": index,
            "middle": middle,
            "ring": ring,
            "pinky": pinky,
        }

    def _thumb_extended(self, landmarks, hand_scale):
        """
        Pulgar extendido:
        - punta más lejos de la muñeca que la articulación IP/MCP
        - y separación suficiente respecto a la base del índice.
        """
        L = self.L
        wrist = landmarks[L.WRIST.value]
        thumb_tip = landmarks[L.THUMB_TIP.value]
        thumb_ip = landmarks[L.THUMB_IP.value]
        thumb_mcp = landmarks[L.THUMB_MCP.value]
        index_mcp = landmarks[L.INDEX_FINGER_MCP.value]

        margin = FINGER_EXTENSION_MARGIN * hand_scale

        return (
            distance_2d(wrist, thumb_tip) > distance_2d(wrist, thumb_ip) + margin
            and distance_2d(wrist, thumb_tip) > distance_2d(wrist, thumb_mcp) + margin
            and distance_2d(thumb_tip, index_mcp) > 0.55 * hand_scale
        )

    def _thumb_direction(self, landmarks, hand_scale):
        """
        Detecta pulgar hacia la derecha en la imagen.

        Como main_hands.py usa imagen en espejo, esto debe coincidir con lo que
        el usuario ve en pantalla: pulgar visualmente hacia la derecha.
        """
        L = self.L
        thumb_tip = landmarks[L.THUMB_TIP.value]
        thumb_mcp = landmarks[L.THUMB_MCP.value]

        dx = thumb_tip.x - thumb_mcp.x
        dy = abs(thumb_tip.y - thumb_mcp.y)

        if dx > THUMB_HORIZONTAL_MARGIN * hand_scale and dy < 1.25 * hand_scale:
            return "right"
        if dx < -THUMB_HORIZONTAL_MARGIN * hand_scale and dy < 1.25 * hand_scale:
            return "left"
        return None

    def _hand_orientation(self, landmarks, fingers):
        """
        Estima si la mano apunta hacia arriba o hacia abajo.

        Se usa el promedio de las puntas de los dedos extendidos principales
        comparado contra la muñeca. En la imagen:
        - y menor = más arriba
        - y mayor = más abajo
        """
        L = self.L
        wrist = landmarks[L.WRIST.value]

        extended_tips = []

        if fingers.get("index"):
            extended_tips.append(landmarks[L.INDEX_FINGER_TIP.value])
        if fingers.get("middle"):
            extended_tips.append(landmarks[L.MIDDLE_FINGER_TIP.value])
        if fingers.get("ring"):
            extended_tips.append(landmarks[L.RING_FINGER_TIP.value])
        if fingers.get("pinky"):
            extended_tips.append(landmarks[L.PINKY_TIP.value])

        # Si solo está el pulgar extendido, no usamos orientación arriba/abajo.
        if not extended_tips:
            return "unknown"

        avg_y = sum(p.y for p in extended_tips) / len(extended_tips)
        dy = avg_y - wrist.y

        if dy < -HAND_ORIENTATION_MARGIN:
            return "up"
        if dy > HAND_ORIENTATION_MARGIN:
            return "down"
        return "unknown"

    def _apply_critical_hold(self, raw):
        """
        Confirma DESPEGAR y ATERRIZAR solo si se sostienen durante cierto tiempo.
        Esto evita activaciones accidentales.
        """
        if not ENABLE_CRITICAL_HOLD:
            return raw

        if raw not in (self.DESPEGAR, self.ATERRIZAR):
            self._reset_critical_hold()
            return raw

        now = time.time()

        if self.critical_candidate != raw:
            self.critical_candidate = raw
            self.critical_start_time = now
            return f"CONFIRMANDO_{raw}"

        elapsed = now - self.critical_start_time
        if elapsed >= CRITICAL_HOLD_SECONDS:
            return raw

        return f"CONFIRMANDO_{raw}"

    def _reset_critical_hold(self):
        self.critical_candidate = None
        self.critical_start_time = None

    def _smooth(self, command):
        """
        Suavizado por mayoría para evitar parpadeos por detecciones aisladas.
        """
        self.history.append(command)
        votes = Counter(self.history)
        most_common, count = votes.most_common(1)[0]

        if count >= (len(self.history) // 2) + 1:
            return most_common

        return command

    def _debug_empty(self):
        return {
            "orientation": "none",
            "thumb": False,
            "index": False,
            "middle": False,
            "ring": False,
            "pinky": False,
            "extended_count": 0,
        }

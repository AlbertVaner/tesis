# ============================================================
# CONFIGURACIÓN GENERAL DEL PROYECTO
# Compatible con:
# - main.py        -> cuerpo completo con MediaPipe Pose
# - main_hands.py  -> mano y dedos con MediaPipe Hands
# ============================================================

# Cámara principal. Si no abre, probar con 1.
CAMERA_INDEX = 0

# MediaPipe
MIN_DETECTION_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6
MAX_NUM_HANDS = 1

# Suavizado temporal
COMMAND_HISTORY_SIZE = 8

# Guardado de datos
SAVE_CSV = True
BODY_CSV_PATH = "data/gestos_cuerpo_detectados.csv"
HAND_CSV_PATH = "data/gestos_mano_detectados.csv"

# Compatibilidad con código viejo
CSV_PATH = BODY_CSV_PATH

# ============================================================
# CONFIGURACIÓN PARA CUERPO COMPLETO
# ============================================================

HAND_UP_MARGIN = 0.07
ARM_EXTENDED_FACTOR = 0.75
HANDS_CLOSE_FACTOR = 0.45
MIN_SHOULDER_WIDTH = 0.03

# ============================================================
# CONFIGURACIÓN PARA MANO Y DEDOS
# ============================================================

# Margen normalizado para decidir si un dedo está extendido.
FINGER_EXTENSION_MARGIN = 0.06

# Umbral para detectar si la dirección principal de los dedos apunta arriba/abajo.
HAND_ORIENTATION_MARGIN = 0.05

# Umbral horizontal para detectar pulgar hacia la derecha.
THUMB_HORIZONTAL_MARGIN = 0.18

# Para detectar puño: máximo número de dedos extendidos permitido.
# 0 significa puño totalmente cerrado.
FIST_MAX_EXTENDED_FINGERS = 0

# Tiempo de confirmación para comandos críticos.
# Por seguridad, despegar y aterrizar no deberían dispararse instantáneamente.
ENABLE_CRITICAL_HOLD = True
CRITICAL_HOLD_SECONDS = 1.0

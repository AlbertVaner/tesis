from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURACIÓN GENERAL DEL PROYECTO
# El entrypoint mantenido es main_hands.py (MediaPipe Hands).
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GESTURE_DATA_DIR = (
    PROJECT_ROOT
    / "results"
    / "data"
    / "gesture_detection"
    / datetime.now().strftime("%Y-%m-%d")
)
BODY_CSV_PATH = GESTURE_DATA_DIR / "gestos_cuerpo_detectados.csv"
HAND_CSV_PATH = GESTURE_DATA_DIR / "gestos_mano_detectados.csv"

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

# Margen para decidir si la mano apunta arriba/abajo, expresado como FRACCIÓN
# de la escala de la mano (muñeca -> MCP del dedo medio), igual que
# FINGER_EXTENSION_MARGIN. Antes era un valor absoluto en coordenadas de imagen,
# por lo que la orientación dejaba de detectarse cuando la mano se alejaba de la
# cámara: la mano se veía pequeña, el desplazamiento vertical no llegaba al
# umbral fijo y DESPEGAR/ATERRIZAR/ARRIBA/ABAJO caían a REPOSO.
# Con una mano típica (escala ~0.15) el valor equivalente al antiguo 0.05 es
# 0.05 / 0.15 ~= 0.33. Subir el valor exige una inclinación más marcada.
HAND_ORIENTATION_MARGIN_FACTOR = 0.35

# Umbral horizontal para detectar pulgar hacia la derecha.
THUMB_HORIZONTAL_MARGIN = 0.18

# Para detectar puño: máximo número de dedos extendidos permitido.
# 0 significa puño totalmente cerrado.
FIST_MAX_EXTENDED_FINGERS = 0

# Tiempo de confirmación para comandos críticos.
# Por seguridad, despegar y aterrizar no deberían dispararse instantáneamente.
ENABLE_CRITICAL_HOLD = True
CRITICAL_HOLD_SECONDS = 1.0

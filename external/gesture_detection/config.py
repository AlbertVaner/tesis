from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURACIÓN DEL SUBSISTEMA DE VISIÓN
# Consumida por hand_tracker.py, hand_gesture_detector.py, main_hands.py
# y los controladores de cámara de controllers/. Los umbrales del
# vocabulario corporal 3D viven en recognition/body_3d_rules.py.
# ============================================================

# Cámara principal. Si no abre, probar con 1.
CAMERA_INDEX = 0

# MediaPipe Hands
MIN_DETECTION_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6
MAX_NUM_HANDS = 1

# Suavizado temporal del detector de mano (votación sobre los últimos N frames)
COMMAND_HISTORY_SIZE = 8

# Guardado de datos (sólo main_hands.py)
SAVE_CSV = True
HAND_CSV_PATH = (
    Path(__file__).resolve().parents[2]
    / "results"
    / "data"
    / "gesture_detection"
    / datetime.now().strftime("%Y-%m-%d")
    / "gestos_mano_detectados.csv"
)

# ============================================================
# GESTOS DE MANO (hand_gesture_detector.py)
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

# Tiempo de confirmación para comandos críticos.
# Por seguridad, despegar y aterrizar no deberían dispararse instantáneamente.
ENABLE_CRITICAL_HOLD = True
CRITICAL_HOLD_SECONDS = 1.0

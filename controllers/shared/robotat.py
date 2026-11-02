"""Identidad del sistema de captura Robotat: broker MQTT, tópicos y frescura.

Sólo constantes. Es la única fuente de estos valores en el repositorio; los
controladores los importan en vez de repetir literales.
"""

#: Broker MQTT del Robotat (Node-RED) en la red del laboratorio.
MQTT_BROKER = "192.168.50.200"
MQTT_PORT = 1880

#: Tópicos por defecto. El Dron 1, el Dron 2 y el Dron 3 corresponden a los
#: rigid bodies 3, 4 y 5 del Robotat (`identifier` 83, 84 y 85 en el mensaje);
#: `mocap/all` publica todos los marcadores.
DRONE_1_TOPIC = "mocap/drone3"
DRONE_2_TOPIC = "mocap/drone4"
DRONE_3_TOPIC = "mocap/drone5"
ALL_MARKERS_TOPIC = "mocap/all"

#: Edad máxima de una pose para considerarla utilizable en un lazo de control.
MOCAP_TIMEOUT_S = 0.75

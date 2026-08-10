import time
import json
import threading
import numpy as np
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Visualización en tiempo real de flujo de datos del servidor MQTT.

# -------------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------------
MQTT_TOPIC = 'mocap/drone3'   # Tópico MQTT del sistema de captura
BROKER = '192.168.50.200'          # Cambia por la IP de tu broker
PORT = 1880

# Variables compartidas
mocap_pose = {'x': 0.0, 'y': 0.0, 'z': 0.0}

# Trayectorias cortas
max_len = 100
mocap_traj = {'x': [], 'y': [], 'z': []}

# -------------------------------------------------------
# CALLBACK MQTT (lectura)
# -------------------------------------------------------
def on_message(client, userdata, msg):
    global mocap_pose
    try:
        data = json.loads(msg.payload.decode())
        pos = data['payload']['pose']['position']

        # Actualizar posición del MoCap
        mocap_pose['x'] = float(pos['x'])
        mocap_pose['y'] = float(pos['y'])
        mocap_pose['z'] = float(pos['z'])

    except Exception as e:
        print("Error en MQTT:", e)
        print("Mensaje:", msg.payload.decode())

def start_mqtt():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(MQTT_TOPIC)
    client.loop_forever()

# -------------------------------------------------------
# GRAFICADO EN TIEMPO REAL
# -------------------------------------------------------
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

# Puntos y líneas del MoCap
mocap_point, = ax.plot([], [], [], 'ro', label='MoCap', markersize=6)
mocap_line, = ax.plot([], [], [], 'r-', alpha=0.5)

# Límites de los ejes
ax.set_xlim(-2, 2)
ax.set_ylim(-2, 2)
ax.set_zlim(0, 2)
ax.set_xlabel('X [m]')
ax.set_ylabel('Y [m]')
ax.set_zlabel('Z [m]')
ax.legend()
ax.set_title("Trayectoria MoCap (MQTT)")

def update(frame):
    # Agregar nuevo punto a la trayectoria
    mocap_traj['x'].append(mocap_pose['x'])
    mocap_traj['y'].append(mocap_pose['y'])
    mocap_traj['z'].append(mocap_pose['z'])

    # Mantener longitud máxima (cola de N puntos)
    if len(mocap_traj['x']) > max_len:
        mocap_traj['x'].pop(0)
        mocap_traj['y'].pop(0)
        mocap_traj['z'].pop(0)

    # Actualizar líneas y puntos
    mocap_line.set_data(mocap_traj['x'], mocap_traj['y'])
    mocap_line.set_3d_properties(mocap_traj['z'])

    mocap_point.set_data([mocap_pose['x']], [mocap_pose['y']])
    mocap_point.set_3d_properties([mocap_pose['z']])

    return mocap_point, mocap_line

ani = FuncAnimation(fig, update, interval=100)

# -------------------------------------------------------
# HILO MQTT
# -------------------------------------------------------
mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
mqtt_thread.start()

plt.show()
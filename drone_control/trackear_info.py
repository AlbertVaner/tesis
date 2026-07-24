import json
import time
import threading
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt
from datetime import datetime
from mpl_toolkits.mplot3d import Axes3D  # necesario para 3D


# -------------------------------------------------------
# CONFIGURACIÓN MQTT / MOCAP
# -------------------------------------------------------
MQTT_TOPIC = "mocap/drone2"
MQTT_BROKER = "192.168.50.200"
PORT = 1880


# -------------------------------------------------------
# VARIABLES GLOBALES
# -------------------------------------------------------
mocap_pose = {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
}

last_ts = None
new_data = False
stop_event = threading.Event()

# Control de grabación
recording = False
t0 = None

# Datos para guardar la trayectoria
time_data = []
x_data = []
y_data = []
z_data = []


# -------------------------------------------------------
# CALLBACK MQTT
# -------------------------------------------------------
def on_message(client, userdata, msg):
    global mocap_pose, last_ts, new_data
    global recording, t0
    global time_data, x_data, y_data, z_data

    try:
        data = json.loads(msg.payload.decode())

        pos = data["payload"]["pose"]["position"]
        ts_str = data.get("ts", None)

        # Ignorar mensajes viejos
        if ts_str is not None:
            msg_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

            if last_ts is not None and msg_time <= last_ts:
                return

            last_ts = msg_time

        mocap_pose["x"] = float(pos["x"])
        mocap_pose["y"] = float(pos["y"])
        mocap_pose["z"] = float(pos["z"])

        # Guardar datos solo si recording está activo
        if recording and t0 is not None:
            t_rel = time.time() - t0

            time_data.append(t_rel)
            x_data.append(mocap_pose["x"])
            y_data.append(mocap_pose["y"])
            z_data.append(mocap_pose["z"])

        new_data = True

    except Exception as e:
        print("Error en MQTT:", e)
        print("Mensaje recibido:", msg.payload.decode())


# -------------------------------------------------------
# INICIAR MQTT
# -------------------------------------------------------
def start_mqtt():
    client = mqtt.Client()
    client.on_message = on_message

    client.connect(MQTT_BROKER, PORT, 60)
    client.subscribe(MQTT_TOPIC)

    print(f"MQTT conectado. Escuchando tópico: {MQTT_TOPIC}")

    while not stop_event.is_set():
        client.loop(timeout=0.1)

    client.disconnect()
    print("MQTT desconectado.")


# -------------------------------------------------------
# HILO PARA IMPRIMIR POSICIÓN ACTUAL
# -------------------------------------------------------
def print_pose_loop():
    global new_data

    last_print_time = 0.0

    while not stop_event.is_set():
        if new_data:
            now = time.time()

            # Imprimir cada 0.1 s aprox
            if now - last_print_time >= 0.1:
                estado = "GRABANDO" if recording else "NO GRABANDO"

                if t0 is not None and recording:
                    elapsed = now - t0
                else:
                    elapsed = 0.0

                print(
                    f"[{estado}] "
                    f"t={elapsed:05.2f}s | "
                    f"x={mocap_pose['x']:.4f} m, "
                    f"y={mocap_pose['y']:.4f} m, "
                    f"z={mocap_pose['z']:.4f} m"
                )

                last_print_time = now

            new_data = False

        time.sleep(0.01)


# -------------------------------------------------------
# GRAFICAR MOVIMIENTO
# -------------------------------------------------------
def plot_movement():
    if len(time_data) == 0:
        print("No se grabaron datos para graficar.")
        return

    # ---------- Figura 1: Trayectoria 3D ----------
    fig1 = plt.figure(figsize=(8, 6))
    ax1 = fig1.add_subplot(111, projection="3d")

    ax1.plot(x_data, y_data, z_data, label="Trayectoria grabada")
    ax1.scatter(x_data[0], y_data[0], z_data[0], marker="o", s=60, label="Inicio")
    ax1.scatter(x_data[-1], y_data[-1], z_data[-1], marker="x", s=80, label="Fin")

    ax1.set_xlabel("X [m]")
    ax1.set_ylabel("Y [m]")
    ax1.set_zlabel("Z [m]")
    ax1.set_title("Movimiento del dron en 3D")
    ax1.legend()
    ax1.grid(True)

    # ---------- Figura 2: Trayectoria en XY ----------
    plt.figure(figsize=(7, 6))
    plt.plot(x_data, y_data, label="Trayectoria XY")
    plt.scatter(x_data[0], y_data[0], marker="o", s=60, label="Inicio")
    plt.scatter(x_data[-1], y_data[-1], marker="x", s=80, label="Fin")
    plt.xlabel("X [m]")
    plt.ylabel("Y [m]")
    plt.title("Trayectoria del dron en el plano X-Y")
    plt.axis("equal")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    # ---------- Figura 3: Altura vs tiempo ----------
    plt.figure(figsize=(8, 5))
    plt.plot(time_data, z_data, label="Z [m]")
    plt.xlabel("Tiempo [s]")
    plt.ylabel("Altura Z [m]")
    plt.title("Altura del dron vs tiempo")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    # ---------- Figura 4: X, Y, Z vs tiempo ----------
    plt.figure(figsize=(10, 5))
    plt.plot(time_data, x_data, label="X [m]")
    plt.plot(time_data, y_data, label="Y [m]")
    plt.plot(time_data, z_data, label="Z [m]")
    plt.xlabel("Tiempo [s]")
    plt.ylabel("Posición [m]")
    plt.title("Posición del dron vs tiempo")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    plt.show()


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    global recording, t0
    global time_data, x_data, y_data, z_data

    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    print_thread = threading.Thread(target=print_pose_loop, daemon=True)
    print_thread.start()

    print("Esperando datos del MoCap...")
    time.sleep(1.0)

    input("\nPresiona ENTER para EMPEZAR a grabar...")

    # Limpiar datos anteriores
    time_data = []
    x_data = []
    y_data = []
    z_data = []

    t0 = time.time()
    recording = True

    print("\nGrabación iniciada.")
    print("Presiona ENTER otra vez para DETENER la grabación.\n")

    input()

    recording = False
    print("\nGrabación detenida.")

    stop_event.set()
    mqtt_thread.join(timeout=1.0)
    print_thread.join(timeout=1.0)

    print(f"Cantidad de puntos grabados: {len(time_data)}")
    plot_movement()


if __name__ == "__main__":
    main()
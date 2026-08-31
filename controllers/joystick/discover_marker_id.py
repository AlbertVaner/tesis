"""Descubre el tópico MQTT que corresponde a una ID de rigid body ROBOTAT.

No abre radio ni se conecta al Crazyflie.
"""

from __future__ import annotations

import argparse
import json
import threading
import time

import paho.mqtt.client as mqtt


BROKER = "192.168.50.200"
PORT = 1880


def contains_id(value, target_id: int) -> bool:
    """Busca la ID tanto como número como texto dentro del JSON recibido."""
    if isinstance(value, dict):
        return any(contains_id(item, target_id) for item in value.values())
    if isinstance(value, list):
        return any(contains_id(item, target_id) for item in value)
    return value == target_id or value == str(target_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Encuentra el tópico MQTT de un rigid body ROBOTAT")
    parser.add_argument("--id", type=int, default=64, help="ID del marker/rigid body")
    parser.add_argument("--seconds", type=float, default=10.0, help="Tiempo de escucha")
    parser.add_argument("--show-all", action="store_true", help="Muestra todos los tópicos mocap recibidos")
    args = parser.parse_args()

    stop = threading.Event()
    seen_topics: set[str] = set()
    matches: set[str] = set()

    def on_message(_client, _userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if message.topic not in seen_topics and args.show_all:
            seen_topics.add(message.topic)
            print(f"Tópico visto: {message.topic}\n  Ejemplo: {json.dumps(data)[:500]}")
        if contains_id(data, args.id) and message.topic not in matches:
            matches.add(message.topic)
            print(f"\nENCONTRADO ID {args.id}: tópico = {message.topic}")
            print(f"Mensaje: {json.dumps(data, indent=2)[:1500]}")

    client = mqtt.Client()
    client.on_message = on_message
    try:
        client.connect(BROKER, PORT, 60)
        client.subscribe("mocap/#")
        print(f"Escuchando mocap/# por {args.seconds:.0f} s para la ID {args.id}...")
        print("Mueva el marker 64 para asegurar que ROBOTAT lo publique.")
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and not stop.is_set():
            client.loop(timeout=0.1)
    finally:
        client.disconnect()

    if matches:
        print("\nSi el tópico es compartido (mocap/all o mocap/allv2), úselo junto con --marker-id.")
    else:
        print("\nNo apareció la ID 64 dentro de los mensajes MQTT.")
        print("Pruebe de nuevo con --show-all; puede que ROBOTAT codifique la ID solo en el nombre del tópico.")


if __name__ == "__main__":
    main()

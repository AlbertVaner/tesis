r"""Visor de consola de los rigid bodies del Robotat. No conecta ningún dron.

Muestra, refrescando en pantalla, la posición y la orientación (roll, pitch,
yaw) que publica el Robotat para cada tópico, cuántos frames distintos llegan
por segundo y la diferencia de rumbo entre los dos primeros. Sirve para
colocar los drones en paralelo antes del preflight y para ver si un rigid
body está definido girado: con los dos drones paralelos, la diferencia de yaw
es el offset que aplica `--alinear-rumbo`.

    .\.venv\Scripts\python.exe .\controllers\joystick\ver_markers.py
    .\.venv\Scripts\python.exe .\controllers\joystick\ver_markers.py --topics mocap/drone3 mocap/drone4
    .\.venv\Scripts\python.exe .\controllers\joystick\ver_markers.py --topics mocap/all --id 65

Ctrl+C termina.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
SHARED_DIR = MODULE_DIR.parent / "shared"
for directory in (MODULE_DIR, SHARED_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from marker_mocap import MocapReceiver, Pose  # noqa: E402
from robotat import DRONE_1_TOPIC, DRONE_2_TOPIC, MOCAP_TIMEOUT_S, MQTT_BROKER, MQTT_PORT  # noqa: E402

REFRESH_S = 0.20
RATE_WINDOW_S = 2.0


class MarkerView:
    """Últimas poses de un tópico y su tasa de frames distintos."""

    def __init__(self, topic: str, identifier: int | None, broker: str, port: int) -> None:
        self.topic = topic
        self.times: deque[float] = deque()
        self.last: Pose | None = None
        self.receiver = MocapReceiver(
            topic, broker=broker, port=port, on_pose=self._on_pose,
            required_identifier=identifier,
        )

    def _on_pose(self, pose: Pose) -> None:
        # El puente repite cada frame varias veces: solo cuenta lo que cambia.
        if self.last is not None and (pose.x, pose.y, pose.z, pose.yaw_deg) == (
            self.last.x, self.last.y, self.last.z, self.last.yaw_deg
        ):
            return
        self.last = pose
        now = time.monotonic()
        self.times.append(now)
        while self.times and now - self.times[0] > RATE_WINDOW_S:
            self.times.popleft()

    def rate_hz(self) -> float:
        if len(self.times) < 2:
            return 0.0
        span = self.times[-1] - self.times[0]
        return (len(self.times) - 1) / span if span > 0 else 0.0

    def start(self) -> None:
        self.receiver.start()

    def stop(self) -> None:
        self.receiver.stop()


def wrap_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def render(views: list[MarkerView]) -> str:
    lines = [
        f"{'topico':<16}{'x [m]':>9}{'y [m]':>9}{'z [m]':>9}"
        f"{'roll':>8}{'pitch':>8}{'yaw':>8}{'Hz':>7}{'edad':>8}",
        "-" * 82,
    ]
    yaws: list[float | None] = []
    for view in views:
        pose = view.last
        if pose is None:
            lines.append(f"{view.topic:<16}{'sin datos':>20}   {view.receiver.error}")
            yaws.append(None)
            continue
        age = pose.age_s
        stale = "  (CADUCA)" if age > MOCAP_TIMEOUT_S else ""
        lines.append(
            f"{view.topic:<16}{pose.x:>9.3f}{pose.y:>9.3f}{pose.z:>9.3f}"
            f"{pose.roll_deg:>8.1f}{pose.pitch_deg:>8.1f}{pose.yaw_deg:>8.1f}"
            f"{view.rate_hz():>7.1f}{age:>7.2f}s{stale}"
        )
        yaws.append(pose.yaw_deg)
    if len(yaws) >= 2 and yaws[0] is not None and yaws[1] is not None:
        difference = wrap_deg(yaws[0] - yaws[1])
        lines.append("")
        lines.append(
            f"yaw({views[0].topic}) - yaw({views[1].topic}) = {difference:+.1f} grados"
        )
        lines.append(
            "Con los dos drones en paralelo, ese valor es el offset del primero "
            "respecto al segundo (lo que aplica --alinear-rumbo)."
        )
    lines.append("")
    lines.append("Ctrl+C para salir.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ver los rigid bodies del Robotat en consola")
    parser.add_argument(
        "--topics", nargs="+", default=[DRONE_1_TOPIC, DRONE_2_TOPIC],
        help="topicos MQTT a mostrar (predeterminado: los dos drones)",
    )
    parser.add_argument("--id", type=int, default=None,
                        help="con un topico agregado como mocap/all, id del rigid body a mostrar")
    parser.add_argument("--broker", default=MQTT_BROKER)
    parser.add_argument("--puerto", type=int, default=MQTT_PORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    views = [MarkerView(topic, args.id, args.broker, args.puerto) for topic in args.topics]
    for view in views:
        view.start()
    print(f"Conectando a {args.broker}:{args.puerto}...", flush=True)
    try:
        while True:
            # Limpia la consola sin depender del sistema: cursor arriba y borrar.
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write(render(views) + "\n")
            sys.stdout.flush()
            time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        pass
    finally:
        for view in views:
            view.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

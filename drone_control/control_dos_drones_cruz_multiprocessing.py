r"""Control high-level por botones con GUI y hardware en procesos separados.

Prueba sin hardware:
    python .\drone_control\control_dos_drones_cruz_multiprocessing.py --dry-run

Prueba real:
    python .\drone_control\control_dos_drones_cruz_multiprocessing.py
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import socket
import threading
import time
from typing import Any, Callable

from control_dos_drones_cruz_botones import HighLevelButtonsApp
from cruz_highlevel_backend import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TOPIC_1,
    DEFAULT_TOPIC_2,
    DEFAULT_URI_1,
    DEFAULT_URI_2,
    HardwareBackend,
    JsonLineServer,
    SimulatedBackend,
)
from cruz_highlevel_protocol import Command


def backend_process(args: argparse.Namespace) -> None:
    backend = SimulatedBackend(args.single) if args.dry_run else HardwareBackend(args)
    JsonLineServer(args.host, args.port, backend).serve()


class ProcessBackend:
    """Adaptador de la GUI al backend propietario del hardware."""

    def __init__(self, process: mp.Process, host: str, port: int) -> None:
        self.process = process
        self.socket = self._wait_for_server(host, port)
        self.reader = self.socket.makefile("r", encoding="utf-8", newline="\n")
        self._latest = self._receive()["snapshot"]
        self._lock = threading.RLock()
        self._closed = False

    @staticmethod
    def _wait_for_server(host: str, port: int) -> socket.socket:
        deadline = time.monotonic() + 12.0
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                connection = socket.create_connection((host, port), timeout=1.0)
                # El segundo de timeout solo sirve para reintentar mientras
                # arranca el proceso. El preflight real puede tardar varios
                # segundos esperando Robotat, radios y alineacion EKF.
                connection.settimeout(None)
                return connection
            except OSError as exc:
                last_error = exc
                time.sleep(0.10)
        raise RuntimeError(f"el proceso backend no inicio: {last_error}")

    def _receive(self) -> dict[str, Any]:
        line = self.reader.readline()
        if not line:
            raise RuntimeError("el proceso backend cerro la conexion")
        response = json.loads(line)
        if response.get("snapshot") is not None:
            self._latest = response["snapshot"]
        return response

    def _request(
        self,
        action: str,
        target: str = "both",
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
        emit: Callable | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            payload = {"action": action, "target": target, "dx": dx, "dy": dy, "dz": dz}
            self.socket.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            while True:
                response = self._receive()
                if emit is not None:
                    emit(
                        bool(response.get("ok")),
                        str(response.get("event", "status")),
                        str(response.get("message", "")),
                        response.get("snapshot"),
                    )
                if response.get("event") == action or not response.get("ok", False):
                    break
            if not response.get("ok", False):
                raise RuntimeError(str(response.get("message", "comando rechazado")))
            return response

    def snapshot(self) -> dict[str, Any]:
        if self._closed:
            return self._latest
        # El hilo de una accion conserva el canal hasta recibir su respuesta.
        # Tkinter no debe congelarse intentando consultar estado durante el
        # preflight, takeoff o aterrizaje.
        if not self._lock.acquire(blocking=False):
            return self._latest
        try:
            return self._request("status")["snapshot"]
        finally:
            self._lock.release()

    def connect(self, emit: Callable) -> None:
        self._request("connect", emit=emit)

    def takeoff(self, command: Command) -> None:
        self._request("takeoff", command.target)

    def move(self, command: Command) -> None:
        self._request("move", command.target, dx=command.dx, dy=command.dy, dz=command.dz)

    def land(self, command: Command) -> None:
        self._request("land", command.target)

    def emergency(self, reason: str = "orden manual") -> None:
        del reason
        self._request("emergency")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._request("shutdown")
        finally:
            self._closed = True
            try:
                self.reader.close()
                self.socket.close()
            finally:
                self.process.join(timeout=12.0)
                if self.process.is_alive():
                    # El backend normalmente termina solo; terminate es el
                    # ultimo recurso al cerrar, cuando ya ejecuto shutdown.
                    self.process.terminate()
                    self.process.join(timeout=3.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dos Crazyflies por botones con backend multiproceso")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--uri1", default=DEFAULT_URI_1)
    parser.add_argument("--uri2", default=DEFAULT_URI_2)
    parser.add_argument("--topic1", default=DEFAULT_TOPIC_1)
    parser.add_argument("--topic2", default=DEFAULT_TOPIC_2)
    parser.add_argument("--single", choices=("drone1", "drone2"), help="habilita solamente un dron")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = mp.get_context("spawn")
    process = context.Process(target=backend_process, args=(args,), name="CruzHardwareBackend")
    process.start()
    try:
        backend = ProcessBackend(process, args.host, args.port)
        HighLevelButtonsApp(backend, dry_run=args.dry_run).mainloop()
        return 0
    except Exception:
        if process.is_alive():
            process.terminate()
            process.join(timeout=3.0)
        raise


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())

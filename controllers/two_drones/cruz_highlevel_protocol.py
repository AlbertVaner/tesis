"""Comandos validados para la interfaz Python de control high-level.

Este modulo no importa cflib ni abre hardware. Se mantiene pequeno para poder
validar todos los comandos con pruebas unitarias sin Crazyflies.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


VALID_ACTIONS = frozenset(
    {"connect", "status", "takeoff", "move", "land", "emergency", "shutdown"}
)
VALID_TARGETS = frozenset({"drone1", "drone2", "both"})
MAX_MOVE_STEP_M = 0.10


class ProtocolError(ValueError):
    """Mensaje JSON invalido o fuera de los limites permitidos."""


@dataclass(frozen=True)
class Command:
    action: str
    target: str = "both"
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0


def decode_command(line: str) -> Command:
    """Decodifica una linea JSON y aplica una lista blanca estricta."""
    try:
        # Algunos clientes .NET agregan BOM UTF-8 al primer mensaje. Aceptarlo
        # vuelve el protocolo local de diagnostico mas robusto.
        value = json.loads(line.lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"JSON invalido: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("el mensaje debe ser un objeto JSON")

    action = str(value.get("action", "")).strip().lower()
    if action not in VALID_ACTIONS:
        raise ProtocolError(f"accion no permitida: {action or '(vacia)'}")

    target = str(value.get("target", "both")).strip().lower()
    if target not in VALID_TARGETS:
        raise ProtocolError(f"objetivo no permitido: {target}")

    components: list[float] = []
    for name in ("dx", "dy", "dz"):
        raw = value.get(name, 0.0)
        if isinstance(raw, bool):
            raise ProtocolError(f"{name} debe ser numerico")
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"{name} debe ser numerico") from exc
        if not math.isfinite(number):
            raise ProtocolError(f"{name} debe ser finito")
        if abs(number) > MAX_MOVE_STEP_M + 1e-9:
            raise ProtocolError(
                f"{name}={number:.3f} excede el paso maximo de {MAX_MOVE_STEP_M:.2f} m"
            )
        components.append(number)

    if action == "move":
        if not any(abs(component) > 1e-9 for component in components):
            raise ProtocolError("move requiere un desplazamiento distinto de cero")
    elif any(abs(component) > 1e-9 for component in components):
        raise ProtocolError(f"la accion {action} no acepta dx/dy/dz")

    return Command(action, target, *components)


def encode_response(
    *,
    ok: bool,
    event: str,
    message: str,
    snapshot: dict[str, Any] | None = None,
) -> bytes:
    """Serializa una respuesta JSON terminada en salto de linea."""
    payload: dict[str, Any] = {"ok": ok, "event": event, "message": message}
    if snapshot is not None:
        payload["snapshot"] = snapshot
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )

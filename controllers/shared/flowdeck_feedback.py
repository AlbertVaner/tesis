"""Seleccion de mediciones del Flow Deck; sin dependencia de UI o de radios."""

from __future__ import annotations

import threading


PARAM_CONFIRM_TIMEOUT_S = 5.0


def _set_confirmed(param, complete_name: str, value: int) -> None:
    """Espera respuesta del firmware; no confunde set_value con confirmacion."""
    group, name = complete_name.split(".")
    confirmed = threading.Event()
    received = []

    def on_update(_name, actual):
        received.append(str(actual))
        confirmed.set()

    param.add_update_callback(group=group, name=name, cb=on_update)
    try:
        param.set_value(complete_name, str(value))
        if not confirmed.wait(PARAM_CONFIRM_TIMEOUT_S):
            raise RuntimeError(f"Sin confirmacion de {complete_name}={value}; preflight bloqueado")
        if received[-1] != str(value):
            raise RuntimeError(
                f"Firmware devolvio {complete_name}={received[-1]}, se esperaba {value}; preflight bloqueado"
            )
    finally:
        param.remove_update_callback(group=group, name=name, cb=on_update)


def configure_flowdeck_feedback(cf, *, enabled: bool) -> None:
    """Excluye flujo/ToF en Robotat, o los habilita en vuelo con Flow Deck.

    range.disable es provisto por el parche de external/crazyflie_firmware/.
    El firmware estandar permite desactivar solo el flujo optico.
    Debe llamarse conectado, sin motores, antes del reset del estimador.
    """
    param = cf.param

    def has(name):
        return param.toc.get_element_by_complete_name(name) is not None

    def attached(name):
        return has(name) and int(param.get_value(name, timeout=PARAM_CONFIRM_TIMEOUT_S)) != 0

    deck_flags = ("deck.bcFlow", "deck.bcFlow2", "deck.bcZRanger", "deck.bcZRanger2")
    if not any(has(name) for name in deck_flags):
        raise RuntimeError("Firmware sin identificacion de Flow Deck/Z-ranger; no se puede seleccionar la realimentacion")
    flow = any(attached(name) for name in deck_flags[:2])
    down_range = flow or any(attached(name) for name in deck_flags[2:])
    required = []
    if flow:
        required.append("motion.disable")
    if down_range and (not enabled or has("range.disable")):
        required.append("range.disable")

    missing = [name for name in required if not has(name)]
    if missing:
        raise RuntimeError(
            "Robotat requiere ignorar flujo optico y distancia al suelo. "
            f"Faltan parametros de firmware: {', '.join(missing)}. "
            "Instala el parche documentado en external/crazyflie_firmware/README.md; "
            "no basta motion.disable. Preflight bloqueado."
        )
    for name in required:
        param.get_value(name, timeout=PARAM_CONFIRM_TIMEOUT_S)
        _set_confirmed(param, name, 0 if enabled else 1)

    if required:
        mode = "Flow Deck: realimentacion habilitada" if enabled else "Robotat: realimentacion Flow Deck/Z-ranger excluida"
        print(f"{mode} ({', '.join(required)} confirmados).", flush=True)
    else:
        print("Sin Flow Deck ni Z-ranger detectados; no se cambian mediciones.", flush=True)

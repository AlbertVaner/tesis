"""Construcción y enmascarado de URLs RTSP por modelo de cámara.

Este módulo no abre conexiones: sólo arma cadenas. Vive en `capture/` porque
es conocimiento de transporte, no de contenido.

Ver docs/hardware.md para el formato de cada modelo.
"""

from __future__ import annotations

import re
from urllib.parse import quote

# Rutas RTSP por modelo. `main` es el stream principal, `sub` el secundario.
# Añadir un modelo nuevo es añadir una entrada aquí, no tocar el código.
RTSP_PATHS: dict[str, dict[str, str]] = {
    "tapo_c210": {
        "main": "/stream1",
        "sub": "/stream2",
    },
    "amcrest_ip4m_1041b": {
        "main": "/cam/realmonitor?channel=1&subtype=0",
        "sub": "/cam/realmonitor?channel=1&subtype=1",
    },
}

# Patrón para enmascarar credenciales al registrar o mostrar una URL.
_CREDENTIALS_RE = re.compile(r"://([^:/@]+):([^@/]+)@")


class UnknownCameraModel(ValueError):
    """El modelo pedido no está en RTSP_PATHS."""


def build_rtsp_url(
    model: str,
    host: str,
    user: str,
    password: str,
    stream: str = "main",
    port: int = 554,
) -> str:
    """Devuelve la URL RTSP para una cámara.

    Args:
        model: clave de RTSP_PATHS, p. ej. "tapo_c210".
        host: IP o nombre de la cámara.
        user, password: credenciales del *usuario de cámara*, que en Tapo es
            distinto de la cuenta TP-Link. Ver README.
        stream: "main" o "sub".
        port: puerto RTSP; 554 salvo que se haya cambiado.

    Raises:
        UnknownCameraModel: si el modelo no está registrado.
        ValueError: si `stream` no es "main" ni "sub".
    """
    if model not in RTSP_PATHS:
        conocidos = ", ".join(sorted(RTSP_PATHS))
        raise UnknownCameraModel(
            f"Modelo de cámara desconocido: {model!r}. Conocidos: {conocidos}. "
            "Para una cámara arbitraria, usar una URL completa en lugar de un modelo."
        )
    if stream not in ("main", "sub"):
        raise ValueError(f"stream debe ser 'main' o 'sub', no {stream!r}")

    # Las credenciales van percent-encoded: las contraseñas de cámara suelen
    # llevar caracteres que romperían la URL.
    usuario = quote(user, safe="")
    clave = quote(password, safe="")
    ruta = RTSP_PATHS[model][stream]
    return f"rtsp://{usuario}:{clave}@{host}:{port}{ruta}"


def mask_url(url: str) -> str:
    """Oculta las credenciales de una URL para poder registrarla.

    Nunca registrar, mostrar ni incluir en un nombre de archivo una URL sin
    pasarla por aquí. Ver AGENTS.md, sección de seguridad.
    """
    return _CREDENTIALS_RE.sub("://***:***@", url)

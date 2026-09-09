"""Carga de la configuración de cámaras.

La configuración real vive en `config/cameras.local.yaml`, que no se versiona
porque contiene credenciales. `config/cameras.example.yaml` es la plantilla.

Credenciales
------------
Cada cámara puede tener las suyas: en las Tapo, la "cuenta de cámara" se crea
por dispositivo y no tiene por qué coincidir entre cámaras.

Precedencia, de mayor a menor:

1. Variables de entorno por cámara: ``CAM_<NOMBRE>_USER`` / ``CAM_<NOMBRE>_PASSWORD``
   (nombre en mayúsculas, cualquier carácter no alfanumérico pasa a ``_``).
2. Claves ``user`` / ``password`` dentro de la entrada de esa cámara en el YAML.
3. Variables de entorno globales ``CAM_USER`` / ``CAM_PASSWORD``.
4. Bloque ``credentials`` global del YAML.

Preferir el entorno cuando se pueda: evita dejar credenciales en disco.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .urls import build_rtsp_url

# Orden de búsqueda de la configuración, relativo a la raíz del repositorio.
RUTAS_POR_DEFECTO = (
    Path("config/cameras.local.yaml"),
    Path("config/cameras.local.yml"),
    Path("config/cameras.example.yaml"),
)

_NO_ALFANUM = re.compile(r"[^A-Z0-9]+")


def _sufijo_entorno(nombre: str) -> str:
    """"cam-1" -> "CAM_1", para componer CAM_CAM_1_USER."""
    return _NO_ALFANUM.sub("_", nombre.upper()).strip("_")


@dataclass(frozen=True)
class CameraConfig:
    name: str
    host: str
    enabled: bool
    model: str
    user: str
    password: str
    port: int = 554

    def url(self, stream: str = "main") -> str:
        return build_rtsp_url(
            self.model,
            self.host,
            self.user,
            self.password,
            stream=stream,
            port=self.port,
        )


@dataclass(frozen=True)
class CaptureConfig:
    width: int = 1280
    height: int = 720
    target_fps: int = 30
    rtsp_transport: str = "tcp"
    sync_tolerance_s: float = 0.017
    reconnect_after_s: float = 2.0


@dataclass(frozen=True)
class Config:
    model: str
    capture: CaptureConfig
    cameras: list[CameraConfig]

    def camera(self, name: str) -> CameraConfig:
        for cam in self.cameras:
            if cam.name == name:
                return cam
        conocidas = ", ".join(c.name for c in self.cameras) or "(ninguna)"
        raise KeyError(f"No hay una cámara llamada {name!r}. Definidas: {conocidas}")

    @property
    def enabled_cameras(self) -> list[CameraConfig]:
        return [c for c in self.cameras if c.enabled]


class ConfigNotFound(FileNotFoundError):
    """No se encontró ningún archivo de configuración."""


def find_config(path: str | Path | None = None) -> Path:
    """Devuelve la ruta de configuración a usar.

    Si `path` es None, busca en RUTAS_POR_DEFECTO desde el directorio actual.
    """
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise ConfigNotFound(f"No existe el archivo de configuración: {p}")
        return p

    for candidata in RUTAS_POR_DEFECTO:
        if candidata.exists():
            return candidata

    intentadas = ", ".join(str(p) for p in RUTAS_POR_DEFECTO)
    raise ConfigNotFound(
        "No se encontró configuración de cámaras. Copiar la plantilla:\n"
        "  copy config\\cameras.example.yaml config\\cameras.local.yaml\n"
        f"Rutas probadas: {intentadas}"
    )


def _resolver_credenciales(
    nombre: str,
    entrada: dict,
    global_user: str,
    global_password: str,
) -> tuple[str, str]:
    """Aplica la precedencia documentada en el docstring del módulo."""
    suf = _sufijo_entorno(nombre)
    usuario = (
        os.environ.get(f"CAM_{suf}_USER")
        or entrada.get("user")
        or global_user
        or ""
    )
    clave = (
        os.environ.get(f"CAM_{suf}_PASSWORD")
        or entrada.get("password")
        or global_password
        or ""
    )
    return str(usuario), str(clave)


def load_config(path: str | Path | None = None) -> Config:
    """Carga y valida la configuración de cámaras."""
    ruta = find_config(path)
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}

    modelo = datos.get("model")
    if not modelo:
        raise ValueError(f"{ruta}: falta la clave 'model'")

    credenciales = datos.get("credentials") or {}
    # El entorno gana sobre el archivo: evita dejar credenciales en disco.
    global_user = os.environ.get("CAM_USER") or credenciales.get("user") or ""
    global_password = (
        os.environ.get("CAM_PASSWORD") or credenciales.get("password") or ""
    )

    cap = datos.get("capture") or {}
    captura = CaptureConfig(
        width=int(cap.get("width", 1280)),
        height=int(cap.get("height", 720)),
        target_fps=int(cap.get("target_fps", 30)),
        rtsp_transport=str(cap.get("rtsp_transport", "tcp")),
        sync_tolerance_s=float(cap.get("sync_tolerance_s", 0.017)),
        reconnect_after_s=float(cap.get("reconnect_after_s", 2.0)),
    )

    camaras: list[CameraConfig] = []
    vistos: set[str] = set()
    for entrada in datos.get("cameras") or []:
        nombre = entrada.get("name")
        host = entrada.get("host")
        if not nombre or not host:
            raise ValueError(f"{ruta}: cada cámara necesita 'name' y 'host'")
        nombre = str(nombre)
        if nombre in vistos:
            raise ValueError(f"{ruta}: nombre de cámara duplicado: {nombre!r}")
        vistos.add(nombre)

        usuario, clave = _resolver_credenciales(
            nombre, entrada, global_user, global_password
        )
        if not usuario or not clave:
            raise ValueError(
                f"{ruta}: la cámara {nombre!r} no tiene credenciales. "
                f"Definir 'user'/'password' en su entrada, un bloque "
                f"'credentials' global, o las variables de entorno "
                f"CAM_{_sufijo_entorno(nombre)}_USER / _PASSWORD."
            )

        camaras.append(
            CameraConfig(
                name=nombre,
                host=str(host),
                enabled=bool(entrada.get("enabled", True)),
                model=str(entrada.get("model", modelo)),
                user=usuario,
                password=clave,
                port=int(entrada.get("port", 554)),
            )
        )

    return Config(model=str(modelo), capture=captura, cameras=camaras)

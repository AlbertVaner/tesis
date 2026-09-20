"""Mirar al frente antes de buscar a la persona. Sin camara.

Lo que fallo de verdad el 2026-09-18: `PositionABS` y `getStatus` no usan la
misma convencion de pan, y "ir a pan 180" mando la camara a mirar hacia atras.
Medido: pedir 180 deja la lectura en 0 y pedir 170 la deja en 9.9.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_ptz_frente.py
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from camara_env import frente_de, frente_desde_entorno, guardar_frente, leer_env  # noqa: E402
from ptz import CamaraPTZ  # noqa: E402
from ptz.cliente import pan_fisico, pan_para_posicion_abs  # noqa: E402

SIN_ARCHIVO = Path("no-existe.env")


@pytest.mark.parametrize("leido, pedido", [(0.0, 180.0), (9.9, 170.1), (180.0, 0.0),
                                           (298.9, 241.1), (354.0, 186.0)])
def test_conversion_del_pan_medida_en_la_camara(leido, pedido):
    assert pan_para_posicion_abs(leido) == pytest.approx(pedido)


class _Respuesta:
    def __init__(self, texto: str) -> None:
        self._texto = texto

    def read(self) -> bytes:
        return self._texto.encode()


class _Camara(CamaraPTZ):
    """Cliente real con la red sustituida en el `opener`: el `dry_run` y el
    armado de la peticion son los de verdad. Obedece `PositionABS` con la
    convencion medida en la camara."""

    def __init__(self, *, obedece: bool = True, **kwargs) -> None:
        super().__init__("camara.invalid", "u", "c", log=lambda _m: None, **kwargs)
        self.obedece = obedece
        self.pan, self.tilt = 0.0, 30.0
        self.pedidos: list[dict] = []
        self._opener = self

    def open(self, url: str, timeout: float = 0.0) -> _Respuesta:
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.pedidos.append(params)
        if params.get("code") == "PositionABS" and self.obedece:
            self.pan = (180.0 - float(params["arg1"])) % 360.0
            self.tilt = float(params["arg2"])
        if params.get("action") == "getStatus":
            lineas = (f"status.Postion[0]={self.pan}", f"status.Postion[1]={self.tilt}",
                      "status.Postion[2]=1.0")
            return _Respuesta(chr(10).join(lineas))
        return _Respuesta("OK")


def test_ir_a_deja_la_lectura_donde_se_pidio():
    cam = _Camara()
    cam.ir_a(180.0, 0.0)
    assert cam.posicion()[:2] == (180.0, 0.0)
    assert float(cam.pedidos[0]["arg1"]) == 0.0    # y no 180, que era mirar atras


def test_mirar_al_frente_espera_a_llegar():
    cam = _Camara()
    assert cam.mirar_al_frente((180.0, 0.0), dormir=lambda _s: None) is True


def test_si_la_camara_no_llega_se_avisa_y_no_se_lanza():
    cam = _Camara(obedece=False)
    assert cam.mirar_al_frente((180.0, 0.0), timeout_s=1.0, dormir=lambda _s: None) is False


def test_sin_frente_no_se_pide_nada():
    cam = _Camara()
    assert cam.mirar_al_frente(None) is True
    assert cam.pedidos == []


def test_en_dry_run_no_se_envia_el_movimiento():
    cam = _Camara(dry_run=True)
    assert cam.mirar_al_frente((180.0, 0.0), dormir=lambda _s: None) is True
    assert cam.pedidos == []


def test_el_frente_por_defecto_es_pan_180_no_pan_0():
    assert frente_desde_entorno({}, SIN_ARCHIVO) == (180.0, 0.0)


def test_el_frente_sale_del_entorno_y_valida_numeros():
    assert frente_desde_entorno({"CAM_FRENTE_PAN": "200", "CAM_FRENTE_TILT": "37.5"},
                                SIN_ARCHIVO) == (200.0, 37.5)
    with pytest.raises(ValueError):
        frente_desde_entorno({"CAM_FRENTE_PAN": "frente"}, SIN_ARCHIVO)


def test_guardar_frente_no_toca_el_resto_del_env(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text("# camara\nCAM_HOST=10.0.0.9\nCAM_FRENTE_PAN=180\nCAM_PASSWORD=x\n",
                       encoding="utf-8")
    guardar_frente(172.4, 35.0, archivo)
    assert leer_env(archivo) == {"CAM_HOST": "10.0.0.9", "CAM_FRENTE_PAN": "172.4",
                                 "CAM_PASSWORD": "x", "CAM_FRENTE_TILT": "35.0"}
    assert archivo.read_text(encoding="utf-8").startswith("# camara\n")


@pytest.mark.parametrize("leido, fisico", [(180.0, 0.0), (166.9, 13.1), (3.0, 177.0),
                                           (186.0, 354.0), (181.0, -1.0)])
def test_pan_fisico_cuenta_desde_el_tope(leido, fisico):
    assert pan_fisico(leido) == pytest.approx(fisico)


def test_sin_frente_la_camara_no_se_mueve_al_arrancar():
    from types import SimpleNamespace
    assert frente_de(SimpleNamespace(frente=None)) is None
    assert frente_de(SimpleNamespace(frente=[3.0, 6.0])) == (3.0, 6.0)
    with pytest.raises(SystemExit):
        frente_de(SimpleNamespace(frente=[3.0]))

"""ControlPTZ: aplicar ordenes sin bloquear el bucle de vision. Sin red.

La propiedad que importa, y la razon de que este modulo exista, es que
`pedir()` vuelva de inmediato aunque la camara tarde. Medido sobre la Amcrest
del laboratorio, una peticion HTTP cuesta ~300 ms de mediana; hacerla dentro
del bucle de vision congelaba la deteccion justo mientras el motor giraba.

Se prueba tambien que solo se aplique la ULTIMA orden pendiente: lo que
importa es como queda el motor, no la historia de ordenes. Encolarlas seria
acumular el retraso que este modulo elimina.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_ptz_control.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from ptz.cliente import ErrorPTZ, describir_error  # noqa: E402
from ptz.control import ControlPTZ  # noqa: E402
from ptz.seguidor import Orden  # noqa: E402

DERECHA = Orden("Right", 2)
IZQUIERDA = Orden("Left", 3)
PARADA = Orden("stop")


class CamaraFalsa:
    """Camara de mentira: registra lo que se le pide y no toca la red."""

    def __init__(self, *, latencia_s: float = 0.0, falla: bool = False) -> None:
        self.latencia_s = latencia_s
        self.falla = falla
        self.aplicadas: list[Orden] = []
        self.paradas = 0

    def aplicar(self, orden) -> None:
        if self.latencia_s:
            time.sleep(self.latencia_s)
        if self.falla:
            raise ErrorPTZ("camara de prueba")
        self.aplicadas.append(orden)

    def posicion(self):
        return (10.0, 20.0, 1.0)

    def parar(self) -> None:
        self.paradas += 1


def _control(camara, **kwargs) -> ControlPTZ:
    """Control sin hilo: los ciclos se disparan a mano, sin depender del reloj."""
    return ControlPTZ(camara, iniciar=False, **kwargs)


# --------------------------------------------------------------- aplicacion


def test_aplica_la_orden_pedida():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    ctrl.pedir(DERECHA)
    ctrl._ciclo(0.0)
    assert cam.aplicadas == [DERECHA]
    assert ctrl.enviadas == 1


def test_sin_orden_no_manda_nada():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    ctrl._ciclo(0.0)
    assert cam.aplicadas == []


def test_pedir_none_no_hace_nada():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    ctrl.pedir(None)
    ctrl._ciclo(0.0)
    assert cam.aplicadas == []


def test_no_reenvia_una_orden_identica():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    for t in (0.0, 0.1, 0.2):
        ctrl.pedir(DERECHA)
        ctrl._ciclo(t)
    assert cam.aplicadas == [DERECHA], "repetir la misma orden gasta 300 ms por nada"


def test_solo_se_aplica_la_ultima_orden_pendiente():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    ctrl.pedir(DERECHA)
    ctrl.pedir(IZQUIERDA)
    ctrl.pedir(PARADA)
    ctrl._ciclo(0.0)
    assert cam.aplicadas == [PARADA], (
        "lo que importa es como queda el motor, no la historia de ordenes"
    )


def test_una_orden_distinta_despues_si_se_manda():
    cam = CamaraFalsa()
    ctrl = _control(cam)
    ctrl.pedir(DERECHA)
    ctrl._ciclo(0.0)
    ctrl.pedir(PARADA)
    ctrl._ciclo(0.1)
    assert cam.aplicadas == [DERECHA, PARADA]


# ------------------------------------------------------------------ errores


def test_un_fallo_de_la_camara_no_rompe_el_bucle():
    cam = CamaraFalsa(falla=True)
    ctrl = _control(cam)
    ctrl.pedir(DERECHA)
    ctrl._ciclo(0.0)
    assert ctrl.errores == 1
    assert ctrl.enviadas == 0


# ----------------------------------------------------------------- posicion


def test_la_posicion_se_refresca_y_respeta_su_periodo():
    cam = CamaraFalsa()
    ctrl = _control(cam, periodo_posicion_s=2.0)
    ctrl._ciclo(0.0)
    assert ctrl.posicion == (10.0, 20.0, 1.0)

    ctrl.posicion = None                 # se comprueba que NO la repone aun
    ctrl._ciclo(1.0)
    assert ctrl.posicion is None
    ctrl._ciclo(2.5)
    assert ctrl.posicion == (10.0, 20.0, 1.0)


# ------------------------------------------------- la propiedad que importa


def test_pedir_no_bloquea_aunque_la_camara_tarde():
    """El bucle de vision no puede pagar los ~300 ms de una peticion HTTP."""
    cam = CamaraFalsa(latencia_s=0.30)
    with ControlPTZ(cam) as ctrl:
        t0 = time.perf_counter()
        for _ in range(5):
            ctrl.pedir(DERECHA)
        transcurrido = time.perf_counter() - t0
        assert transcurrido < 0.05, (
            f"pedir() tardo {transcurrido * 1000:.0f} ms; deberia volver al instante"
        )
        time.sleep(0.6)
        assert cam.aplicadas, "el hilo tiene que haber aplicado la orden"


def test_cerrar_detiene_el_motor():
    cam = CamaraFalsa()
    ctrl = ControlPTZ(cam)
    ctrl.pedir(DERECHA)
    time.sleep(0.2)
    ctrl.cerrar()
    assert cam.paradas >= 1, "al cerrar, el motor nunca puede quedar girando"


# ------------------------------------------------- mensajes que sirven


def _http_error(codigo: int):
    import urllib.error
    return urllib.error.HTTPError("http://x/y", codigo, "por que sea", {}, None)


def test_un_401_habla_de_credenciales_no_de_red():
    msg = describir_error(_http_error(401), "/cgi-bin/ptz.cgi", "10.0.0.5")
    assert "contrasena" in msg
    assert "Amcrest View" in msg, "hay que decir cual de las dos cuentas es"


def test_un_404_habla_del_modelo_no_de_credenciales():
    msg = describir_error(_http_error(404), "/cgi-bin/ptz.cgi", "10.0.0.5")
    assert "endpoint" in msg
    assert "contrasena" not in msg


def test_un_error_de_red_sugiere_comprobar_la_ip():
    import urllib.error
    msg = describir_error(urllib.error.URLError("timed out"), "/x", "10.0.0.5")
    assert "10.0.0.5" in msg
    assert "IP" in msg
    assert "cambia de IP" in msg, "el caso Wi-Fi -> cable es el que mas confunde"


def test_otros_errores_no_se_tragan():
    msg = describir_error(ValueError("raro"), "/x", "10.0.0.5")
    assert "ValueError" in msg


def test_el_mensaje_nunca_lleva_credenciales():
    """Las credenciales van en la cabecera Digest; que no se cuelen aqui."""
    import urllib.error
    for exc in (_http_error(401), _http_error(404),
                urllib.error.URLError("x"), ValueError("y")):
        msg = describir_error(exc, "/cgi-bin/ptz.cgi?action=getStatus", "10.0.0.5")
        assert "@" not in msg

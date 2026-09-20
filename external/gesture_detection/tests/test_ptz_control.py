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


# ------------------------------------------------------------ tope del tilt
#
# El 2026-09-18, con la camara montada de lado, el seguimiento horizontal lo
# hace el motor de tilt (-4 a 79 grados). Con el tilt en su tope inferior la
# persona a la derecha quedaba fuera del recorrido: la camara no avanzaba y
# desde la imagen era identico a una camara que no obedece.


class CamaraConTope(CamaraFalsa):
    """Camara de lado (`Rotate90=2`): derecha del cuadro = `Down` del motor."""

    MOTOR = {"Left": "Up", "Right": "Down", "Up": "Right", "Down": "Left"}

    def __init__(self, tilt: float) -> None:
        super().__init__()
        self.tilt = tilt

    def posicion(self):
        return (180.0, self.tilt, 1.0)

    def limites_tilt(self):
        return (-4.0, 79.0)

    def codigo_motor(self, codigo):
        return self.MOTOR[codigo]


def test_en_el_tope_no_se_empuja_y_se_avisa():
    camara = CamaraConTope(tilt=-6.3)
    control = _control(camara)
    control._ciclo(0.0)                       # lee la posicion
    control.pedir(Orden("Right", 1))
    control._ciclo(0.1)
    assert camara.aplicadas == []
    assert control.tope == "Right"


def test_hacia_el_otro_lado_si_se_mueve_y_el_aviso_se_quita():
    camara = CamaraConTope(tilt=-6.3)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("Right", 1))
    control._ciclo(0.1)
    control.pedir(Orden("Left", 1))
    control._ciclo(0.2)
    assert [o.codigo for o in camara.aplicadas] == ["Left"]
    assert control.tope is None


def test_lejos_del_tope_se_mueve_normal():
    camara = CamaraConTope(tilt=40.0)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("Right", 1))
    control._ciclo(0.1)
    assert [o.codigo for o in camara.aplicadas] == ["Right"]
    assert control.tope is None


def test_el_tope_superior_tambien_cuenta():
    camara = CamaraConTope(tilt=78.5)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("Left", 1))           # Left del cuadro = Up del motor
    control._ciclo(0.1)
    assert camara.aplicadas == [] and control.tope == "Left"


def test_el_eje_vertical_del_cuadro_no_tiene_tope():
    # Arriba y abajo del cuadro los mueve el pan, que da casi la vuelta entera.
    camara = CamaraConTope(tilt=-6.3)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("Down", 1))
    control._ciclo(0.1)
    assert [o.codigo for o in camara.aplicadas] == ["Down"]


def test_una_parada_nunca_se_bloquea():
    camara = CamaraConTope(tilt=-6.3)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("stop"))
    control._ciclo(0.1)
    assert [o.codigo for o in camara.aplicadas] == ["stop"]


class CamaraBocaAbajo(CamaraFalsa):
    """Colgada del techo con `Flip`: el cuadro y el motor coinciden, pero `Up`
    baja la lectura del tilt (medido: de 2.0 a -6.3)."""

    def __init__(self, tilt: float) -> None:
        super().__init__()
        self.tilt = tilt

    def posicion(self):
        return (180.0, self.tilt, 1.0)

    def limites_tilt(self):
        return (-4.0, 79.0)

    def codigo_motor(self, codigo):
        return codigo

    def sentido_tilt(self, motor):
        return {"Up": -1, "Down": 1}.get(motor, 0)


def test_boca_abajo_el_tope_inferior_bloquea_arriba_y_no_abajo():
    camara = CamaraBocaAbajo(tilt=-6.3)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden("Up", 1))
    control._ciclo(0.1)
    assert camara.aplicadas == [] and control.tope == "Up"
    control.pedir(Orden("Down", 1))
    control._ciclo(0.2)
    assert [o.codigo for o in camara.aplicadas] == ["Down"]
    assert control.tope is None


# -------------------------------------------------------------- tope del pan
#
# Medido el 2026-09-18 con la camara boca abajo: con la lectura del pan en 180
# el motor no giraba nada hacia la derecha (0 px de desplazamiento, ni a
# velocidad 3) y hacia la izquierda si. La lectura 180 es el tope mecanico:
# `fisico = 180 - leido`, y el recorrido va de 1 a 354 grados fisicos.


class CamaraEnTopeDePan(CamaraBocaAbajo):
    def __init__(self, pan: float) -> None:
        super().__init__(tilt=6.0)
        self.pan = pan

    def posicion(self):
        return (self.pan, self.tilt, 1.0)

    def limites_pan(self):
        return (1.0, 354.0)

    def sentido_pan(self, motor):
        return {"Left": 1, "Right": -1}.get(motor, 0)      # volteada: Right baja el fisico


def _pedir_en(pan: float, codigo: str):
    camara = CamaraEnTopeDePan(pan)
    control = _control(camara)
    control._ciclo(0.0)
    control.pedir(Orden(codigo, 1))
    control._ciclo(0.1)
    return camara, control


def test_con_el_pan_en_su_tope_no_se_empuja_hacia_ese_lado():
    camara, control = _pedir_en(180.0, "Right")
    assert camara.aplicadas == [] and control.tope == "Right"


def test_desde_el_tope_hacia_el_otro_lado_si_gira():
    camara, control = _pedir_en(180.0, "Left")
    assert [o.codigo for o in camara.aplicadas] == ["Left"] and control.tope is None


def test_a_mitad_de_recorrido_gira_a_los_dos_lados():
    for codigo in ("Left", "Right"):
        camara, control = _pedir_en(3.0, codigo)          # lectura 3 = fisico 177
        assert [o.codigo for o in camara.aplicadas] == [codigo]


def test_el_otro_extremo_del_pan_tambien_es_tope():
    camara, control = _pedir_en(186.0, "Left")            # lectura 186 = fisico 354
    assert camara.aplicadas == [] and control.tope == "Left"


# ------------------------------------------------- dar la vuelta por el otro lado


class CamaraQueDaLaVuelta(CamaraEnTopeDePan):
    def __init__(self, pan: float) -> None:
        super().__init__(pan)
        self.idas: list[tuple[float, float]] = []

    def ir_a(self, pan, tilt, zoom=1.0):
        self.idas.append((pan, tilt))
        self.pan = pan                           # llega al instante


def _bloquear(control, codigo: str, veces: int) -> None:
    for i in range(veces):
        control.pedir(Orden(codigo, 1))
        control._ciclo(0.1 + i)
        control.pedir(Orden("stop"))
        control._ciclo(0.2 + i)


def test_una_sola_orden_contra_el_tope_no_da_la_vuelta():
    camara = CamaraQueDaLaVuelta(180.0)
    control = _control(camara)
    control._ciclo(0.0)
    _bloquear(control, "Right", 1)
    assert camara.idas == [] and control.vueltas == 0


def test_si_la_persona_sigue_fuera_la_camara_da_la_vuelta():
    camara = CamaraQueDaLaVuelta(180.0)           # lectura 180 = tope bajo del pan
    control = _control(camara)
    control._ciclo(0.0)
    _bloquear(control, "Right", 2)
    # Sale por el otro extremo, 30 grados pasado el sector muerto: fisico 324,
    # que en lectura es 216 (36 grados a la derecha del tope).
    assert camara.idas == [(216.0, 6.0)]
    assert control.vueltas == 1 and control.tope is None and not control.dando_la_vuelta


def test_desde_el_otro_extremo_la_vuelta_es_al_reves():
    camara = CamaraQueDaLaVuelta(186.0)           # lectura 186 = fisico 354, tope alto
    control = _control(camara)
    control._ciclo(0.0)
    _bloquear(control, "Left", 2)
    assert camara.idas == [(149.0, 6.0)]          # fisico 31


def test_se_puede_desactivar():
    camara = CamaraQueDaLaVuelta(180.0)
    control = _control(camara)
    control.dar_la_vuelta = False
    control._ciclo(0.0)
    _bloquear(control, "Right", 3)
    assert camara.idas == [] and control.tope == "Right"


def test_el_tope_del_tilt_nunca_da_la_vuelta():
    camara = CamaraBocaAbajo(tilt=-6.3)
    camara.ir_a = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe girar"))
    control = _control(camara)
    control._ciclo(0.0)
    _bloquear(control, "Up", 3)
    assert control.vueltas == 0

"""Politica de seguimiento PTZ. Sin camara, sin red y sin MediaPipe.

Lo que se verifica es el comportamiento que no se puede comprobar mirando la
pantalla, porque en pantalla todo parece razonable:

* que la zona muerta impida moverse por ruido de deteccion;
* que la histeresis evite el caceo, que es el fallo caracteristico de un lazo
  que mueve la propia camara que observa;
* que la velocidad crezca con el error, que es lo que hace que el movimiento
  se sienta suave en vez de a tirones;
* que no se encadene un paso nuevo sobre una imagen que todavia no refleja el
  anterior, que es el origen de la oscilacion por latencia;
* que el motor no se quede girando si se pierde a la persona;
* que un movimiento tenga siempre un tope de duracion.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_ptz_seguidor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from ptz.seguidor import (  # noqa: E402
    Ajustes,
    HOMBROS_Y_CADERAS,
    Seguidor,
    centro_torso,
    decidir_con_gesto,
    velocidad_para,
)


def _torso(x: float, y: float, visibilidad: float = 1.0):
    """Landmarks sinteticos con el torso en `(x, y)`."""
    puntos = np.zeros((33, 3))
    vis = np.zeros(33)
    for i in HOMBROS_Y_CADERAS:
        puntos[i] = (x, y, 0.0)
        vis[i] = visibilidad
    return puntos, vis


def _codigo(orden) -> str | None:
    return None if orden is None else orden.codigo


# ------------------------------------------------------------ centro_torso


def test_centro_torso_promedia_hombros_y_caderas():
    puntos, vis = _torso(0.7, 0.4)
    assert centro_torso(puntos, vis) == (0.7, 0.4)


def test_centro_torso_ignora_landmarks_poco_visibles():
    puntos, vis = _torso(0.7, 0.4, visibilidad=0.1)
    assert centro_torso(puntos, vis) is None, (
        "con el torso ocluido es preferible no mover la camara"
    )


def test_centro_torso_sin_landmarks():
    assert centro_torso(np.empty((0, 3)), np.empty((0,))) is None


# ------------------------------------------------------------ zona muerta


def test_centrada_no_mueve():
    seg = Seguidor()
    assert seg.decidir((0.5, 0.5), 0.0) is None
    assert seg.activo is None


def test_dentro_de_la_zona_muerta_no_mueve():
    a = Ajustes()
    seg = Seguidor(a)
    apenas = 0.5 + a.arrancar_en - 0.01
    assert seg.decidir((apenas, 0.5), 0.0) is None


def test_fuera_de_la_zona_muerta_arranca_hacia_ese_lado():
    seg = Seguidor()
    assert _codigo(seg.decidir((0.8, 0.5), 0.0)) == "Right"
    assert seg.activo == "Right"

    otro = Seguidor()
    assert _codigo(otro.decidir((0.2, 0.5), 0.0)) == "Left"


# ------------------------------------------------------ velocidad suave


def test_velocidad_minima_justo_al_salir_de_la_zona_muerta():
    a = Ajustes()
    assert velocidad_para(a.arrancar_en, a.arrancar_en, a) == a.velocidad_min


def test_velocidad_maxima_en_el_borde_del_cuadro():
    a = Ajustes()
    assert velocidad_para(0.5, a.arrancar_en, a) == a.velocidad_max
    assert velocidad_para(a.error_saturacion, a.arrancar_en, a) == a.velocidad_max


def test_la_velocidad_no_decrece_con_el_error():
    a = Ajustes()
    errores = np.linspace(a.arrancar_en, 0.5, 25)
    velocidades = [velocidad_para(e, a.arrancar_en, a) for e in errores]
    assert velocidades == sorted(velocidades)
    assert min(velocidades) == a.velocidad_min
    assert max(velocidades) == a.velocidad_max


def test_el_signo_del_error_no_cambia_la_velocidad():
    a = Ajustes()
    assert velocidad_para(0.3, a.arrancar_en, a) == velocidad_para(-0.3, a.arrancar_en, a)


def test_una_persona_apenas_descentrada_se_corrige_despacio():
    a = Ajustes()
    suave = Seguidor(a).decidir((0.5 + a.arrancar_en + 0.01, 0.5), 0.0)
    brusca = Seguidor(a).decidir((0.99, 0.5), 0.0)
    assert suave.velocidad == a.velocidad_min
    assert brusca.velocidad == a.velocidad_max
    assert suave.velocidad < brusca.velocidad


# -------------------------------------------------------------- histeresis


def test_sigue_moviendose_hasta_el_umbral_de_parada():
    a = Ajustes()
    seg = Seguidor(a)
    seg.decidir((0.8, 0.5), 0.0)

    # Ya dentro de la zona de arranque, pero aun no centrada: no para.
    intermedio = 0.5 + (a.arrancar_en + a.parar_en) / 2
    assert seg.decidir((intermedio, 0.5), 0.05) is None
    assert seg.activo == "Right"

    # Suficientemente centrada: para.
    assert _codigo(seg.decidir((0.5 + a.parar_en / 2, 0.5), 0.10)) == "stop"
    assert seg.activo is None


def test_enfriamiento_impide_rearrancar_de_inmediato():
    a = Ajustes()
    seg = Seguidor(a)
    seg.decidir((0.8, 0.5), 0.0)
    seg.decidir((0.5, 0.5), 0.1)          # para en t=0.1
    assert seg.activo is None

    # Descentrada otra vez, pero todavia en enfriamiento.
    assert seg.decidir((0.9, 0.5), 0.1 + a.enfriamiento_s / 2) is None
    # Pasado el enfriamiento, si.
    assert _codigo(seg.decidir((0.9, 0.5), 0.1 + a.enfriamiento_s + 0.01)) == "Right"


# ------------------------------------------------------------- seguridad


def test_pierde_a_la_persona_y_para():
    a = Ajustes()
    seg = Seguidor(a)
    seg.decidir((0.9, 0.5), 0.0)
    assert seg.decidir(None, 0.1) is None, "una perdida breve no deberia cortar"
    assert _codigo(seg.decidir(None, a.paciencia_s + 0.01)) == "stop"


def test_el_movimiento_continuo_tiene_tope_de_duracion():
    a = Ajustes(pulso_s=0.0)
    seg = Seguidor(a)
    seg.decidir((0.99, 0.5), 0.0)
    # Sigue descentradisima, pero el movimiento ya duro demasiado.
    assert _codigo(seg.decidir((0.99, 0.5), a.pulso_max_s + 0.01)) == "stop"


# ------------------------------------------------------- pasos acotados


def test_el_paso_termina_al_cumplirse_el_pulso():
    """El sobrepaso se acota limitando cuanto dura cada movimiento."""
    a = Ajustes()
    seg = Seguidor(a)
    seg.decidir((0.99, 0.5), 0.0)
    assert seg.decidir((0.99, 0.5), a.pulso_s / 2) is None
    # Sigue igual de descentrada, pero el paso se acabo: para y reevalua.
    assert _codigo(seg.decidir((0.99, 0.5), a.pulso_s + 0.001)) == "stop"


def test_con_pulso_cero_el_movimiento_es_continuo():
    a = Ajustes(pulso_s=0.0)
    seg = Seguidor(a)
    seg.decidir((0.99, 0.5), 0.0)
    assert seg.decidir((0.99, 0.5), 0.5) is None, (
        "sin pulso solo debe parar al llegar al centro"
    )
    assert _codigo(seg.decidir((0.5, 0.5), 0.6)) == "stop"


def test_la_espera_entre_pasos_supera_la_duracion_del_paso():
    """Si se reevalua antes de que la imagen refleje el paso, se sobrepasa."""
    a = Ajustes()
    assert a.enfriamiento_s > a.pulso_s


def test_un_error_grande_se_cubre_en_varios_pasos():
    a = Ajustes()
    seg = Seguidor(a)
    ahora = 0.0
    pasos = 0
    # La persona no se mueve y la camara tampoco corrige (peor caso): el
    # seguidor debe insistir a pasos, no quedarse girando de una vez.
    for _ in range(400):
        orden = seg.decidir((0.95, 0.5), ahora)
        if orden is not None and not orden.es_parada:
            pasos += 1
        ahora += 0.05
    assert pasos >= 5, f"solo dio {pasos} pasos en 20 s"
    # Con la persona clavada, el error nunca cambia y cada ciclo lo cierra el
    # tope de la espera por confirmacion, no el enfriamiento.
    duracion_ciclo = a.pulso_s + a.espera_max_s
    assert pasos <= 20 / duracion_ciclo + 1, "esta ignorando la espera por confirmacion"


# ------------------------------------------- espera por confirmacion visual


def _tras_un_paso(a: Ajustes, centro_al_parar=(0.9, 0.5)):
    """Seguidor que acaba de dar un paso y paro en `centro_al_parar`, en t=0."""
    seg = Seguidor(a)
    seg.decidir((0.9, 0.5), -1.0)
    seg.decidir(centro_al_parar, 0.0)     # el paso termina y se guarda el centro
    assert seg.activo is None
    return seg


def test_no_encadena_un_paso_si_la_imagen_no_ha_cambiado():
    """El origen de la oscilacion: decidir sobre una imagen anterior al paso."""
    a = Ajustes()
    seg = _tras_un_paso(a)
    # Pasado el enfriamiento, pero la persona sigue exactamente donde estaba:
    # el paso anterior aun no se ve.
    assert seg.decidir((0.9, 0.5), a.enfriamiento_s + 0.01) is None
    assert seg.decidir((0.9, 0.5), a.enfriamiento_s + 0.20) is None


def test_un_cambio_observado_desbloquea_el_siguiente_paso():
    a = Ajustes()
    seg = _tras_un_paso(a)
    movida = (0.9 - a.cambio_minimo * 2, 0.5)
    assert _codigo(seg.decidir(movida, a.enfriamiento_s + 0.01)) == "Right"


def test_un_cambio_por_debajo_del_umbral_es_ruido_y_no_cuenta():
    a = Ajustes()
    seg = _tras_un_paso(a)
    apenas = (0.9 - a.cambio_minimo / 2, 0.5)
    assert seg.decidir(apenas, a.enfriamiento_s + 0.01) is None


def test_la_espera_por_confirmacion_tiene_tope():
    """Si la persona camina al ritmo de la camara, el error no cambia nunca."""
    a = Ajustes()
    seg = _tras_un_paso(a)
    assert seg.decidir((0.9, 0.5), a.espera_max_s - 0.01) is None
    assert _codigo(seg.decidir((0.9, 0.5), a.espera_max_s + 0.01)) == "Right"


def test_la_confirmacion_mira_el_eje_del_paso():
    """Un paso horizontal solo se da por visto si cambio la coordenada x."""
    a = Ajustes()
    seg = _tras_un_paso(a)
    # La y cambia muchisimo, la x no: el paso horizontal sigue sin verse.
    assert seg.decidir((0.9, 0.95), a.enfriamiento_s + 0.01) is None


# --------------------------------------- el gesto manda sobre el encuadre


# Descentrada lo justo para querer moverse, pero sin llegar a `error_critico`:
# es el caso donde el gesto tiene que ganar.
CASI = 0.5 + 0.20


def test_un_gesto_en_curso_detiene_la_camara():
    """Girar durante un gesto contamina el gesto: el encuadre puede esperar."""
    seg = Seguidor()
    seg.decidir((CASI, 0.5), 0.0)
    assert seg.activo == "Right"
    orden = decidir_con_gesto(seg, (CASI, 0.5), 0.05, gesto_en_curso=True)
    assert orden is not None and orden.es_parada
    assert seg.activo is None


def test_con_un_gesto_en_curso_no_se_arranca_ningun_movimiento():
    seg = Seguidor()
    assert decidir_con_gesto(seg, (CASI, 0.5), 0.0, gesto_en_curso=True) is None
    assert seg.activo is None


def test_sin_gesto_la_politica_es_la_de_siempre():
    seg = Seguidor()
    orden = decidir_con_gesto(seg, (0.9, 0.5), 0.0, gesto_en_curso=False)
    assert orden is not None and orden.codigo == "Right"


def test_al_acabar_el_gesto_el_seguimiento_se_reanuda():
    a = Ajustes()
    seg = Seguidor(a)
    decidir_con_gesto(seg, (CASI, 0.5), 0.0, gesto_en_curso=True)
    orden = decidir_con_gesto(seg, (CASI, 0.5), a.espera_max_s + 0.1,
                              gesto_en_curso=False)
    assert orden is not None and orden.codigo == "Right"


# ------------------------------------------- los dos escapes de la prioridad


def test_si_esta_a_punto_de_salirse_el_encuadre_gana():
    """Un gesto que se sale del cuadro no se puede clasificar igualmente."""
    a = Ajustes()
    seg = Seguidor(a)
    lejos = 0.5 + a.error_critico + 0.02
    orden = decidir_con_gesto(seg, (lejos, 0.5), 0.0, gesto_en_curso=True)
    assert orden is not None and orden.codigo == "Right", (
        "proteger el gesto a costa de perder a la persona no protege nada"
    )


def test_un_segmento_largo_deja_de_retener_la_camara():
    """`en_segmento` significa 'se mueve', no 'hace un gesto'. Caminar lo abre."""
    a = Ajustes()
    seg = Seguidor(a)
    # Dentro del umbral critico: al principio el gesto manda.
    assert decidir_con_gesto(seg, (CASI, 0.5), 0.0, gesto_en_curso=True) is None
    assert decidir_con_gesto(seg, (CASI, 0.5), a.bloqueo_max_s - 0.1,
                             gesto_en_curso=True) is None
    # Pasado el tope, lo que hay abierto es locomocion: se sigue.
    orden = decidir_con_gesto(seg, (CASI, 0.5), a.bloqueo_max_s + 0.1,
                              gesto_en_curso=True)
    assert orden is not None and orden.codigo == "Right"


def test_el_tope_se_reinicia_al_cerrar_el_segmento():
    a = Ajustes()
    seg = Seguidor(a)
    decidir_con_gesto(seg, (CASI, 0.5), 0.0, gesto_en_curso=True)
    decidir_con_gesto(seg, (0.5, 0.5), 1.0, gesto_en_curso=False)   # cierra
    # Un gesto nuevo vuelve a tener su cupo entero.
    assert decidir_con_gesto(seg, (CASI, 0.5), a.bloqueo_max_s + 1.5,
                             gesto_en_curso=True) is None


def test_sin_persona_en_cuadro_un_gesto_no_deja_la_camara_girando():
    seg = Seguidor()
    seg.decidir((0.9, 0.5), 0.0)
    orden = decidir_con_gesto(seg, None, 0.05, gesto_en_curso=True)
    assert orden is not None and orden.es_parada


# ----------------------------------------------- frames aprovechables


def test_en_movimiento_mientras_el_motor_gira():
    seg = Seguidor()
    assert seg.en_movimiento(0.0) is False
    seg.decidir((0.9, 0.5), 0.0)
    assert seg.en_movimiento(0.05) is True


def test_sigue_en_movimiento_durante_el_enfriamiento():
    """La orden de parar tarda en llegar: el motor no se detiene al decidirlo."""
    a = Ajustes()
    seg = Seguidor(a)
    seg.decidir((0.9, 0.5), 0.0)
    seg.decidir((0.5, 0.5), 0.1)                  # se decide parar
    assert seg.activo is None
    assert seg.en_movimiento(0.1 + a.enfriamiento_s / 2) is True
    assert seg.en_movimiento(0.1 + a.enfriamiento_s + 0.01) is False


def test_detener_es_incondicional_y_idempotente():
    seg = Seguidor()
    seg.decidir((0.9, 0.5), 0.0)
    assert _codigo(seg.detener(1.0)) == "stop"
    assert seg.detener(1.0) is None


# ------------------------------------------------------------------- tilt


def test_tilt_se_puede_desactivar():
    seg = Seguidor(Ajustes(seguir_tilt=False))
    assert seg.decidir((0.5, 0.95), 0.0) is None


def test_tilt_sigue_en_vertical_cuando_esta_activo():
    seg = Seguidor(Ajustes(seguir_tilt=True))
    assert _codigo(seg.decidir((0.5, 0.95), 0.0)) == "Down"

    otro = Seguidor(Ajustes(seguir_tilt=True))
    assert _codigo(otro.decidir((0.5, 0.05), 0.0)) == "Up"


def test_la_zona_muerta_del_tilt_es_propia():
    # Con la de fabrica (0.20) un torso a 0.68 no inclina; igualada al pan, si.
    assert Seguidor().decidir((0.5, 0.68), 0.0) is None
    seg = Seguidor(Ajustes(arrancar_en_tilt=0.16, parar_en_tilt=0.08))
    assert _codigo(seg.decidir((0.5, 0.68), 0.0)) == "Down"


def test_el_objetivo_vertical_desplaza_el_centro():
    # Torso centrado en el cuadro pero objetivo mas abajo: para que el torso
    # baje en la imagen la camara tiene que inclinarse hacia arriba.
    seg = Seguidor(Ajustes(objetivo_y=0.75, arrancar_en_tilt=0.16, parar_en_tilt=0.08))
    assert _codigo(seg.decidir((0.5, 0.5), 0.0)) == "Up"
    # Y en el objetivo no se mueve, aunque este lejos del centro geometrico.
    quieto = Seguidor(Ajustes(objetivo_y=0.75, arrancar_en_tilt=0.16, parar_en_tilt=0.08))
    assert quieto.decidir((0.5, 0.75), 0.0) is None
    # Se para al llegar al objetivo, no al centro.
    seg.decidir((0.5, 0.5), 0.0)
    assert _codigo(seg.decidir((0.5, 0.72), 0.05)) == "stop"


def test_el_pan_tiene_prioridad_sobre_el_tilt():
    seg = Seguidor()
    assert _codigo(seg.decidir((0.95, 0.95), 0.0)) == "Right", (
        "corregir las dos cosas a la vez marea la imagen"
    )

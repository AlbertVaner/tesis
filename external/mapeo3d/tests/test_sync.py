"""Emparejamiento temporal de varias cámaras, sin cámaras.

`MultiCameraSync` sólo necesita objetos con `.name` y `.read()`, así que se
prueba entero con un doble que entrega marcas de tiempo fabricadas. Eso permite
reproducir exactamente lo que en el laboratorio es difícil de provocar a
voluntad: una cámara que va a la mitad de fps, una que se cae a mitad de
sesión, y un desfase constante.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from mapeo3d.capture import MultiCameraSync  # noqa: E402


class RelojFalso:
    """Reloj virtual que avanza una vez por vuelta completa de sondeo.

    Sin esto los dobles entregarían toda su lista de golpe, que es algo que
    `CameraStream` no hace nunca: el tiempo tiene que correr entre lecturas
    para que los frames «lleguen» en orden temporal, como en la realidad.
    """

    def __init__(self, paso: float = 1 / 480):
        self.t = 0.0
        self.paso = paso
        self.n_streams = 0
        self._lecturas = 0

    def tick(self) -> None:
        self._lecturas += 1
        if self.n_streams and self._lecturas % self.n_streams == 0:
            self.t += self.paso


class StreamFalso:
    """Doble de `CameraStream`: devuelve el último frame ya «llegado».

    Reproduce el contrato que importa: **no hay cola**. Si el consumidor se
    atrasa, los frames intermedios se pierden, igual que en el hilo lector
    real. `read()` devuelve `None` si no hay nada nuevo.
    """

    def __init__(self, name: str, tiempos, reloj: RelojFalso):
        self.name = name
        self._tiempos = list(tiempos)
        self._i = 0
        self._reloj = reloj
        self.entregados = 0

    def read(self):
        self._reloj.tick()
        llegado = None
        while self._i < len(self._tiempos) and self._tiempos[self._i] <= self._reloj.t:
            llegado = self._tiempos[self._i]
            self._i += 1
        if llegado is None:
            return None
        self.entregados += 1
        # El "frame" es su propia marca de tiempo: así una prueba puede
        # comprobar que se emparejó el frame correcto y no sólo que hubo uno.
        return (f"{self.name}@{llegado:.4f}", llegado)


def escenario(specs, paso: float = 1 / 480):
    """Construye streams que comparten reloj.

    `specs` es una lista de `(nombre, tiempos)`.
    """
    reloj = RelojFalso(paso)
    streams = [StreamFalso(n, t, reloj) for n, t in specs]
    reloj.n_streams = len(streams)
    return streams


def tiempos(fps, n, offset=0.0):
    return [offset + i / fps for i in range(n)]


def drenar(sync, vueltas: int = 20000):
    """Consume conjuntos sin dormir: el reloj es virtual, no real."""
    salida = []
    for _ in range(vueltas):
        c = sync.next(timeout_s=0.0)
        if c is not None:
            salida.append(c)
    return salida


# ------------------------------------------------------------- lo básico


def test_dos_camaras_en_fase_emparejan_todo():
    a, b = escenario([("cam1", tiempos(30, 20)), ("cam2", tiempos(30, 20))])
    sync = MultiCameraSync([a, b])

    conjuntos = drenar(sync)
    assert len(conjuntos) >= 18
    for c in conjuntos:
        assert c.n_vistas == 2
        assert c.desfase_max_s == pytest.approx(0.0, abs=1e-9)


def test_empareja_el_frame_mas_cercano_y_no_el_ultimo():
    """El vecino más cercano puede ser el frame ANTERIOR al último.

    Es la razón de que el buffer viva en el sincronizador y no en
    `CameraStream`, que por diseño sólo guarda el último frame.
    """
    a, b = escenario([("cam1", [0.100]), ("cam2", [0.095, 0.180])])
    sync = MultiCameraSync([a, b], tolerancia_s=0.017)

    conjuntos = drenar(sync, vueltas=100)
    assert conjuntos, "no llegó a emparejar nada"
    c = conjuntos[0]
    assert c.n_vistas == 2
    assert c["cam2"].frame == "cam2@0.0950", "emparejó el último, no el cercano"
    assert c["cam2"].desfase_ms == pytest.approx(-5.0, abs=0.01)


def test_un_desfase_dentro_de_tolerancia_participa():
    a, b = escenario([
        ("cam1", tiempos(30, 15)),
        ("cam2", tiempos(30, 15, offset=0.010)),   # 10 ms < 17 ms
    ])
    sync = MultiCameraSync([a, b], tolerancia_s=0.017)

    conjuntos = drenar(sync)
    assert conjuntos
    assert all(c.n_vistas == 2 for c in conjuntos)


def test_una_camara_a_otra_tasa_queda_fuera_a_ratos():
    """La tolerancia rechaza a las que van a OTRA TASA, no a las desfasadas.

    Ver `test_un_sesgo_constante_no_lo_detecta_la_tolerancia`: con la misma
    tasa, ningún desfase queda nunca fuera. Lo que sí queda fuera es una cámara
    cuyos frames caen en instantes que no coinciden con los de las demás.
    """
    a, b, c = escenario([
        ("cam1", tiempos(30, 30)),
        ("cam2", tiempos(30, 30)),
        ("cam3", tiempos(7, 8)),              # tasa muy distinta
    ])
    sync = MultiCameraSync([a, b, c], tolerancia_s=0.005)

    conjuntos = drenar(sync)
    assert conjuntos
    assert any("cam3" in x.descartadas for x in conjuntos)
    assert any("cam3" not in x for x in conjuntos)


def test_un_sesgo_constante_no_lo_detecta_la_tolerancia():
    """El fallo silencioso que obliga a medir el sesgo aparte.

    Con la misma tasa y periodo T, la distancia al vecino más cercano nunca
    supera T/2 por grande que sea el sesgo. Media cámara de segundo de retraso
    se empareja con desfase aparente CERO. Por eso existe `sesgos`.
    """
    a, b = escenario([
        ("cam1", tiempos(30, 40)),
        ("cam2", tiempos(30, 40, offset=0.500)),   # medio segundo tarde
    ])
    sync = MultiCameraSync([a, b], tolerancia_s=0.017)

    conjuntos = drenar(sync)
    assert conjuntos
    # Entra igualmente, y encima diciendo que va perfectamente sincronizada.
    assert all(c.n_vistas == 2 for c in conjuntos)
    assert sync.stats.desfase_max_ms < 1.0


def test_el_sesgo_declarado_se_compensa():
    """Con el sesgo medido y declarado, se empareja el frame correcto.

    Se usa un sesgo realista de 40 ms: uno de 500 ms es incompatible con
    tiempo real de todos modos, porque obligaría a esperar medio segundo a
    esa cámara (y `espera_maxima_s` la declararía rezagada, con razón).
    """
    a, b = escenario([
        ("cam1", tiempos(30, 40)),
        ("cam2", tiempos(30, 40, offset=0.040)),
    ])
    sync = MultiCameraSync([a, b], tolerancia_s=0.017,
                           sesgos={"cam2": 0.040})

    conjuntos = drenar(sync)
    assert conjuntos
    for c in conjuntos:
        if "cam2" in c:
            # El instante corregido coincide con el de cam1...
            assert c["cam2"].timestamp == pytest.approx(c.t_ref, abs=1e-9)
            # ...y la marca de llegada cruda sigue disponible para auditar.
            assert c["cam2"].timestamp_llegada == pytest.approx(
                c["cam2"].timestamp + 0.040, abs=1e-9
            )


def test_un_sesgo_para_una_camara_desconocida_falla():
    streams = escenario([("cam1", tiempos(30, 5)), ("cam2", tiempos(30, 5))])
    with pytest.raises(ValueError, match="no están en streams"):
        MultiCameraSync(streams, sesgos={"cam9": 0.1})


# --------------------------------------------------------- seis cámaras


def test_seis_camaras_con_jitter_realista():
    """El caso del montaje real: seis cámaras libres, con jitter de red."""
    import random

    rng = random.Random(4)
    streams = escenario([
        (f"cam{i + 1}", [j / 30.0 + rng.gauss(0.0, 0.002) for j in range(40)])
        for i in range(6)
    ])
    sync = MultiCameraSync(streams, tolerancia_s=0.017)

    conjuntos = drenar(sync)
    assert len(conjuntos) >= 35
    # Con jitter de 2 ms las seis deberían entrar casi siempre.
    completos = sum(1 for c in conjuntos if c.n_vistas == 6)
    assert completos / len(conjuntos) > 0.9
    assert sync.stats.desfase_max_ms < 17.0


def test_una_camara_a_la_mitad_de_fps_participa_menos():
    """El síntoma de una Tapo que baja el frame rate por poca luz."""
    specs = [(f"cam{i + 1}", tiempos(30, 60)) for i in range(5)]
    specs.append(("cam6", tiempos(15, 30)))
    sync = MultiCameraSync(escenario(specs), tolerancia_s=0.017)

    drenar(sync)
    st = sync.stats
    assert st.participaciones["cam6"] < st.participaciones["cam1"]
    assert st.participaciones["cam6"] > 0
    # Y queda registrado dónde mirar, que es para lo que existen las stats.
    assert "cam6" in st.resumen()


def test_una_camara_caida_no_bloquea_a_las_demas():
    """Una cámara muerta degrada a N-1 vistas; no detiene la sesión."""
    specs = [(f"cam{i + 1}", tiempos(30, 40)) for i in range(5)]
    specs.append(("cam6", tiempos(30, 5)))     # se cae tras 5 frames
    sync = MultiCameraSync(escenario(specs), tolerancia_s=0.017)

    conjuntos = drenar(sync)
    # Se pierde una pausa de `espera_maxima_s` mientras se decide que está
    # caída —a 30 fps, unos 7 conjuntos de 40— y después continúa con cinco.
    assert len(conjuntos) >= 30, "la cámara caída frenó el emparejamiento"
    assert conjuntos[-1].n_vistas == 5
    assert "cam6" not in conjuntos[-1]


def test_la_pausa_al_caerse_una_camara_dura_lo_declarado():
    """El costo de detectar la caída es `espera_maxima_s`, redondeado al frame.

    Es el precio a pagar por no descartar una cámara con un hipo pasajero.
    Bajar `espera_maxima_s` acorta la pausa y hace el sistema más nervioso.
    """
    T = 1 / 30
    specs = [(f"cam{i + 1}", tiempos(30, 40)) for i in range(2)]
    specs.append(("cam3", tiempos(30, 5)))
    sync = MultiCameraSync(escenario(specs), espera_maxima_s=0.10)

    ts = [c.t_ref for c in drenar(sync)]
    saltos = [b - a for a, b in zip(ts, ts[1:])]
    assert 0.10 <= max(saltos) <= 0.10 + 2 * T


def test_la_camara_rezagada_no_fija_la_referencia():
    """Si la referencia la marcase la más atrasada, todo iría a su ritmo."""
    streams = escenario([
        ("cam1", tiempos(30, 30, offset=1.0)),
        ("cam2", tiempos(30, 30, offset=1.0)),
        ("cam3", tiempos(30, 3)),               # se quedó al principio
    ])
    sync = MultiCameraSync(streams, espera_maxima_s=0.25)

    conjuntos = drenar(sync)
    assert conjuntos, "la referencia se fue con la cámara rezagada"
    assert conjuntos[-1].t_ref >= 1.0
    assert "cam3" not in conjuntos[-1]


# ------------------------------------------------------------- garantías


def test_nunca_repite_el_mismo_instante():
    streams = escenario([(f"cam{i + 1}", tiempos(30, 25)) for i in range(3)])
    sync = MultiCameraSync(streams)
    ts = [c.t_ref for c in drenar(sync)]
    assert ts == sorted(ts)
    assert len(set(ts)) == len(ts)


def test_sin_frames_devuelve_none_y_no_cuelga():
    streams = escenario([("cam1", []), ("cam2", [])])
    sync = MultiCameraSync(streams)
    assert sync.next(timeout_s=0.02) is None
    assert sync.stats.conjuntos == 0


def test_un_conjunto_con_muy_pocas_vistas_se_descarta():
    streams = escenario([
        ("cam1", tiempos(30, 10)),
        ("cam2", tiempos(30, 10, offset=0.5)),     # nunca coincide
    ])
    sync = MultiCameraSync(streams, tolerancia_s=0.017, min_vistas=2)

    assert drenar(sync) == []
    assert sync.stats.conjuntos == 0
    assert sync.stats.conjuntos_descartados > 0


def test_los_nombres_duplicados_fallan_al_construir():
    streams = escenario([("cam1", tiempos(30, 3)), ("cam1", tiempos(30, 3))])
    with pytest.raises(ValueError, match="duplicados"):
        MultiCameraSync(streams)


def test_sin_streams_falla_al_construir():
    with pytest.raises(ValueError):
        MultiCameraSync([])


def test_las_stats_cuadran_con_lo_emparejado():
    streams = escenario([(f"cam{i + 1}", tiempos(30, 20)) for i in range(4)])
    sync = MultiCameraSync(streams)
    conjuntos = drenar(sync)

    st = sync.stats
    assert st.conjuntos == len(conjuntos)
    assert sum(st.participaciones.values()) == sum(c.n_vistas for c in conjuntos)
    assert st.desfase_mediano_ms <= st.desfase_max_ms

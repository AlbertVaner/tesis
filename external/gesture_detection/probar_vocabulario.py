"""Probador del vocabulario completo: dos modos excluyentes y un paro. Sin dron.

Junta en un solo bucle de camara todo lo que la vision produce y le pone
delante un **supervisor simulado**: un dron imaginario con estado (modo de
control, en el aire, comportamiento, velocidad) que reacciona a los gestos
como lo haria el controlador real. Sirve para ver, antes de volar, si el
vocabulario se entiende como una secuencia y no gesto a gesto.

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\probar_vocabulario.py
    python .\\external\\gesture_detection\\probar_vocabulario.py --paro pecho
    python .\\external\\gesture_detection\\probar_vocabulario.py --estado-estatico
    python .\\external\\gesture_detection\\probar_vocabulario.py --video grabacion.mp4
    python .\\external\\gesture_detection\\probar_vocabulario.py --guardar-segmentos --persona adrian
    python .\\external\\gesture_detection\\probar_vocabulario.py --solo-dinamicos

Dos modos, y el aplauso conmuta entre ellos
-------------------------------------------
Probado en vivo con los tres canales activos a la vez, los estaticos y los
dinamicos se pisan, y ABAJO es el peor caso: un brazo abajo y al frente es
justo por donde pasan los brazos al empezar y al terminar cualquier gesto
dinamico. Por eso los dos canales **no conviven**:

    MODO DINAMICO (al arrancar)    senalero, ven_aca, arco, circulo
    MODO ESTATICO                  ARRIBA, ABAJO, ADELANTE, ATRAS, IZQUIERDA, DERECHA

El aplauso cambia de modo en las dos direcciones. Es el unico gesto dinamico
que se escucha en modo estatico, y cambiar de modo deja al dron en hover.

El paro (X sobre la cabeza, 1 s) es una regla estatica aparte y funciona
**siempre**, en los dos modos.

Los tres gestos de estado de `body_3d_rules` (DESPEGAR con las dos manos
sobre los hombros, ATERRIZAR en cruz, STOP con las manos juntas) quedan
desactivados por defecto: el senalero y la X los sustituyen. `--estado-estatico`
los activa en modo estatico, para compararlos.

Que hace el supervisor simulado
-------------------------------
    aplaudir     cambia de modo (dinamico <-> estatico); hover
    senalero     despega si esta en el suelo, aterriza si esta en el aire
    ven_aca      SEGUIR al marker                 (en el aire)
    arco         ALEJARSE del marker              (en el aire)
    circulo      ORBITAR el marker                (en el aire)
    direccion    velocidad manual, MANUAL         (modo estatico, en el aire)
    PARO         aterrizaje inmediato, vuelve a modo dinamico. Siempre.

Un gesto que llega en el modo que no le corresponde se muestra como ignorado
y con el motivo: es la parte del vocabulario que no se ve en la matriz de
confusion.

Teclas: `q` salir, `r` reiniciar todo, `d` detalle, `espacio` pausa.

Modo `--solo-dinamicos` (antes `detectar_gestos_3d.py`)
------------------------------------------------------
Solo el canal dinamico, sin paro, sin estaticos y sin supervisor: cada
segmento cerrado se clasifica contra el banco y se anota como `detectado`.
El banco por defecto pasa a ser `models/plantillas_dinamicas.npz` (el que
construye `construir_plantillas.py` sin argumentos) y el CSV va a
`results/data/gestos_dinamicos/`. Sirve para ajustar el banco y los umbrales
de arranque de `recognition/dinamicos.py` viendo la barra de rapidez.

Que esperar de ese modo: el gesto se reconoce **al terminarlo**, no mientras
se hace (un aplauso tarda unos 2.4 s). Medido sobre 102 tomas de 10 personas,
dejando fuera a cada persona: los tres gestos bien clasificados 69 / 72;
movimientos ajenos rechazados 16 / 30. Ese segundo numero es la limitacion
real: es un clasificador con rechazo parcial, no un detector de "hay gesto o
no". Los falsos positivos son casi siempre `aplaudir`, porque cualquier
movimiento de las dos manos hacia el pecho se le parece (aplausos reales a
distancia 0.259, confusiones a 0.286, y se solapan). Ningun umbral lo
arregla: exigir margen cuesta 22 de 72 gestos buenos y votar entre plantillas
empeora (13 fugas pasan a 19). Lo que si lo arregla es material: con
`--guardar-segmentos` cada segmento queda grabado; se borran los correctos y
el resto se suma a la clase de rechazo con `construir_plantillas.py
--rechazo-extra`. El detector aprende a rechazar de sus propios errores.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from contracts import GESTOS_DE_ESTADO, Gesture, VelocityIntent  # noqa: E402
from dataset.storage import Toma, guardar  # noqa: E402
from pose.detector import PoseDetector  # noqa: E402
from pose.normalize import N_LANDMARKS, body_frame, landmarks_to_array  # noqa: E402
from recognition.body_3d_rules import (  # noqa: E402
    CONO_DEG,
    VELOCIDADES,
    Body3DRecognizer,
    diagnostico,
)
from recognition.dinamicos import (  # noqa: E402
    ENTRADA_RAPIDEZ,
    BancoDinamico,
    ReconocedorDinamico,
)
from recognition.paro_estatico import INSTRUCCION, POSTURAS, ReglaParo  # noqa: E402
from utils import calculate_fps  # noqa: E402
from visualization.pose_overlay import draw_pose  # noqa: E402

VENTANA = "Vocabulario completo - prueba sin dron"
ALTO_VIDEO = 720
ANCHO_PANEL = 440
PIE_ALTO = 34

FONDO = (24, 24, 28)
BLANCO = (238, 238, 242)
GRIS = (150, 150, 155)
VERDE = (120, 220, 140)
ROJO = (90, 90, 240)
AMBAR = (80, 200, 255)

#: Segundos que la ultima deteccion dinamica se queda en pantalla.
MOSTRAR_S = 2.5

#: Tras soltar el paro, segundos en que se sigue descartando el canal
#: dinamico: bajar los brazos es un movimiento y cerraria un segmento.
DESCARTE_TRAS_PARO_S = 1.0

#: Gestos estaticos que son navegacion continua.
NAVEGACION = frozenset(VELOCIDADES)

#: Comportamiento del dron simulado que pide cada gesto dinamico.
MODOS_DINAMICOS = {"ven_aca": "SEGUIR", "arco": "ALEJARSE", "circulo": "ORBITAR"}

DINAMICO, ESTATICO = "dinamico", "estatico"

#: Banco y carpeta de resultados de cada modo de ejecucion.
BANCO_VOCABULARIO = "plantillas_vocabulario.npz"
BANCO_DINAMICO = "plantillas_dinamicas.npz"
CARPETA_VOCABULARIO = "vocabulario"
CARPETA_DINAMICOS = "gestos_dinamicos"


# ------------------------------------------------------------ supervisor


@dataclass
class Simulador:
    """Un dron imaginario que responde al vocabulario como lo haria el real."""

    control: str = DINAMICO          #: DINAMICO o ESTATICO; el aplauso conmuta
    en_aire: bool = False
    comportamiento: str = "hover"    #: hover, SEGUIR, ALEJARSE, ORBITAR, MANUAL
    velocidad: VelocityIntent = field(default_factory=VelocityIntent)
    paro_activo: bool = False

    def reset(self) -> None:
        self.control = DINAMICO
        self.en_aire = self.paro_activo = False
        self._hover()

    # ---- eventos

    def gesto(self, nombre: str) -> tuple[str, str]:
        """Gesto dinamico o de estado. `(accion, motivo)`; motivo vacio si se ejecuto."""
        if self.paro_activo:
            return "ignorado", "paro activo"
        if nombre == "aplaudir":
            self.control = ESTATICO if self.control == DINAMICO else DINAMICO
            self._hover()
            return f"MODO {self.control.upper()}", ""
        if nombre in ("senalero", *MODOS_DINAMICOS):
            if self.control != DINAMICO:
                return "ignorado", "modo estatico (aplaudir para cambiar)"
            if nombre == "senalero":
                return self._despegar() if not self.en_aire else self._aterrizar()
            if not self.en_aire:
                return "ignorado", "en el suelo (senalero primero)"
            self._hover()
            self.comportamiento = MODOS_DINAMICOS[nombre]
            return self.comportamiento, ""
        if nombre in ("DESPEGAR", "ATERRIZAR", "STOP"):
            if self.control != ESTATICO:
                return "ignorado", "modo dinamico (aplaudir para cambiar)"
            if nombre == "DESPEGAR":
                return self._despegar() if not self.en_aire else ("ignorado", "ya en el aire")
            if nombre == "ATERRIZAR":
                return self._aterrizar() if self.en_aire else ("ignorado", "ya en el suelo")
            self._hover()
            return "HOVER", ""
        return "ignorado", f"gesto sin comando: {nombre}"

    def navegar(self, nombre: str, velocidad: VelocityIntent) -> tuple[str, str]:
        """Canal continuo. Se llama cada frame con la direccion confirmada."""
        if self.paro_activo:
            return "ignorado", "paro activo"
        if self.control != ESTATICO:
            return "ignorado", "modo dinamico (aplaudir para cambiar)"
        if not self.en_aire:
            return "ignorado", "en el suelo"
        self.comportamiento = "MANUAL"
        self.velocidad = velocidad
        return "MANUAL", ""

    def soltar_navegacion(self) -> None:
        """Sin direccion confirmada, la velocidad manual vuelve a cero."""
        if self.comportamiento == "MANUAL":
            self.velocidad = VelocityIntent()

    def paro(self) -> str:
        self.paro_activo = True
        self.control = DINAMICO
        estaba = self.en_aire
        self._aterrizar()
        return "PARO: aterrizaje de emergencia" if estaba else "PARO (ya en el suelo)"

    def soltar_paro(self) -> None:
        self.paro_activo = False

    # ---- internos

    def _hover(self) -> None:
        self.comportamiento = "hover"
        self.velocidad = VelocityIntent()

    def _despegar(self) -> tuple[str, str]:
        self.en_aire = True
        self._hover()
        return "DESPEGAR", ""

    def _aterrizar(self) -> tuple[str, str]:
        self.en_aire = False
        self._hover()
        return "ATERRIZAR", ""


# ----------------------------------------------------------------- panel


class Lineas:
    def __init__(self, panel) -> None:
        self.panel = panel
        self.y = 30

    def salto(self, px: int = 10) -> None:
        self.y += px

    def texto(self, txt, color=BLANCO, escala=0.46, grosor=1) -> None:
        cv2.putText(self.panel, txt, (16, self.y), cv2.FONT_HERSHEY_SIMPLEX,
                    escala, color, grosor, cv2.LINE_AA)
        self.y += int(24 * max(escala / 0.46, 1.0))

    def titulo(self, txt, color=GRIS) -> None:
        self.salto(4)
        self.texto(txt, color, 0.42)

    def medida(self, m) -> None:
        color = VERDE if m.cumple else ROJO
        cv2.putText(self.panel, f"  {m.etiqueta[:20]:<20}", (16, self.y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, BLANCO, 1, cv2.LINE_AA)
        signo = ">" if m.sentido == ">=" else "<"
        valor = f"{m.valor:6.2f}" if np.isfinite(m.valor) else "   s/d"
        cv2.putText(self.panel, f"{valor} {signo} {m.umbral:5.2f}  "
                    f"{'OK' if m.cumple else '--'}", (206, self.y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
        self.y += 20

    def barra(self, fraccion: float, color) -> None:
        f = float(np.clip(fraccion, 0.0, 1.0))
        cv2.rectangle(self.panel, (16, self.y - 10), (16 + int(300 * f), self.y - 2),
                      color, -1)
        cv2.rectangle(self.panel, (16, self.y - 10), (316, self.y - 2), GRIS, 1)
        self.y += 14


def _direccion_mas_cercana(diag) -> str:
    if diag is None or not diag.get("direcciones"):
        return ""
    m = diag["direcciones"][0]
    return f"lo mas cerca: {m.etiqueta} a {m.valor:.0f} deg (cono {CONO_DEG:.0f})"


def _panel_estado(L, *, sim, ultima_accion, hay_marco, solo_dinamicos, t) -> None:
    """Cabecera: estado del dron simulado, o solo el marco en --solo-dinamicos."""
    if solo_dinamicos:
        if not hay_marco:
            L.texto("sin marco corporal", ROJO, 0.44)
    elif sim.paro_activo:
        L.texto("PARO DE EMERGENCIA", ROJO, 0.78, 2)
    else:
        L.texto(f"MODO {sim.control.upper()}", AMBAR, 0.6, 2)
        L.texto(f"{'EN EL AIRE' if sim.en_aire else 'en el suelo'}   "
                f"{sim.comportamiento}", VERDE if sim.en_aire else GRIS, 0.5,
                2 if sim.en_aire else 1)
        if sim.comportamiento == "MANUAL":
            v = sim.velocidad
            L.texto(f"vx {v.vx:+.0f}  vy {v.vy:+.0f}  vz {v.vz:+.0f}", AMBAR, 0.46)
    if ultima_accion is not None and t - ultima_accion[0] < MOSTRAR_S + 1.0:
        _, gesto, accion, motivo = ultima_accion
        if motivo:
            L.texto(f"{gesto}: ignorado, {motivo}", AMBAR, 0.4)
        else:
            L.texto(f"{gesto} -> {accion}", VERDE, 0.46)


def _panel_paro(L, *, regla, hay_marco, detalle) -> None:
    L.titulo(f"PARO   ({regla.postura}, {regla.confirmacion_s:.1f} s, siempre activo)")
    if not hay_marco:
        L.texto("  sin marco corporal", ROJO, 0.42)
    elif regla.activo:
        L.texto("  ACTIVO: suelta los brazos para rearmar", ROJO, 0.44)
    elif regla.cumple:
        L.texto(f"  postura OK, sostener {regla.falta_s:.1f} s mas", AMBAR, 0.44)
        L.barra(regla.sostenido_s / regla.confirmacion_s, AMBAR)
    else:
        L.texto(f"  {INSTRUCCION[regla.postura]}", GRIS, 0.4)
    if detalle and regla.medidas:
        for m in regla.medidas:
            L.medida(m)


def _panel_estaticos(L, *, sim, evento, diag, detalle) -> None:
    activo = sim.control == ESTATICO and not sim.paro_activo
    L.titulo("ESTATICOS   (un brazo, 0.2 s)" + ("" if activo else "   inactivos"),
             BLANCO if activo else GRIS)
    if evento is None or diag is None:
        L.texto("  sin marco corporal", ROJO if activo else GRIS, 0.42)
    elif evento.gesture is Gesture.NO_GESTURE:
        L.texto("  sin direccion", GRIS, 0.42)
        if detalle and activo:
            L.texto(f"  {_direccion_mas_cercana(diag)}", GRIS, 0.38)
    else:
        de_estado = evento.gesture in GESTOS_DE_ESTADO
        listo = evento.confirmed or evento.velocity != VelocityIntent()
        color = (VERDE if listo else AMBAR) if activo else GRIS
        L.texto(f"  {evento.gesture.value}" + ("   (estado)" if de_estado else ""),
                color, 0.56, 2 if activo else 1)
        falta = evento.scores.get("falta_s", 0.0)
        if falta > 0 and activo:
            L.texto(f"  sostener {falta:.1f} s mas", GRIS, 0.4)


def _panel_dinamicos(L, *, sim, rec, detalle, solo_dinamicos, t) -> None:
    activo = solo_dinamicos or (sim.control == DINAMICO and not sim.paro_activo)
    L.titulo("DINAMICOS   (DTW)" + ("" if activo else "   solo aplaudir"),
             BLANCO if activo else GRIS)
    if rec.en_segmento:
        L.texto(f"  grabando gesto   {rec.segmento_s:4.1f} s", ROJO, 0.48, 2)
    else:
        L.texto("  esperando movimiento", GRIS, 0.42)
        L.barra(rec.rapidez / ENTRADA_RAPIDEZ, AMBAR)
    ultima = rec.ultima
    if ultima is not None and t - ultima.t_fin < MOSTRAR_S:
        if ultima.gesto:
            L.texto(f"  {ultima.gesto.upper()}", VERDE, 0.58, 2)
        else:
            L.texto("  no reconocido", AMBAR, 0.48)
            L.texto(f"  {ultima.motivo or 'lejos de todas'}", GRIS, 0.38)
        L.texto(f"  distancia {ultima.distancia:.2f}   margen {ultima.margen:.2f}"
                f"   {ultima.duracion_s:.1f} s", GRIS, 0.38)
        if detalle and ultima.distancias:
            for g, d in sorted(ultima.distancias.items(), key=lambda x: x[1])[:4]:
                L.texto(f"     {g:<12} {d:.3f}", GRIS, 0.36)


def dibujar_panel(*, sim, rec, regla, evento, diag, ultima_accion, fps, escala_m,
                  contador, detalle, pausado, hay_marco, t, solo_dinamicos=False):
    panel = np.full((ALTO_VIDEO, ANCHO_PANEL, 3), FONDO, np.uint8)
    L = Lineas(panel)
    L.texto("SOLO DINAMICOS - SIN DRON" if solo_dinamicos
            else "VOCABULARIO COMPLETO - SIN DRON", GRIS, 0.42)
    torso = f"{escala_m * 100:.0f} cm" if np.isfinite(escala_m) else "s/d"
    L.texto(f"fps {fps:4.1f}    torso {torso}{'    PAUSA' if pausado else ''}",
            GRIS, 0.4)

    _panel_estado(L, sim=sim, ultima_accion=ultima_accion, hay_marco=hay_marco,
                  solo_dinamicos=solo_dinamicos, t=t)
    if not solo_dinamicos:
        _panel_paro(L, regla=regla, hay_marco=hay_marco, detalle=detalle)
        _panel_estaticos(L, sim=sim, evento=evento, diag=diag, detalle=detalle)
    _panel_dinamicos(L, sim=sim, rec=rec, detalle=detalle,
                     solo_dinamicos=solo_dinamicos, t=t)

    # ----- contadores
    sitio = (ALTO_VIDEO - PIE_ALTO - L.y) // 20
    if sitio >= 2:
        L.titulo("EN LA SESION")
        for g, n in contador.most_common(sitio - 1):
            L.texto(f"  {g:<26} {n}", BLANCO, 0.4)
        if not contador:
            L.texto("  nada todavia", GRIS, 0.4)

    cv2.putText(panel, "q salir   r reiniciar   d detalle   espacio pausa",
                (16, ALTO_VIDEO - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38, GRIS, 1,
                cv2.LINE_AA)
    return panel


# ----------------------------------------------------------------- bucle


def bucle(fuente, *, banco, regla, registro, espejo=True,
          estado_estatico=False, segmentos=None, persona="vivo",
          solo_dinamicos=False) -> Counter:
    captura = cv2.VideoCapture(fuente)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {fuente!r}.")
    detector = PoseDetector()
    rec = ReconocedorDinamico(banco)
    reglas = Body3DRecognizer()
    sim = Simulador()
    contador: Counter = Counter()
    escalas: list[float] = []
    anterior = 0.0
    fps = 0.0
    detalle = True
    pausado = False
    frame = None
    pose = None
    evento = diag = None
    ultima_accion = None
    nav_anterior: Gesture | None = None      # para anotar solo los cambios
    t_paro_soltado = -np.inf
    t0 = time.monotonic()
    # Historial crudo, para guardar cada segmento tal como se vio.
    crudos: list[tuple[float, np.ndarray, np.ndarray, np.ndarray]] = []
    guardados = 0

    def anotar(t, canal, gesto, accion, motivo, distancia=np.nan, margen=np.nan,
               distancias=None):
        if accion == "no reconocido":
            contador["no reconocido"] += 1
        else:
            contador[f"{gesto} -> {accion}" if not motivo else f"{gesto} ignorado"] += 1
        print(f"[{t - t0:6.2f} s] {canal:<10} {gesto:<10} {accion:<16}"
              + (f" {motivo}" if motivo else "")
              + (f"   d={distancia:.3f} margen={margen:.3f}"
                 if np.isfinite(distancia) else ""))
        if registro is not None:
            registro.writerow([f"{t - t0:.3f}", canal, gesto, accion, motivo,
                               f"{distancia:.4f}" if np.isfinite(distancia) else "",
                               f"{margen:.4f}" if np.isfinite(margen) else "",
                               sim.control, int(sim.en_aire), sim.comportamiento,
                               ";".join(f"{g}={d:.4f}" for g, d in
                                        sorted((distancias or {}).items()))])

    def guardar_segmento(det):
        """Cada segmento cerrado, reconocido o no, como una toma en disco."""
        nonlocal guardados
        tramo = [c for c in crudos if det.t_inicio - 0.2 <= c[0] <= det.t_fin]
        if len(tramo) < 8:
            return
        guardados += 1
        guardar(segmentos, Toma(
            persona=persona, gesto=f"leido_{det.gesto or 'nada'}",
            numero=guardados, orientacion_deg=0.0,
            world=np.stack([c[1] for c in tramo]),
            imagen=np.stack([c[2] for c in tramo]),
            visibility=np.stack([c[3] for c in tramo]),
            timestamps=np.array([c[0] - tramo[0][0] for c in tramo]),
        ))

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VENTANA, 1280, 720)
    if solo_dinamicos:
        print("Ponte a cuerpo entero. El gesto se reconoce al terminarlo.\n")
    else:
        print("Ponte a cuerpo entero. Arranca en modo dinamico; aplaudi para pasar "
              "a los estaticos y otra vez para volver. La X sobre la cabeza para siempre.\n")

    try:
        while True:
            if not pausado or frame is None:
                ok, crudo = captura.read()
                if not ok:
                    break
                alto, ancho = crudo.shape[:2]
                frame = cv2.resize(crudo, (int(ancho * ALTO_VIDEO / alto), ALTO_VIDEO))
                # Sin voltear: en espejo MediaPipe intercambia izquierda y
                # derecha, y el cruce de munecas cambia de signo.
                lm2d, mundo_lm = detector.process_full(frame)
                fps, anterior = calculate_fps(anterior)
                t = time.monotonic()

                pose = None
                mundo, vis = landmarks_to_array(mundo_lm)
                if mundo.size:
                    marco = body_frame(mundo, vis)
                    if marco is not None and marco.valid:
                        escalas.append(marco.torso_length_m)
                        pose = marco.apply(mundo) / float(np.median(escalas[-900:]))
                if segmentos is not None:
                    if mundo.size and lm2d is not None:
                        P2 = np.array([[l.x, l.y] for l in lm2d], dtype=np.float64)
                        crudos.append((t, mundo.copy(), P2, vis.copy()))
                    else:
                        crudos.append((t, np.full((N_LANDMARKS, 3), np.nan),
                                       np.full((N_LANDMARKS, 2), np.nan),
                                       np.zeros(N_LANDMARKS)))
                    if len(crudos) > 900:
                        crudos.pop(0)

                # 1. Paro. Manda sobre los dos modos. (No existe en --solo-dinamicos.)
                if not solo_dinamicos:
                    if regla.actualizar(pose, t):
                        accion = sim.paro()
                        ultima_accion = (t, "PARO", accion, "")
                        anotar(t, "estatico", "PARO", accion, "")
                        rec.reset()
                        reglas.reset()
                    if sim.paro_activo and not regla.activo:
                        sim.soltar_paro()
                        t_paro_soltado = t
                        rec.reset()

                # 2. Dinamico. Corre siempre, porque el aplauso que cambia de
                # modo es dinamico; en modo estatico el resto se ignora. En
                # --solo-dinamicos no hay supervisor: se anota lo detectado.
                det = rec.actualizar(pose, t)
                if det is not None and det.gesto:
                    if solo_dinamicos:
                        ultima_accion = (t, det.gesto, "detectado", "")
                        anotar(t, "dinamico", det.gesto, "detectado", "",
                               det.distancia, det.margen, det.distancias)
                    elif regla.activo or t - t_paro_soltado < DESCARTE_TRAS_PARO_S:
                        anotar(t, "dinamico", det.gesto, "descartado",
                               "movimiento del paro", det.distancia, det.margen)
                    else:
                        accion, motivo = sim.gesto(det.gesto)
                        ultima_accion = (t, det.gesto, accion, motivo)
                        anotar(t, "dinamico", det.gesto, accion, motivo,
                               det.distancia, det.margen, det.distancias)
                        reglas.reset()      # que el reposo tras el gesto no herede
                elif det is not None:
                    # Un segmento rechazado tambien se registra: es la unica
                    # forma de saber despues POR QUE un gesto no salio.
                    anotar(t, "dinamico", "-", "no reconocido",
                           det.motivo or "lejos de todas las plantillas",
                           det.distancia, det.margen, det.distancias)
                if det is not None and segmentos is not None:
                    guardar_segmento(det)

                # 3. Estaticos. Se alimentan siempre para que la escala se
                # caliente y para que el panel los muestre; solo actuan en
                # modo estatico, y nunca con el paro en curso.
                if not solo_dinamicos:
                    evento = reglas.update(mundo_lm, t)
                    rasgos = reglas.ultimos_rasgos
                    diag = None if rasgos is None else diagnostico(rasgos)
                    g = evento.gesture
                    if regla.activo or regla.cumple:
                        reglas.reset()
                        g = Gesture.NO_GESTURE
                    if g in NAVEGACION and evento.velocity != VelocityIntent():
                        accion, motivo = sim.navegar(g.value, evento.velocity)
                        if g is not nav_anterior:
                            ultima_accion = (t, g.value, accion, motivo)
                            anotar(t, "estatico", g.value, accion, motivo)
                        nav_anterior = g
                    else:
                        if nav_anterior is not None:
                            sim.soltar_navegacion()
                        nav_anterior = None
                        if g in GESTOS_DE_ESTADO and evento.confirmed:
                            if estado_estatico:
                                accion, motivo = sim.gesto(g.value)
                            else:
                                accion, motivo = "ignorado", "desactivado (--estado-estatico)"
                            ultima_accion = (t, g.value, accion, motivo)
                            anotar(t, "estado", g.value, accion, motivo)

                draw_pose(frame, lm2d, detector.connections)

            panel = dibujar_panel(
                sim=sim, rec=rec, regla=regla, evento=evento, diag=diag,
                ultima_accion=ultima_accion, fps=fps,
                escala_m=float(np.median(escalas)) if escalas else float("nan"),
                contador=contador, detalle=detalle, pausado=pausado,
                hay_marco=pose is not None, t=time.monotonic(),
                solo_dinamicos=solo_dinamicos)
            mostrado = cv2.flip(frame, 1) if espejo else frame
            cv2.imshow(VENTANA, np.hstack([mostrado, panel]))

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("r"):
                rec.reset()
                regla.reset()
                reglas.reset()
                sim.reset()
                ultima_accion = None
                nav_anterior = None
            if tecla == ord("d"):
                detalle = not detalle
            if tecla == ord(" "):
                pausado = not pausado
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        captura.release()
        detector.close()
        cv2.destroyAllWindows()
    return contador


# ------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prueba el vocabulario completo, dinamico y estatico, sin dron")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--video", help="archivo de video en vez de la camara")
    parser.add_argument("--banco",
                        help=f"por defecto models/{BANCO_VOCABULARIO} "
                             f"(models/{BANCO_DINAMICO} con --solo-dinamicos)")
    parser.add_argument("--umbral", type=float, help="sobreescribe el umbral del banco")
    parser.add_argument("--margen", type=float,
                        help="ventaja minima sobre el segundo gesto; el banco trae 0")
    parser.add_argument("--paro", choices=sorted(POSTURAS), default="cabeza",
                        help="postura del paro de emergencia")
    parser.add_argument("--confirmacion", type=float,
                        help="segundos a sostener el paro; por defecto segun postura")
    parser.add_argument("--estado-estatico", action="store_true",
                        help="activa DESPEGAR/ATERRIZAR/STOP estaticos de "
                             "body_3d_rules en modo estatico")
    parser.add_argument("--solo-dinamicos", action="store_true",
                        help="solo el canal dinamico (DTW), sin paro, estaticos ni "
                             "supervisor; sustituye al antiguo detectar_gestos_3d.py")
    parser.add_argument("--guardar-segmentos", action="store_true",
                        help="guarda cada segmento cerrado, reconocido o no, "
                             "como una toma en results/data/<modo>/<fecha>/segmentos")
    parser.add_argument("--persona", default="vivo",
                        help="nombre con el que se guardan los segmentos")
    parser.add_argument("--sin-espejo", action="store_true")
    parser.add_argument("--sin-csv", action="store_true")
    args = parser.parse_args()

    solo = args.solo_dinamicos
    nombre_banco = BANCO_DINAMICO if solo else BANCO_VOCABULARIO
    carpeta_modo = CARPETA_DINAMICOS if solo else CARPETA_VOCABULARIO
    ruta = Path(args.banco) if args.banco else PROJECT_DIR / "models" / nombre_banco
    if not ruta.exists():
        print(f"No hay banco en {ruta}. Construilo con:")
        if solo:
            print(r"  python .\external\gesture_detection\construir_plantillas.py")
        else:
            print(r"  python .\external\gesture_detection\construir_plantillas.py "
                  r"--carpeta results\data\gestos --gestos senalero,aplaudir,ven_aca,arco,circulo "
                  r"--negativos otro --salida models\plantillas_vocabulario.npz")
        return 1
    banco = BancoDinamico.cargar(ruta)
    if args.umbral is not None:
        # Forzar un umbral a mano tiene que ganarle a los umbrales por gesto
        # del banco; si no, el argumento no haria nada visible.
        banco.umbral = args.umbral
        banco.umbrales = {}
    if args.margen is not None:
        banco.margen = args.margen
    regla = ReglaParo(args.paro, args.confirmacion)

    print(f"Banco: {ruta.name}   gestos: {', '.join(banco.clases)}"
          + ("   (+ rechazo)" if banco.tiene_rechazo else
             "   SIN rechazo: aceptara cualquier movimiento"))
    print(f"  umbral {banco.umbral:.3f}   margen {banco.margen:.3f}"
          f"   rasgos {banco.plantillas[0].shape[1]}")
    if banco.umbrales:
        print("  umbral por gesto: " + "  ".join(
            f"{g} {banco.umbrales[g]:.3f}" for g in sorted(banco.umbrales)
            if g in banco.clases))
    if solo:
        print("Modo: solo dinamicos (sin paro, sin estaticos, sin supervisor)\n")
    else:
        print(f"Paro: {INSTRUCCION[regla.postura]}, {regla.confirmacion_s:.1f} s")
        print("Modo estatico: " + ", ".join(g.value for g in VELOCIDADES)
              + ("  + DESPEGAR/ATERRIZAR/STOP" if args.estado_estatico else "")
              + "\n")

    archivo = registro = None
    if not args.sin_csv:
        carpeta = (PROJECT_DIR / "results" / "data" / carpeta_modo
                   / datetime.now().strftime("%Y-%m-%d"))
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"sesion_{datetime.now():%H%M%S}.csv"
        archivo = destino.open("w", newline="", encoding="utf-8")
        registro = csv.writer(archivo)
        registro.writerow(["t_s", "canal", "gesto", "accion", "motivo",
                           "distancia", "margen", "control", "en_aire",
                           "comportamiento", "distancias"])

    segmentos = None
    if args.guardar_segmentos:
        segmentos = (PROJECT_DIR / "results" / "data" / carpeta_modo
                     / datetime.now().strftime("%Y-%m-%d") / "segmentos")
        print(f"Cada segmento cerrado se guarda en {segmentos}")
        print("  como toma 'leido_<gesto>'; sirve para ver por que fallo un gesto.")
        if solo:
            print("  Borra los que SI eran ese gesto; el resto es material de rechazo")
            print("  para construir_plantillas.py --rechazo-extra.")
        print()

    fuente = args.video if args.video else args.camera
    try:
        contador = bucle(fuente, banco=banco, regla=regla, registro=registro,
                         espejo=not args.sin_espejo,
                         estado_estatico=args.estado_estatico,
                         segmentos=segmentos, persona=args.persona,
                         solo_dinamicos=solo)
        print("\nEn la sesion:")
        for g, n in contador.most_common():
            print(f"  {g:<30} {n}")
        if not contador:
            print("  nada")
        if archivo is not None:
            print(f"\nRegistro: {destino}")
        return 0
    except KeyboardInterrupt:
        print("Interrupcion solicitada.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if archivo is not None:
            archivo.close()


if __name__ == "__main__":
    raise SystemExit(main())

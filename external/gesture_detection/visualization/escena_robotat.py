"""Vista 3D del Robotat para el video resumen: drones, operador, marker y camaras.

Dibuja en un recuadro, con una proyeccion en perspectiva propia (OpenCV, sin
matplotlib, que a 30 fps durante minutos seria lento):

* el area de vuelo de `escena_robotat.json` con su rejilla;
* las camaras del mocap (OptiTrack) y las camaras IP de vision por
  computadora, en las posiciones del JSON (aproximadas: ver su `_nota`);
* cada dron con su orientacion (yaw), su estela y una linea de sombra al suelo;
* el **marker 65** que el operador lleva en la mano y, a partir de el, una
  figura del operador: el cuerpo sigue al marker con retardo y el brazo va del
  hombro a la mano. Es una reconstruccion esquematica, no una medida del cuerpo.

Los datos salen de los CSV que ya escribe cada sesion, con la hora de pared
`t_unix` de cada fila, que es el mismo reloj que `render.jsonl`:

* `results/data/dron_robotat/<dia>/dron_robotat_DronN_*.csv` (cada dron);
* `results/data/control_camara_dron1/<dia>/<sesion>.csv` (marker 65).

No importa controladores: solo lee esos archivos.
"""

from __future__ import annotations

import bisect
import csv
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np

CONFIG = Path(__file__).resolve().with_name("escena_robotat.json")
PROJECT_DIR = Path(__file__).resolve().parents[3]

#: Muestras mas viejas que esto no se dibujan (el dron o el marker se perdieron).
VALIDA_S = 0.5
ESTELA_S = 3.0
#: Retardo con el que el cuerpo sigue a la mano (filtro de primer orden).
CUERPO_TAU_S = 1.2

COLORES_DRON = [(235, 175, 40), (60, 140, 255), (120, 200, 90), (200, 120, 220)]   # BGR
MARKER = (60, 60, 235)
MOCAP = (90, 200, 255)
IP = (235, 175, 40)
SUELO = (52, 48, 44)
REJILLA = (78, 74, 70)
TEXTO = (215, 215, 215)
POSTE = (95, 92, 88)
#: Mismo tono que el panel del video, para que la vista no sea un hueco negro.
FONDO = (24, 22, 20)


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v if math.isfinite(v) else math.nan


# ------------------------------------------------------------------- datos


class Serie:
    """Puntos `(t, x, y, z, yaw)` ordenados; `en(t)` da el ultimo valido."""

    def __init__(self, nombre: str, t, xyz, yaw=None) -> None:
        self.nombre = nombre
        orden = np.argsort(t)
        self.t = np.asarray(t, float)[orden]
        self.xyz = np.asarray(xyz, float).reshape(-1, 3)[orden]
        self.yaw = (np.zeros(len(self.t)) if yaw is None else np.asarray(yaw, float)[orden])

    def indice(self, t: float) -> int | None:
        i = bisect.bisect_right(self.t, t) - 1
        if i < 0 or t - self.t[i] > VALIDA_S:
            return None
        return i

    def en(self, t: float):
        i = self.indice(t)
        return None if i is None else (self.xyz[i], self.yaw[i])

    def estela(self, t: float, s: float = ESTELA_S) -> np.ndarray:
        a, b = bisect.bisect_left(self.t, t - s), bisect.bisect_right(self.t, t)
        return self.xyz[a:b]


def _leer(ruta: Path) -> list[dict]:
    with Path(ruta).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def drones_de_la_sesion(dia: str, t0: float, t1: float) -> list[Serie]:
    """Los CSV de dron del dia que se solapan con `[t0, t1]` (hora de pared)."""
    series = []
    for ruta in sorted((PROJECT_DIR / "results" / "data" / "dron_robotat" / dia).glob("dron_robotat_Dron*_*.csv")):
        filas = [f for f in _leer(ruta) if not f.get("evento")]
        t = np.array([_num(f.get("t_unix")) for f in filas])
        if not len(t) or not np.isfinite(t).any():
            continue
        if np.nanmax(t) < t0 or np.nanmin(t) > t1:
            continue
        xyz = np.array([[_num(f.get(f"mocap_{e}")) for e in "xyz"] for f in filas])
        ok = np.isfinite(t) & np.isfinite(xyz).all(axis=1)
        nombre = re.search(r"(Dron\d)", ruta.stem).group(1)
        yaw = np.array([_num(f.get("mocap_yaw_deg")) for f in filas])
        series.append(Serie(nombre, t[ok], xyz[ok], np.nan_to_num(yaw[ok])))
    # Si un mismo dron tiene dos CSV solapados, se queda el de mas muestras.
    unicos: dict[str, Serie] = {}
    for s in series:
        if s.nombre not in unicos or len(s.t) > len(unicos[s.nombre].t):
            unicos[s.nombre] = s
    return [unicos[k] for k in sorted(unicos)]


def eventos_de_drones(dia: str, t0: float, t1: float) -> list[tuple[float, str, str]]:
    """`[(t_unix, dron, evento)]` de los CSV de dron del dia dentro de `[t0, t1]`, en orden."""
    eventos = []
    for ruta in sorted((PROJECT_DIR / "results" / "data" / "dron_robotat" / dia).glob("dron_robotat_Dron*_*.csv")):
        nombre = re.search(r"(Dron\d)", ruta.stem).group(1)
        for f in _leer(ruta):
            t = _num(f.get("t_unix"))
            if f.get("evento") and math.isfinite(t) and t0 <= t <= t1:
                eventos.append((t, nombre, f["evento"]))
    return sorted(eventos)


def tramos_con_drones(eventos, duracion_s: float = 6.0) -> list[tuple[float, float]]:
    """Cuando enseñar los drones: al despegar y al **empezar** a seguir u orbitar.

    `SEGUIR` y `ORBITA` se repiten cada segundo mientras duran; solo cuenta
    el primero de cada racha. Los tramos que se tocan se funden en uno.
    """
    ultimo: dict[tuple[str, str], float] = {}
    tramos = []
    for t, dron, evento in eventos:
        if evento == "TAKEOFF":
            tramos.append((t - 0.3, t + duracion_s))
        elif evento in ("SEGUIR", "ORBITA"):
            if t - ultimo.get((dron, evento), -1e9) > 3.0:
                tramos.append((t, t + duracion_s))
            ultimo[(dron, evento)] = t
    tramos.sort()
    unidos: list[list[float]] = []
    for a, b in tramos:
        if unidos and a <= unidos[-1][1] + 1.0:
            unidos[-1][1] = max(unidos[-1][1], b)
        else:
            unidos.append([a, b])
    return [(a, b) for a, b in unidos]


def marker_de_la_sesion(ruta_csv: Path) -> Serie | None:
    if not Path(ruta_csv).is_file():
        return None
    filas = _leer(ruta_csv)
    if not filas or "marker_x" not in filas[0]:
        return None
    t = np.array([_num(f.get("t_unix")) for f in filas])
    xyz = np.array([[_num(f.get(f"marker_{e}")) for e in "xyz"] for f in filas])
    ok = np.isfinite(t) & np.isfinite(xyz).all(axis=1)
    return Serie("marker 65", t[ok], xyz[ok]) if ok.sum() else None


def cuerpo_desde_marker(marker: Serie, tau_s: float = CUERPO_TAU_S) -> Serie:
    """Posicion del cuerpo: la de la mano, filtrada (el cuerpo no se mueve con cada gesto)."""
    xy = marker.xyz[:, :2].copy()
    for i in range(1, len(xy)):
        dt = marker.t[i] - marker.t[i - 1]
        if dt > 2.0:                          # se perdio el marker: empezar de nuevo
            continue
        a = 1.0 - math.exp(-max(dt, 0.0) / tau_s)
        xy[i] = xy[i - 1] + a * (xy[i] - xy[i - 1])
    return Serie("operador", marker.t, np.column_stack([xy, np.zeros(len(xy))]))


# ------------------------------------------------------------------ dibujo


class Vista3D:
    """Camara virtual en perspectiva mirando al centro del area, con un leve giro."""

    def __init__(self, config: dict, ancho: int, alto: int, *, azimut_deg=-58.0, elevacion_deg=30.0,
                 distancia_m=8.0, giro_deg_por_s=0.0) -> None:
        self.c = config
        self.ancho, self.alto = ancho, alto
        self.azimut, self.elevacion = azimut_deg, elevacion_deg
        self.distancia = distancia_m
        self.giro = giro_deg_por_s
        ax, ay = config["area"]["x"], config["area"]["y"]
        self.centro = np.array([(ax[0] + ax[1]) / 2, (ay[0] + ay[1]) / 2, 0.9])
        self.focal = 1.55 * alto

    def _matriz(self, t: float):
        az = math.radians(self.azimut + self.giro * t)
        el = math.radians(self.elevacion)
        ojo = self.centro + self.distancia * np.array(
            [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        adelante = self.centro - ojo
        adelante /= np.linalg.norm(adelante)
        derecha = np.cross(adelante, [0, 0, 1.0])
        derecha /= np.linalg.norm(derecha)
        arriba = np.cross(derecha, adelante)
        return ojo, np.stack([derecha, -arriba, adelante])

    def proyectar(self, puntos, t: float) -> np.ndarray:
        ojo, r = self._matriz(t)
        p = (np.asarray(puntos, float).reshape(-1, 3) - ojo) @ r.T
        z = np.maximum(p[:, 2], 1e-3)
        return np.column_stack([self.ancho / 2 + self.focal * p[:, 0] / z,
                                self.alto / 2 + self.focal * p[:, 1] / z])

    def dibujar(self, t: float, *, drones: list[tuple[str, tuple, np.ndarray]], marker=None,
                cuerpo=None, camara_activa: str | None = None, t_vista: float = 0.0,
                esqueleto=None) -> np.ndarray:
        """BGR de la escena. `drones`: `[(nombre, (xyz, yaw) o None, estela)]`.

        `esqueleto`: `(lm 33 x 3, vis 33, conexiones)` del operador en metros del
        Robotat (`reconstruir_cuerpo.py`); si no hay, una figura esquematica en `cuerpo`.
        """
        esc = 2                                   # se dibuja al doble y se reduce: bordes suaves
        g = max(1, round(self.alto / 540))       # grosor de lo que se mueve: el doble en la vista grande
        img = np.full((self.alto * esc, self.ancho * esc, 3), FONDO, np.uint8)

        def P(puntos):
            return (self.proyectar(puntos, t_vista) * esc).astype(np.int32)

        ax, ay, alto = self.c["area"]["x"], self.c["area"]["y"], self.c["area"]["alto"]
        suelo = [[ax[0], ay[0], 0], [ax[1], ay[0], 0], [ax[1], ay[1], 0], [ax[0], ay[1], 0]]
        cv2.fillPoly(img, [P(suelo)], SUELO, cv2.LINE_AA)
        for x in np.arange(ax[0], ax[1] + 1e-6, 0.5):
            cv2.polylines(img, [P([[x, ay[0], 0], [x, ay[1], 0]])], False, REJILLA, 1 * esc, cv2.LINE_AA)
        for y in np.arange(ay[0], ay[1] + 1e-6, 0.5):
            cv2.polylines(img, [P([[ax[0], y, 0], [ax[1], y, 0]])], False, REJILLA, 1 * esc, cv2.LINE_AA)
        # Ejes del Robotat en el origen: x rojo, y verde.
        o = P([[0, 0, 0], [0.5, 0, 0], [0, 0.5, 0]])
        cv2.line(img, tuple(o[0]), tuple(o[1]), (60, 60, 220), 2 * esc, cv2.LINE_AA)
        cv2.line(img, tuple(o[0]), tuple(o[2]), (80, 200, 80), 2 * esc, cv2.LINE_AA)
        # Aristas verticales y superiores del volumen, tenues.
        for x, y, _ in suelo:
            cv2.polylines(img, [P([[x, y, 0], [x, y, alto]])], False, (70, 66, 62), 1 * esc, cv2.LINE_AA)
        techo = [[x, y, alto] for x, y, _ in suelo]
        cv2.polylines(img, [P(techo)], True, (70, 66, 62), 1 * esc, cv2.LINE_AA)

        # Camaras en su poste, con un cono tenue hacia el area y su icono.
        mocap = list(self.c.get("camaras_mocap", []))
        ips = self.c.get("camaras_ip", [])
        ips = list(ips.items()) if isinstance(ips, dict) else [(None, p) for p in ips]
        objetivo = np.array([self.centro[0], self.centro[1], 0.8])
        conos = img.copy()
        for pos, color in [(p, MOCAP) for p in mocap] + [(p, IP) for _, p in ips]:
            pos = np.asarray(pos, float)
            cv2.polylines(img, [P([[pos[0], pos[1], 0], pos])], False, POSTE, 2 * esc, cv2.LINE_AA)
            d = objetivo - pos
            d /= np.linalg.norm(d)
            u = np.cross(d, [0, 0, 1.0])
            u /= np.linalg.norm(u)
            v = np.cross(u, d)
            esquinas = [pos + 0.55 * d + su * 0.17 * u + sv * 0.12 * v
                        for su, sv in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
            q = P([pos] + esquinas)
            for k in range(1, 5):
                cv2.line(conos, tuple(q[0]), tuple(q[k]), color, 1 * esc, cv2.LINE_AA)
            cv2.polylines(conos, [q[1:]], True, color, 1 * esc, cv2.LINE_AA)
        img = cv2.addWeighted(conos, 0.3, img, 0.7, 0)
        for pos in mocap:
            icono_optitrack(img, P([pos])[0], esc)
        for nombre, pos in ips:
            icono_ip(img, P([pos])[0], esc, activa=nombre is not None and nombre == camara_activa)

        # Operador: su esqueleto 3D si se reconstruyo; si no, una figura bajo el marker.
        if esqueleto is not None:
            lm, vis, conexiones = esqueleto
            q = P(lm)
            gris = (225, 225, 225)
            for a, b in conexiones:
                if a >= 11 and b >= 11 and vis[a] > 0.3 and vis[b] > 0.3:
                    cv2.line(img, tuple(q[a]), tuple(q[b]), gris, 3 * esc * g, cv2.LINE_AA)
            for i in range(11, 33):
                if vis[i] > 0.3:
                    cv2.circle(img, tuple(q[i]), 2 * esc * g, (90, 185, 60), -1, cv2.LINE_AA)
            cuello = (lm[11] + lm[12]) / 2
            cabeza = lm[0] + np.array([0, 0, 0.04])
            c0, c1 = P([cabeza, cabeza + np.array([0, 0, 0.11])])
            cv2.line(img, tuple(P([cuello])[0]), tuple(c0), gris, 3 * esc * g, cv2.LINE_AA)
            cv2.circle(img, tuple(c0), max(3, int(np.linalg.norm(c1 - c0))), gris, 2 * esc * g, cv2.LINE_AA)
        elif cuerpo is not None:
            bx, by = cuerpo[0][:2]
            cadera, hombro, cabeza = [bx, by, 0.95], [bx, by, 1.42], [bx, by, 1.66]
            gris = (225, 225, 225)
            for a, b in ([[bx - 0.12, by, 0], cadera], [[bx + 0.12, by, 0], cadera], [cadera, hombro]):
                cv2.polylines(img, [P([a, b])], False, gris, 3 * esc * g, cv2.LINE_AA)
            mano = marker[0] if marker is not None else [bx + 0.15, by, 0.8]
            cv2.polylines(img, [P([hombro, mano])], False, gris, 3 * esc * g, cv2.LINE_AA)
            cv2.polylines(img, [P([hombro, [bx - 0.1, by, 0.85]])], False, gris, 3 * esc * g, cv2.LINE_AA)
            c0, c1 = P([cabeza, [bx, by, 1.66 + 0.11]])
            cv2.circle(img, tuple(c0), max(3, int(np.linalg.norm(c1 - c0))), gris, 2 * esc * g, cv2.LINE_AA)
        if marker is not None:
            q = P([marker[0]])[0]
            cv2.circle(img, tuple(q), 6 * esc * g, MARKER, -1, cv2.LINE_AA)

        # Drones: estela, sombra al suelo y una X con la nariz marcada.
        for k, (nombre, estado, estela) in enumerate(drones):
            color = COLORES_DRON[k % len(COLORES_DRON)]
            if len(estela) >= 2:
                cv2.polylines(img, [P(estela)], False, tuple(int(c * 0.6) for c in color), 2 * esc * g, cv2.LINE_AA)
            if estado is None:
                continue
            p, yaw = estado
            cv2.polylines(img, [P([p, [p[0], p[1], 0]])], False, (110, 110, 110), 1 * esc, cv2.LINE_AA)
            psi = math.radians(yaw)
            brazos = []
            for d in (math.pi / 4, 3 * math.pi / 4, -math.pi / 4, -3 * math.pi / 4):
                brazos.append([p[0] + 0.14 * math.cos(psi + d), p[1] + 0.14 * math.sin(psi + d), p[2]])
            b = P(brazos)
            cv2.line(img, tuple(b[0]), tuple(b[3]), color, 3 * esc * g, cv2.LINE_AA)
            cv2.line(img, tuple(b[1]), tuple(b[2]), color, 3 * esc * g, cv2.LINE_AA)
            nariz = P([p, [p[0] + 0.24 * math.cos(psi), p[1] + 0.24 * math.sin(psi), p[2]]])
            cv2.line(img, tuple(nariz[0]), tuple(nariz[1]), color, 2 * esc * g, cv2.LINE_AA)
            q = P([p])[0]
            cv2.circle(img, tuple(q), 4 * esc * g, color, -1, cv2.LINE_AA)
        return cv2.resize(img, (self.ancho, self.alto), interpolation=cv2.INTER_AREA)


def icono_optitrack(img, centro, esc: int = 1) -> None:
    """Camara OptiTrack: cuerpo oscuro con el anillo de LEDs alrededor de la lente."""
    x, y = int(centro[0]), int(centro[1])
    w, h = 9 * esc, 7 * esc
    cv2.rectangle(img, (x - w, y - h), (x + w, y + h), (40, 40, 40), -1, cv2.LINE_AA)
    cv2.rectangle(img, (x - w, y - h), (x + w, y + h), (150, 150, 150), max(1, esc // 2), cv2.LINE_AA)
    cv2.circle(img, (x, y), 5 * esc, MOCAP, max(1, int(1.5 * esc)), cv2.LINE_AA)
    cv2.circle(img, (x, y), 2 * esc, (230, 230, 230), -1, cv2.LINE_AA)


def icono_ip(img, centro, esc: int = 1, activa: bool = False) -> None:
    """Camara IP con pan/tilt: base y cupula claras, lente del color de las IP."""
    x, y = int(centro[0]), int(centro[1])
    r = (8 if activa else 6) * esc
    claro = (255, 255, 255) if activa else (215, 215, 215)
    cv2.rectangle(img, (x - r, y - r - 2 * esc), (x + r, y - r + esc), claro, -1, cv2.LINE_AA)
    cv2.ellipse(img, (x, y - r + esc), (r, r), 0, 0, 180, claro, -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), max(2, int(2.5 * esc)), IP, -1, cv2.LINE_AA)


def cargar_config(ruta: Path = CONFIG) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))

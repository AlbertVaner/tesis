"""Calibración extrínseca entre dos cámaras (estéreo).

Da la posición y orientación de una cámara respecto a la otra, que es lo que
falta para poder triangular. Los intrínsecos se dan por buenos y **no se
reestiman**: ya se midieron por separado con más vistas y mejor condicionadas
de las que puede aportar una sesión estéreo.

Sobre la sincronización
-----------------------
Las cámaras IP no están sincronizadas por hardware, y eso normalmente sería un
problema para observar el mismo instante desde dos vistas. Aquí no lo es,
porque **la captura exige que el tablero esté quieto**: si no se mueve, da
igual que una cámara vea el frame 30 ms después que la otra. La misma puerta de
quietud que evita los frames movidos resuelve de paso la sincronización.

Marco de coordenadas
--------------------
El resultado sitúa la cámara B respecto de la A, así que el origen es la cámara
A. Anclarlo al marco del Robotat es un paso posterior y distinto, que usa el
Crazyflie como blanco; ver docs/calibration.md.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from .board import ChessboardSpec
from .intrinsics import (
    ATIPICA_FACTOR_MEDIANA,
    ATIPICA_MINIMO_PX,
    CameraIntrinsics,
)

# Por encima de este error la calibración estéreo no es utilizable.
RMS_ACEPTABLE_PX = 1.0

# Mínimo de pares tras descartar atípicos.
MINIMO_PARES = 8

# Tamaño mínimo del tablero en el cuadro para calibración ESTÉREO.
#
# Mucho más bajo que en intrínsecos (0.20) y no por descuido: son problemas
# distintos. En intrínsecos se estima la focal, y para eso el tablero tiene que
# subtender un ángulo grande. Aquí los intrínsecos van FIJOS y sólo se estiman
# 6 parámetros (R y T) a partir de ~1000 correspondencias repartidas en 18
# pares: el sistema está enormemente sobredeterminado.
#
# Medido en simulación con ruido de detección conservador (0.5 px), error en la
# escala reconstruida:
#
#     extent 3.0 % (69 px)  ->  +6.96 %   inservible
#     extent 3.7 % (86 px)  ->  +3.17 %   malo
#     extent 4.5 % (103 px) ->  +1.67 %   límite
#     extent 6.3 % (146 px) ->  +0.34 %   bien
#     extent 8.8 % (203 px) ->  +0.17 %   muy bien
#     extent 12.9 % (297 px)->  +0.09 %
#
# El codo está sobre el 6 %. Se toma 8 % para dejar margen.
EXTENT_MINIMO_ESTEREO = 0.08

# --- coherencia entre pares -------------------------------------------------
#
# Cada par del tablero determina, por sí solo, la pose relativa entre las dos
# cámaras: basta resolver PnP en cada una. Si las cámaras no se movieron, todos
# los pares tienen que dar la misma respuesta. Si una cámara se reapunta a
# mitad de sesión, los pares de antes y los de después describen geometrías
# distintas, y `stereoCalibrate` intenta ajustar UNA pose rígida a DOS
# configuraciones: el resultado es un RMS enorme sin ninguna pista de por qué.
#
# Es el fallo más caro de la calibración estéreo, porque no se distingue de
# «datos ruidosos» mirando el RMS. Por eso se detecta explícitamente.
#
# Un par se considera coherente con una hipótesis de pose si reproyecta por
# debajo de este umbral.
#
# Medido en simulación con distorsión e intrínsecos realistas (18 pares por
# sesión, hipótesis reajustada sobre sus inliers), contando cuántas sesiones se
# marcan como «una cámara se movió»:
#
#                        ruido 0.5 px   1 px    2 px
#     cámaras quietas       0/8         0/5     0/5     <- ningún falso positivo
#     movida 28°            8/8         5/5      -
#     movida 10°            8/8          -      3/5
#     movida  5°             -           -      3/5
#
# El valor importa: a 3 px un grupo real se fragmenta y el movimiento pasa
# desapercibido; a 5 px los grupos salen enteros sin ningún falso positivo.
# Movimientos por debajo de lo que detecta aquí aportan menos error que el
# propio ruido de detección.
UMBRAL_COHERENCIA_PX = 5.0

# Un grupo coherente por debajo de este tamaño no se considera una
# «configuración», sino ruido.
MINIMO_BLOQUE = 4


class ParesIncoherentes(RuntimeError):
    """Los pares no describen una sola geometría: una cámara se movió."""

    def __init__(self, coherencia: "Coherencia"):
        super().__init__(coherencia.diagnostico())
        self.coherencia = coherencia


@dataclass
class Coherencia:
    """Resultado de comprobar que todos los pares describen la misma geometría."""

    n_pares: int
    consenso: list[int]
    bloques: list[list[int]]
    sueltos: list[int]
    movimiento_en: int | None = None

    @property
    def hay_movimiento(self) -> bool:
        return self.movimiento_en is not None

    @property
    def coherente(self) -> bool:
        return not self.hay_movimiento and len(self.consenso) >= MINIMO_PARES

    def resumen(self) -> str:
        if self.hay_movimiento:
            return (f"INCOHERENTE: {len(self.bloques)} configuraciones "
                    f"distintas, cambio en el par {self.movimiento_en}")
        if self.sueltos:
            return (f"coherente: {len(self.consenso)}/{self.n_pares} pares "
                    f"(sueltos: {', '.join(str(i) for i in self.sueltos)})")
        return f"coherente: {self.n_pares}/{self.n_pares} pares"

    def diagnostico(self) -> str:
        if not self.hay_movimiento:
            return self.resumen()
        lineas = [
            "Los pares no describen una sola geometría: se agrupan en "
            f"{len(self.bloques)} configuraciones incompatibles entre sí.",
            "",
        ]
        for n, bloque in enumerate(self.bloques, 1):
            lineas.append(f"  grupo {n}: pares "
                          f"{', '.join(str(i) for i in bloque)}")
        if self.sueltos:
            lineas.append(f"  sin grupo: {', '.join(str(i) for i in self.sueltos)}")
        lineas += [
            "",
            f"Los grupos están separados en el tiempo — el cambio ocurre en el "
            f"par {self.movimiento_en}. Eso significa que UNA DE LAS CÁMARAS SE "
            "MOVIÓ durante la sesión (pan/tilt desde la app, un roce, o el "
            "seguimiento automático de movimiento sin desactivar).",
            "",
            "No se puede calibrar con estos datos: no hay una sola posición "
            "relativa que describa los dos grupos, y tampoco se sabe en cuál de "
            "las dos configuraciones están las cámaras AHORA.",
            "",
            "Qué hacer: fijar las cámaras, comprobar que patrulla y seguimiento "
            "estén desactivados, y repetir la captura sin tocarlas. Los pares de "
            "un solo grupo se pueden recalibrar con --solo-pares si hacen falta "
            "y se sabe que las cámaras siguen en esa posición.",
        ]
        return "\n".join(lineas)


@dataclass
class StereoExtrinsics:
    """Pose de la cámara B respecto de la A."""

    cam_a: str
    cam_b: str
    R: np.ndarray  # 3x3, rota de A a B
    T: np.ndarray  # (3,) en metros, traslación de A a B
    rms: float
    n_pairs: int
    n_descartados: int = 0
    per_pair_errors: np.ndarray = field(default_factory=lambda: np.empty(0))
    intrinsics_a: CameraIntrinsics | None = None
    intrinsics_b: CameraIntrinsics | None = None
    coherencia: "Coherencia | None" = None
    indices: list[int] = field(default_factory=list)
    fecha: str = ""

    # ------------------------------------------------------------ derivados

    @property
    def baseline_m(self) -> float:
        """Distancia entre los dos centros ópticos, en metros."""
        return float(np.linalg.norm(self.T))

    @property
    def angulo_entre_ejes_deg(self) -> float:
        """Ángulo entre los ejes ópticos de las dos cámaras.

        No es el ángulo de triangulación (ese depende de dónde esté el punto),
        pero sí dice cuánto convergen o divergen las cámaras.
        """
        eje_a = np.array([0.0, 0.0, 1.0])
        eje_b = self.R.T @ eje_a
        cos = float(np.clip(np.dot(eje_a, eje_b), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos)))

    @property
    def calidad_aceptable(self) -> bool:
        return self.rms <= RMS_ACEPTABLE_PX

    def projection_matrices(self) -> tuple[np.ndarray, np.ndarray]:
        """Matrices `(3, 4)` de las dos cámaras, con origen en la cámara A.

        Es lo único que consume `triangulation/`.
        """
        if self.intrinsics_a is None or self.intrinsics_b is None:
            raise ValueError(
                "Hacen falta los intrínsecos de ambas cámaras para componer "
                "las matrices de proyección."
            )
        Pa = self.intrinsics_a.K @ np.hstack([np.eye(3), np.zeros((3, 1))])
        Pb = self.intrinsics_b.K @ np.hstack([self.R, self.T.reshape(3, 1)])
        return Pa, Pb

    def angulo_triangulacion_deg(self, punto3d: np.ndarray) -> float:
        """Ángulo entre rayos hacia un punto, visto desde las dos cámaras."""
        X = np.asarray(punto3d, dtype=np.float64).ravel()
        ca = np.zeros(3)                      # la cámara A está en el origen
        cb = -self.R.T @ self.T.ravel()       # centro de la cámara B
        va, vb = X - ca, X - cb
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na < 1e-12 or nb < 1e-12:
            return 0.0
        cos = float(np.clip(np.dot(va, vb) / (na * nb), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos)))

    # ------------------------------------------------------------ E/S

    def to_dict(self) -> dict:
        return {
            "cam_a": self.cam_a,
            "cam_b": self.cam_b,
            "fecha": self.fecha,
            "R": [[float(v) for v in fila] for fila in self.R],
            "T": [float(v) for v in np.asarray(self.T).ravel()],
            "rms_px": float(self.rms),
            "n_pairs": int(self.n_pairs),
            "n_descartados": int(self.n_descartados),
            "baseline_m": round(self.baseline_m, 5),
            "angulo_entre_ejes_deg": round(self.angulo_entre_ejes_deg, 2),
        }

    def save(self, ruta: str | Path) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return ruta

    @classmethod
    def load(cls, ruta: str | Path) -> "StereoExtrinsics":
        d = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
        return cls(
            cam_a=d["cam_a"],
            cam_b=d["cam_b"],
            R=np.array(d["R"], dtype=np.float64),
            T=np.array(d["T"], dtype=np.float64),
            rms=float(d["rms_px"]),
            n_pairs=int(d["n_pairs"]),
            n_descartados=int(d.get("n_descartados", 0)),
            fecha=d.get("fecha", ""),
        )

    def resumen(self) -> str:
        estado = "OK" if self.calidad_aceptable else "POBRE"
        return (
            f"[{self.cam_a}->{self.cam_b}] {self.n_pairs} pares"
            + (f" (+{self.n_descartados} descartados)" if self.n_descartados else "")
            + f", RMS {self.rms:.3f} px ({estado}), "
            f"línea base {self.baseline_m * 100:.1f} cm, "
            f"ejes a {self.angulo_entre_ejes_deg:.1f}°"
        )


def _errores_por_par(objp, pa, pb, Ka, da, Kb, db, R, T, *,
                     poses_a=None) -> np.ndarray:
    """Error de reproyección de cada par, con la pose estimada del tablero.

    `poses_a` permite reutilizar las poses del tablero en la cámara A, que no
    dependen de la hipótesis (R, T) y se recalcularían N veces al comparar
    todos los pares contra todos.
    """
    errores = []
    for k, (a, b) in enumerate(zip(pa, pb)):
        if poses_a is not None:
            rvec, tvec = poses_a[k]
            ok = rvec is not None
        else:
            ok, rvec, tvec = cv2.solvePnP(
                objp, np.asarray(a, np.float32).reshape(-1, 1, 2), Ka, da
            )
        if not ok:
            errores.append(np.inf)
            continue
        proj_a, _ = cv2.projectPoints(objp, rvec, tvec, Ka, da)
        Rt, _ = cv2.Rodrigues(rvec)
        Rb = R @ Rt
        tb = R @ tvec.reshape(3, 1) + T.reshape(3, 1)
        proj_b, _ = cv2.projectPoints(objp, cv2.Rodrigues(Rb)[0], tb, Kb, db)

        ea = np.asarray(a, np.float64).reshape(-1, 2) - proj_a.reshape(-1, 2)
        eb = np.asarray(b, np.float64).reshape(-1, 2) - proj_b.reshape(-1, 2)
        todos = np.vstack([ea, eb])
        errores.append(float(np.sqrt(np.mean(np.sum(todos ** 2, axis=1)))))
    return np.array(errores)


def _poses_tablero(objp, puntos, K, dist) -> list[tuple[np.ndarray, np.ndarray]]:
    """Pose del tablero en cada vista, resolviendo PnP."""
    poses = []
    for p in puntos:
        ok, rvec, tvec = cv2.solvePnP(
            objp, np.asarray(p, np.float32).reshape(-1, 1, 2), K, dist
        )
        poses.append((rvec, tvec) if ok else (None, None))
    return poses


def pose_relativa_de_un_par(objp, a, b, Ka, da, Kb, db):
    """Pose de B respecto de A implicada por un solo par.

    Un tablero visto a la vez por las dos cámaras basta para determinar la
    geometría completa, y de forma métrica: PnP da la pose del tablero en cada
    cámara, y componerlas da la pose de una respecto de la otra.
    """
    oka, rva, tva = cv2.solvePnP(objp, np.asarray(a, np.float32).reshape(-1, 1, 2), Ka, da)
    okb, rvb, tvb = cv2.solvePnP(objp, np.asarray(b, np.float32).reshape(-1, 1, 2), Kb, db)
    if not (oka and okb):
        return None, None
    Ra = cv2.Rodrigues(rva)[0]
    Rb = cv2.Rodrigues(rvb)[0]
    R = Rb @ Ra.T
    return R, (tvb.ravel() - R @ tva.ravel())


def analizar_coherencia(
    puntos_a, puntos_b, intr_a, intr_b, spec, *,
    umbral_px: float = UMBRAL_COHERENCIA_PX,
) -> Coherencia:
    """Comprueba que todos los pares describan la misma geometría.

    Cada par propone, por sí solo, una pose relativa completa. Se toma la de
    cada par como hipótesis y se mide cuántos de los demás encajan en ella. El
    grupo más grande es el consenso.

    La pose de un solo par no siempre es fiable — PnP sobre un patrón plano
    tiene una ambigüedad de dos soluciones que se vuelve severa cuando el
    tablero se ve casi de frente — así que cada hipótesis se **reajusta** sobre
    sus propios inliers antes de contarlos. Sin ese paso, un grupo real se
    fragmenta en trozos de dos o tres pares y el movimiento pasa desapercibido.

    Si los pares que quedan fuera forman **otro** grupo grande y los dos grupos
    están separados en el tiempo, no son ruido: son dos posiciones físicas
    distintas de las cámaras. Eso es lo que se busca detectar.
    """
    objp = spec.object_points()
    Ka, da = intr_a.K, intr_a.dist.reshape(1, -1)
    Kb, db = intr_b.K, intr_b.dist.reshape(1, -1)
    n = len(puntos_a)

    pa = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in puntos_a]
    pb = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in puntos_b]
    poses_a = _poses_tablero(objp, pa, Ka, da)

    def encajan(R, T) -> set[int]:
        errs = _errores_por_par(objp, pa, pb, Ka, da, Kb, db, R, T,
                                poses_a=poses_a)
        return {j for j, e in enumerate(errs) if e < umbral_px}

    def refinar(grupo: set[int]) -> set[int]:
        """Reajusta la pose sobre un grupo y recuenta quién encaja."""
        for _ in range(3):
            idx = sorted(grupo)
            if len(idx) < 3:
                return grupo
            try:
                _, _, _, _, _, R, T, _, _ = cv2.stereoCalibrate(
                    [objp] * len(idx), [pa[i] for i in idx], [pb[i] for i in idx],
                    Ka, da, Kb, db, intr_a.image_size,
                    flags=cv2.CALIB_FIX_INTRINSIC,
                    criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                              50, 1e-6),
                )
            except cv2.error:
                return grupo
            nuevo = encajan(np.asarray(R), np.asarray(T).ravel())
            if nuevo == grupo or len(nuevo) < 3:
                return nuevo if len(nuevo) >= 3 else grupo
            grupo = nuevo
        return grupo

    candidatos: list[set[int]] = []
    vistos: list[set[int]] = []
    for i in range(n):
        R, T = pose_relativa_de_un_par(objp, pa[i], pb[i], Ka, da, Kb, db)
        if R is None:
            continue
        semilla = encajan(R, T) | {i}
        if len(semilla) < 3 or semilla in vistos:
            continue
        vistos.append(semilla)
        grupo = refinar(semilla)
        if grupo not in candidatos:
            candidatos.append(grupo)

    inliers = [set() for _ in range(n)]
    for grupo in candidatos:
        for i in grupo:
            if len(grupo) > len(inliers[i]):
                inliers[i] = grupo

    restantes = set(range(n))
    bloques: list[list[int]] = []
    while restantes:
        mejor = max(restantes, key=lambda i: len(inliers[i] & restantes))
        grupo = sorted(inliers[mejor] & restantes)
        if len(grupo) < MINIMO_BLOQUE:
            break
        bloques.append(grupo)
        restantes -= set(grupo)

    if not bloques:
        return Coherencia(n, [], [], sorted(restantes))

    consenso = bloques[0]
    movimiento = None
    if len(bloques) >= 2:
        # ¿Están separados en el tiempo? Si un grupo termina antes de que
        # empiece el otro, es un cambio de configuración, no ruido disperso.
        a, b = bloques[0], bloques[1]
        primero, segundo = (a, b) if max(a) < max(b) else (b, a)
        if max(primero) < min(segundo):
            movimiento = min(segundo)

    return Coherencia(n, consenso, bloques, sorted(restantes), movimiento)


def calibrate_stereo(
    puntos_a: list[np.ndarray],
    puntos_b: list[np.ndarray],
    intr_a: CameraIntrinsics,
    intr_b: CameraIntrinsics,
    spec: ChessboardSpec,
    *,
    rechazar_atipicos: bool = True,
    exigir_coherencia: bool = True,
    indices: list[int] | None = None,
) -> StereoExtrinsics:
    """Estima la pose de la cámara B respecto de la A.

    Los intrínsecos se fijan (`CALIB_FIX_INTRINSIC`): ya están medidos con más
    vistas y mejor condicionadas que las que aporta una sesión estéreo, y
    dejarlos libres sólo añade parámetros que el dato no determina.

    Args:
        puntos_a, puntos_b: esquinas del tablero en cada cámara, un elemento
            por par simultáneo. Deben corresponderse uno a uno.
    """
    if len(puntos_a) != len(puntos_b):
        raise ValueError(
            f"Los pares no se corresponden: {len(puntos_a)} en A y "
            f"{len(puntos_b)} en B."
        )
    if len(puntos_a) < MINIMO_PARES:
        raise ValueError(
            f"Hacen falta al menos {MINIMO_PARES} pares; hay {len(puntos_a)}. "
            "Lo recomendable son 15-20, con el tablero repartido por el "
            "solape de las dos cámaras."
        )

    objp = spec.object_points()
    pa = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in puntos_a]
    pb = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in puntos_b]
    Ka, da = intr_a.K, intr_a.dist.reshape(1, -1)
    Kb, db = intr_b.K, intr_b.dist.reshape(1, -1)
    if indices is None:
        indices = list(range(len(pa)))

    # Antes de ajustar nada: ¿describen todos los pares la misma geometría?
    # Si una cámara se movió a mitad de sesión no hay respuesta correcta, y
    # el ajuste lo enmascara como un RMS alto sin explicar la causa.
    coh = analizar_coherencia(pa, pb, intr_a, intr_b, spec)
    if exigir_coherencia and coh.hay_movimiento:
        raise ParesIncoherentes(coh)

    def ajustar(la, lb):
        return cv2.stereoCalibrate(
            [objp] * len(la), la, lb, Ka, da, Kb, db, intr_a.image_size,
            flags=cv2.CALIB_FIX_INTRINSIC,
            criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                      100, 1e-6),
        )

    rms, _, _, _, _, R, T, _, _ = ajustar(pa, pb)

    descartados: list[int] = []
    vivos = list(range(len(pa)))
    if rechazar_atipicos:
        for _ in range(5):
            errs = _errores_por_par(
                objp, [pa[i] for i in vivos], [pb[i] for i in vivos],
                Ka, da, Kb, db, R, T,
            )
            umbral = max(ATIPICA_MINIMO_PX,
                         ATIPICA_FACTOR_MEDIANA * float(np.median(errs)))
            malos = [vivos[j] for j, e in enumerate(errs) if e > umbral]
            if not malos:
                break
            quedan = [i for i in vivos if i not in malos]
            if len(quedan) < MINIMO_PARES:
                break
            vivos = quedan
            descartados.extend(malos)
            rms, _, _, _, _, R, T, _, _ = ajustar(
                [pa[i] for i in vivos], [pb[i] for i in vivos]
            )
        pa = [pa[i] for i in vivos]
        pb = [pb[i] for i in vivos]

    errores = _errores_por_par(objp, pa, pb, Ka, da, Kb, db, R, T)

    return StereoExtrinsics(
        cam_a=intr_a.camera,
        cam_b=intr_b.camera,
        R=np.asarray(R, dtype=np.float64),
        T=np.asarray(T, dtype=np.float64).ravel(),
        rms=float(rms),
        n_pairs=len(pa),
        n_descartados=len(descartados),
        per_pair_errors=errores,
        intrinsics_a=intr_a,
        intrinsics_b=intr_b,
        coherencia=coh,
        indices=[indices[i] for i in vivos] if rechazar_atipicos else list(indices),
        fecha=_dt.date.today().isoformat(),
    )

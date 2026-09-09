"""Calibración intrínseca: matriz de cámara, distorsión y campo de visión.

Los intrínsecos son propiedad del lente y del sensor, no de dónde esté la
cámara: sobreviven a moverla, y sólo se invalidan si cambia la resolución del
stream o el zoom. Por eso se calibran una vez y se reutilizan.

Este módulo es la única fuente de matrices de cámara del repositorio. Ver
AGENTS.md, "Criterio para ubicar archivos nuevos", punto 5.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from .board import ChessboardSpec, corner_centroid, corner_extent

# Por encima de este error de reproyección la calibración es pobre y conviene
# repetirla. Referencia habitual en la literatura de visión.
RMS_ACEPTABLE_PX = 0.5

# El tablero debe ocupar al menos esta fracción del ancho de la imagen para que
# la focal quede determinada. Ver board.corner_extent.
EXTENT_MINIMO = 0.20
EXTENT_OBJETIVO = 0.30

# Coherencia del residual por encima de la cual se considera que el error es
# SISTEMÁTICO y no ruido. Ver CameraIntrinsics.residual_coherence.
COHERENCIA_SISTEMATICA = 0.35

# Rechazo de vistas atípicas. Una vista movida no es "una vista un poco peor":
# es una observación de otra cosa, y contamina el ajuste entero.
ATIPICA_FACTOR_MEDIANA = 3.0   # error > este múltiplo de la mediana
ATIPICA_MINIMO_PX = 1.5        # ...y por encima de este absoluto
MINIMO_VISTAS_TRAS_RECHAZO = 10


@dataclass
class CameraIntrinsics:
    """Resultado de una calibración intrínseca."""

    camera: str
    image_size: tuple[int, int]  # (ancho, alto)
    K: np.ndarray  # 3x3
    dist: np.ndarray  # (5,) k1 k2 p1 p2 k3
    rms: float
    n_images: int
    n_descartadas: int = 0
    per_view_errors: np.ndarray = field(default_factory=lambda: np.empty(0))
    residual_coherence: float = 0.0
    board: str = ""
    fecha: str = ""

    # ------------------------------------------------------------ derivados

    @property
    def fx(self) -> float:
        return float(self.K[0, 0])

    @property
    def fy(self) -> float:
        return float(self.K[1, 1])

    @property
    def fov_h_deg(self) -> float:
        """Campo de visión horizontal, derivado del ajuste.

        Sustituye a la medición con cinta métrica: sale del propio `fx`.
        """
        return 2.0 * math.degrees(math.atan(self.image_size[0] / (2.0 * self.fx)))

    @property
    def fov_v_deg(self) -> float:
        return 2.0 * math.degrees(math.atan(self.image_size[1] / (2.0 * self.fy)))

    @property
    def cobertura_vertical_por_metro(self) -> float:
        """Metros de alto que abarca el cuadro por cada metro de distancia.

        Es el número que decide a qué distancia hay que poner la cámara para
        que una persona quepa entera. Ver docs/hardware.md.
        """
        return 2.0 * math.tan(math.radians(self.fov_v_deg) / 2.0)

    def distancia_minima(self, alto_objetivo_m: float, altura_camara_m: float) -> float:
        """Distancia mínima para que un objeto de ese alto quepa entero.

        Supone la cámara horizontal. La altura óptima es la mitad del alto a
        cubrir; cualquier otra exige más distancia.
        """
        semicobertura = self.cobertura_vertical_por_metro / 2.0
        necesario = max(altura_camara_m, alto_objetivo_m - altura_camara_m)
        return necesario / semicobertura

    @property
    def calidad_aceptable(self) -> bool:
        return self.rms <= RMS_ACEPTABLE_PX

    # ------------------------------------------------------------ E/S

    def to_dict(self) -> dict:
        return {
            "camera": self.camera,
            "fecha": self.fecha,
            "board": self.board,
            "image_size": [int(self.image_size[0]), int(self.image_size[1])],
            "K": [[float(v) for v in fila] for fila in self.K],
            "dist": [float(v) for v in np.asarray(self.dist).ravel()],
            "rms_px": float(self.rms),
            "n_images": int(self.n_images),
            "n_descartadas": int(self.n_descartadas),
            "fov_h_deg": round(self.fov_h_deg, 2),
            "fov_v_deg": round(self.fov_v_deg, 2),
            "cobertura_vertical_por_metro": round(
                self.cobertura_vertical_por_metro, 4
            ),
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
    def load(cls, ruta: str | Path) -> "CameraIntrinsics":
        datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
        return cls(
            camera=datos["camera"],
            image_size=(int(datos["image_size"][0]), int(datos["image_size"][1])),
            K=np.array(datos["K"], dtype=np.float64),
            dist=np.array(datos["dist"], dtype=np.float64),
            rms=float(datos["rms_px"]),
            n_images=int(datos["n_images"]),
            board=datos.get("board", ""),
            fecha=datos.get("fecha", ""),
        )

    # ------------------------------------------------------------ uso

    def undistort(self, imagen: np.ndarray) -> np.ndarray:
        """Rectifica una imagen.

        Obligatorio antes de cualquier uso geométrico: si no se rectifica, la
        triangulación absorbe la distorsión como error y el residual sube sin
        explicación aparente. Ver docs/calibration.md.
        """
        return cv2.undistort(imagen, self.K, self.dist)

    def undistort_points(self, puntos: np.ndarray) -> np.ndarray:
        """Rectifica coordenadas de píxel, devolviéndolas en píxeles.

        Es la versión de `undistort` para puntos ya detectados, y es lo que hay
        que aplicar **antes de triangular**: la matriz de proyección `K[R|T]`
        describe una cámara estenopeica ideal, y las esquinas detectadas no lo
        son. Saltarse este paso no rompe nada de forma visible — el residual de
        reproyección puede seguir siendo bajo — pero introduce un error de
        escala sistemático en la reconstrucción. Con las Tapo (k1 ≈ -0.42) ese
        error es del orden del 6 %.
        """
        pts = np.asarray(puntos, dtype=np.float32).reshape(-1, 1, 2)
        rect = cv2.undistortPoints(pts, self.K, self.dist.reshape(1, -1), P=self.K)
        return rect.reshape(-1, 2)

    def resumen(self) -> str:
        estado = "OK" if self.calidad_aceptable else "POBRE"
        return (
            f"[{self.camera}] {self.image_size[0]}×{self.image_size[1]}, "
            f"{self.n_images} imágenes"
            + (f" (+{self.n_descartadas} descartadas)" if self.n_descartadas else "")
            + f", RMS {self.rms:.3f} px ({estado}), "
            f"FOV {self.fov_h_deg:.1f}° H × {self.fov_v_deg:.1f}° V"
        )


def _coherencia(residual: np.ndarray, spec: ChessboardSpec) -> float:
    """Cuánto se parecen los residuales de esquinas vecinas, en `[-1, 1]`.

    Es lo que distingue las dos causas de un RMS alto, que piden arreglos
    opuestos:

    - **Cerca de 0**: el error es aleatorio de esquina a esquina. Desenfoque,
      trepidación, ruido del sensor. Se arregla con más luz y sujeción firme.
    - **Cerca de +1**: el error es sistemático — esquinas vecinas se desvían en
      la misma dirección. El patrón observado no es el patrón que se le está
      diciendo al ajuste que es: **tablero doblado**, o dimensiones del patrón
      mal declaradas. Más luz no arregla nada.

    Se mide como el coseno medio entre el vector de residual de cada esquina y
    el de su vecina en la misma fila.
    """
    R = np.asarray(residual, dtype=np.float64).reshape(spec.rows, spec.cols, 2)
    a = R[:, :-1, :].reshape(-1, 2)
    b = R[:, 1:, :].reshape(-1, 2)
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    m = (na > 1e-9) & (nb > 1e-9)
    if not m.any():
        return 0.0
    return float(np.mean(np.sum(a[m] * b[m], axis=1) / (na[m] * nb[m])))


def _errores_por_vista(objs, ips, K, dist, rvecs, tvecs, spec):
    errores, coherencias = [], []
    for objeto, imagen, rvec, tvec in zip(objs, ips, rvecs, tvecs):
        proyectado, _ = cv2.projectPoints(objeto, rvec, tvec, K, dist)
        obs = np.asarray(imagen, dtype=np.float64).reshape(-1, 2)
        pro = np.asarray(proyectado, dtype=np.float64).reshape(-1, 2)
        residual = obs - pro
        errores.append(float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))))
        coherencias.append(_coherencia(residual, spec))
    return np.array(errores), np.array(coherencias)


def calibrate(
    puntos_imagen: list[np.ndarray],
    spec: ChessboardSpec,
    image_size: tuple[int, int],
    camera: str = "cam",
    *,
    rechazar_atipicas: bool = True,
) -> CameraIntrinsics:
    """Ajusta los intrínsecos a partir de las esquinas detectadas.

    Args:
        puntos_imagen: una entrada por vista, cada una `(N, 1, 2)` float32.
        spec: el tablero usado, para generar los puntos 3D.
        image_size: `(ancho, alto)` en píxeles.
        camera: nombre, sólo para etiquetar el resultado.

    Raises:
        ValueError: con menos de 5 vistas. Con pocas vistas el ajuste converge
            a algo, pero a algo que no describe el lente.
    """
    if len(puntos_imagen) < 5:
        raise ValueError(
            f"Hacen falta al menos 5 vistas para calibrar; hay {len(puntos_imagen)}. "
            "Lo recomendable son 20, repartidas por todo el cuadro y con "
            "inclinaciones distintas."
        )

    objp = spec.object_points()
    # Contrato de forma: (N,1,2) float32. Ver board._normalizar.
    puntos_imagen = [
        np.asarray(p, dtype=np.float32).reshape(-1, 1, 2) for p in puntos_imagen
    ]
    puntos_objeto = [objp for _ in puntos_imagen]

    rms, K, dist, _rvecs, _tvecs = cv2.calibrateCamera(
        puntos_objeto, puntos_imagen, image_size, None, None
    )

    # Rechazo iterativo de vistas atípicas.
    #
    # Un frame movido no es "una vista algo peor": es la observación de un
    # tablero deformado por el movimiento, y arrastra el ajuste entero. Basta
    # con que 4 de 20 estén movidas para que el RMS pase de 0.97 a 2.94 px.
    descartadas: list[int] = []
    if rechazar_atipicas:
        vivos = list(range(len(puntos_imagen)))
        for _ in range(5):
            errs, _ = _errores_por_vista(
                [objp] * len(vivos),
                [puntos_imagen[i] for i in vivos],
                K, dist, _rvecs, _tvecs, spec,
            )
            umbral = max(ATIPICA_MINIMO_PX,
                         ATIPICA_FACTOR_MEDIANA * float(np.median(errs)))
            malas = [vivos[j] for j, e in enumerate(errs) if e > umbral]
            if not malas:
                break
            quedan = [i for i in vivos if i not in malas]
            if len(quedan) < MINIMO_VISTAS_TRAS_RECHAZO:
                break
            vivos = quedan
            descartadas.extend(malas)
            rms, K, dist, _rvecs, _tvecs = cv2.calibrateCamera(
                [objp] * len(vivos), [puntos_imagen[i] for i in vivos],
                image_size, None, None,
            )
        puntos_imagen = [puntos_imagen[i] for i in vivos]
        puntos_objeto = [objp] * len(puntos_imagen)

    # Error por vista, para poder señalar capturas malas.
    #
    # Se calcula con numpy y no con cv2.norm: cv2.norm exige que ambos arrays
    # tengan el MISMO tipo y número de canales, y los detectores devuelven
    # formas distintas según la versión de OpenCV. Reordenar a (N,2) elimina
    # esa clase de fallo por completo.
    errores, coherencias = _errores_por_vista(
        puntos_objeto, puntos_imagen, K, dist, _rvecs, _tvecs, spec
    )
    errores = list(errores)
    coherencias = list(coherencias)

    return CameraIntrinsics(
        camera=camera,
        image_size=(int(image_size[0]), int(image_size[1])),
        K=np.asarray(K, dtype=np.float64),
        dist=np.asarray(dist, dtype=np.float64).ravel(),
        rms=float(rms),
        n_images=len(puntos_imagen),
        n_descartadas=len(descartadas),
        per_view_errors=np.array(errores),
        residual_coherence=float(np.mean(coherencias)) if coherencias else 0.0,
        board=spec.describe(),
        fecha=_dt.date.today().isoformat(),
    )


def diagnosticar(
    puntos_imagen: list[np.ndarray],
    image_size: tuple[int, int],
    rms: float | None = None,
    coherencia: float | None = None,
) -> list[str]:
    """Explica POR QUÉ una calibración salió como salió.

    Un RMS alto no dice qué hacer distinto. Estas comprobaciones sí.
    Devuelve una lista de hallazgos en texto, el primero el más importante.
    """
    hallazgos: list[str] = []
    W, H = image_size

    ext = np.array([corner_extent(np.asarray(v), image_size) for v in puntos_imagen])
    cen = np.array([corner_centroid(np.asarray(v)) for v in puntos_imagen])

    # 1. Tamaño del tablero: la causa nº1 de una focal indeterminada.
    if ext.max() < EXTENT_MINIMO:
        hallazgos.append(
            f"**El tablero es demasiado pequeño en el cuadro**: ocupa entre el "
            f"{ext.min() * 100:.0f} % y el {ext.max() * 100:.0f} % del ancho, y "
            f"hace falta al menos el {EXTENT_MINIMO * 100:.0f} % "
            f"(objetivo {EXTENT_OBJETIVO * 100:.0f} %). Con el tablero tan lejos "
            f"la focal queda sin determinar por mucho que baje el RMS. "
            f"ACERCAR LA CÁMARA O EL TABLERO — es el arreglo con diferencia más "
            f"importante."
        )
    elif ext.mean() < EXTENT_OBJETIVO:
        hallazgos.append(
            f"El tablero queda algo pequeño: media del {ext.mean() * 100:.0f} % "
            f"del ancho, objetivo {EXTENT_OBJETIVO * 100:.0f} %. Acercarlo mejora "
            f"la estimación de la focal."
        )

    # 2. Variedad de distancias.
    if ext.max() / max(ext.min(), 1e-6) < 1.6:
        hallazgos.append(
            "Todas las vistas están a distancias parecidas. Alternar cerca y "
            "lejos separa la focal de la distancia al tablero."
        )

    # 3. Cobertura del cuadro: la distorsión de los bordes sólo se estima si
    #    el tablero pasa por los bordes.
    rx = (cen[:, 0].max() - cen[:, 0].min()) / W
    ry = (cen[:, 1].max() - cen[:, 1].min()) / H
    if rx < 0.5 or ry < 0.5:
        hallazgos.append(
            f"El tablero no recorre el cuadro (rango {rx * 100:.0f} % en X, "
            f"{ry * 100:.0f} % en Y). Sin vistas en los bordes, la distorsión "
            f"radial no se estima bien."
        )

    # 4. RMS alto con tamaño suficiente: el problema son las esquinas. La
    #    coherencia del residual dice CUÁL de las dos causas es, y piden
    #    arreglos opuestos.
    if rms is not None and rms > RMS_ACEPTABLE_PX and ext.max() >= EXTENT_MINIMO:
        if coherencia is not None and coherencia >= COHERENCIA_SISTEMATICA:
            hallazgos.insert(0, (
                f"**El error es SISTEMÁTICO, no ruido** (coherencia "
                f"{coherencia:+.2f}, por encima de {COHERENCIA_SISTEMATICA:+.2f}): "
                f"las esquinas vecinas se desvían juntas, así que el patrón "
                f"observado no es plano-y-quieto como supone el ajuste. Dos "
                f"causas producen esta firma y no se distinguen por los "
                f"números:\n"
                f"     (a) **el tablero no está plano** — pegarlo a una "
                f"superficie rígida, sin ondas ni burbujas;\n"
                f"     (b) **se movió durante la exposición** — con obturador "
                f"rodante el movimiento cizalla la imagen; apoyar el tablero en "
                f"un soporte, esperar a que quede quieto, y más luz para acortar "
                f"la exposición.\n"
                f"     Para saber cuál es: repetir con --save-frames y MIRAR las "
                f"imágenes. Se ve a simple vista."
            ))
        elif coherencia is not None:
            hallazgos.append(
                f"RMS de {rms:.2f} px con residual poco estructurado "
                f"(coherencia {coherencia:+.2f}): el error es aleatorio, típico "
                f"de desenfoque o trepidación. Más luz, sujetar firme, y "
                f"comprobar que la cámara enfoca a esa distancia."
            )
        else:
            hallazgos.append(
                f"RMS de {rms:.2f} px con tablero de tamaño suficiente: las "
                f"esquinas están mal localizadas. Tablero doblado, imágenes "
                f"movidas, o reflejos."
            )

    if not hallazgos:
        hallazgos.append("Sin problemas detectados en la geometría de las vistas.")
    return hallazgos


def resumen_vistas(
    puntos_imagen: list[np.ndarray], image_size: tuple[int, int]
) -> dict:
    """Estadísticas de las vistas, para el informe."""
    ext = np.array([corner_extent(np.asarray(v), image_size) for v in puntos_imagen])
    cen = np.array([corner_centroid(np.asarray(v)) for v in puntos_imagen])
    W, H = image_size
    return {
        "n": len(puntos_imagen),
        "extent_min": float(ext.min()),
        "extent_max": float(ext.max()),
        "extent_med": float(ext.mean()),
        "rango_x": float((cen[:, 0].max() - cen[:, 0].min()) / W),
        "rango_y": float((cen[:, 1].max() - cen[:, 1].min()) / H),
    }


def guardar_puntos(
    puntos_imagen: list[np.ndarray],
    spec: ChessboardSpec,
    image_size: tuple[int, int],
    camera: str,
    ruta: str | Path,
) -> Path:
    """Guarda las esquinas capturadas ANTES de calibrar.

    Capturar 20 vistas cuesta diez minutos de trabajo manual; calibrar cuesta
    segundos. Persistir las esquinas primero convierte cualquier fallo
    posterior en un reintento de segundos en vez de repetir la sesión entera.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        ruta,
        puntos=np.stack([np.asarray(p, np.float32).reshape(-1, 1, 2)
                         for p in puntos_imagen]),
        cols=spec.cols,
        rows=spec.rows,
        square_mm=spec.square_mm,
        image_size=np.array(image_size, dtype=np.int32),
        camera=camera,
    )
    return ruta


def cargar_puntos(
    ruta: str | Path,
) -> tuple[list[np.ndarray], ChessboardSpec, tuple[int, int], str]:
    """Lee lo guardado por `guardar_puntos`."""
    d = np.load(Path(ruta), allow_pickle=False)
    spec = ChessboardSpec(
        cols=int(d["cols"]), rows=int(d["rows"]), square_mm=float(d["square_mm"])
    )
    tam = tuple(int(v) for v in d["image_size"])
    puntos = [p for p in d["puntos"]]
    camera = str(d["camera"]) if "camera" in d else "cam"
    return puntos, spec, (tam[0], tam[1]), camera


def escribir_reporte(
    intr: CameraIntrinsics,
    ruta: str | Path,
    notas: str = "",
    puntos_imagen: list[np.ndarray] | None = None,
) -> Path:
    """Escribe el `report.md` que exige docs/calibration.md.

    Una calibración sin su residual documentado no es utilizable como
    referencia y no puede citarse en la tesis.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)

    peor = ""
    if intr.per_view_errors.size:
        idx = int(np.argmax(intr.per_view_errors))
        peor = (
            f"- Peor vista: #{idx}, {intr.per_view_errors[idx]:.3f} px\n"
            f"- Mejor vista: #{int(np.argmin(intr.per_view_errors))}, "
            f"{intr.per_view_errors.min():.3f} px\n"
        )

    veredicto = (
        "Calibración **aceptable**."
        if intr.calidad_aceptable
        else f"**Calibración pobre**: el RMS supera {RMS_ACEPTABLE_PX} px."
    )

    diagnostico = ""
    if puntos_imagen:
        st = resumen_vistas(puntos_imagen, intr.image_size)
        lineas = diagnosticar(
            puntos_imagen, intr.image_size, intr.rms, intr.residual_coherence
        )
        diagnostico = (
            "\n## Diagnóstico de las vistas\n\n"
            f"- Tamaño del tablero en el cuadro: "
            f"{st['extent_min'] * 100:.0f} % – {st['extent_max'] * 100:.0f} % "
            f"del ancho (media {st['extent_med'] * 100:.0f} %; objetivo "
            f"{EXTENT_OBJETIVO * 100:.0f} %)\n"
            f"- Recorrido del centro del tablero: {st['rango_x'] * 100:.0f} % en X, "
            f"{st['rango_y'] * 100:.0f} % en Y\n"
            f"- Coherencia del residual: {intr.residual_coherence:+.2f} "
            f"(0 = ruido aleatorio, +1 = error sistemático)\n\n"
            + "\n".join(f"{i}. {h}" for i, h in enumerate(lineas, 1))
            + "\n"
        )

    # Un centro óptico lejos del centro de la imagen delata un ajuste mal
    # condicionado, aunque el RMS no lo diga.
    cx, cy = float(intr.K[0, 2]), float(intr.K[1, 2])
    desvio_cx = abs(cx - intr.image_size[0] / 2) / intr.image_size[0]
    desvio_cy = abs(cy - intr.image_size[1] / 2) / intr.image_size[1]
    aviso_centro = ""
    if desvio_cx > 0.10 or desvio_cy > 0.10:
        aviso_centro = (
            f"\n> **Aviso**: el centro óptico salió en ({cx:.0f}, {cy:.0f}), a "
            f"{desvio_cx * 100:.0f} % / {desvio_cy * 100:.0f} % del centro de la "
            f"imagen. En una cámara normal debería quedar cerca del centro; una "
            f"desviación así indica un ajuste mal condicionado, casi siempre por "
            f"tablero pequeño o poca variedad de vistas.\n"
        )

    razon_fxfy = abs(intr.fx - intr.fy) / max(intr.fx, intr.fy)
    if razon_fxfy > 0.02:
        aviso_centro += (
            f"\n> **Aviso**: fx y fy difieren un {razon_fxfy * 100:.1f} %. Con "
            f"píxeles cuadrados deberían coincidir; una diferencia así es otro "
            f"síntoma de ajuste mal condicionado.\n"
        )

    ruta.write_text(
        f"""# Calibración intrínseca — {intr.camera}

- Fecha: {intr.fecha}
- Resolución: {intr.image_size[0]}×{intr.image_size[1]}
- Patrón: {intr.board}
- Vistas usadas: {intr.n_images}

## Resultado

- **RMS de reproyección: {intr.rms:.3f} px**
- fx = {intr.fx:.2f}, fy = {intr.fy:.2f}
- cx = {intr.K[0, 2]:.2f}, cy = {intr.K[1, 2]:.2f}
- Distorsión: {", ".join(f"{v:.5f}" for v in intr.dist)}

{peor}
{veredicto}
{aviso_centro}{diagnostico}

## Campo de visión derivado

- Horizontal: **{intr.fov_h_deg:.1f}°**
- Vertical: **{intr.fov_v_deg:.1f}°**
- Cobertura vertical: **{intr.cobertura_vertical_por_metro:.3f} · d**

### Distancia mínima para que una persona quepa entera

| Objetivo | Cámara a 0.98 m | Cámara a 1.10 m |
|---|---|---|
| De pie (1.80 m) | {intr.distancia_minima(1.80, 0.98):.2f} m | {intr.distancia_minima(1.80, 1.10):.2f} m |
| Brazos en alto (2.20 m) | {intr.distancia_minima(2.20, 0.98):.2f} m | {intr.distancia_minima(2.20, 1.10):.2f} m |

{notas}
""",
        encoding="utf-8",
    )
    return ruta

"""Esqueleto 3D del operador en el marco del Robotat, a partir de una sesion grabada.

Junta tres cosas que ya se graban con `--grabar-hd`:

* **La forma del cuerpo.** MediaPipe da, ademas del esqueleto 2D, uno 3D en
  metros (`pose_world_landmarks`): origen en el centro de la cadera, `x` a la
  derecha de la imagen, `y` hacia abajo y `z` alejandose de la camara. Se
  recalcula aqui sobre el video HD de la camara activa (`camN_hd.mkv`), porque
  en vivo no se guarda.
* **Hacia donde mira esa camara.** Las PTZ siguen al operador, asi que la
  camara activa mira desde su poste (`escena_robotat.json`) hacia el. Con eso,
  el `z` de MediaPipe es la direccion poste -> operador en el suelo del
  Robotat y el `x`, la perpendicular.
* **Donde esta.** El marker 65 va en una mano: el esqueleto se traslada para
  que esa muneca caiga sobre el marker, con los pies en el suelo.

Es una reconstruccion con **una** camara cada vez, no una triangulacion: la
forma y los gestos son los de MediaPipe; la orientacion depende de que las
posiciones de las camaras del JSON sean buenas (son aproximadas).

Uso, desde la raiz del repositorio:

    python .\\external\\gesture_detection\\reconstruir_cuerpo.py results\\captures\\control_camara_dron1\\2026-10-31\\sesion_110018

Deja `cuerpo3d.npz` en la carpeta de la sesion: `t_unix` (N), `lm` (N x 33 x 3,
en metros del Robotat), `vis` (N x 33), `camara` (N) y `conexiones`. Lo usan
`editar_video_resumen.py` (vista 3D) y `controllers/shared/exportar_vuelo_matlab.py`.
"""

from __future__ import annotations

import argparse
import bisect
import sys
from pathlib import Path

import cv2
import numpy as np

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from grabar_camaras_hd import buscar_ffmpeg  # noqa: E402
from renderizar_sesion_hd import FuenteHD, _ffprobe, marcas_de_tiempo  # noqa: E402
from visualization.escena_robotat import cargar_config, cuerpo_desde_marker, marker_de_la_sesion  # noqa: E402
from visualization.registro_render import NOMBRE as REGISTRO, leer  # noqa: E402

FPS = 15.0
ANCHO_DETECCION = 960
NOMBRE = "cuerpo3d.npz"
MUNECA = {"izq": 15, "der": 16}
PIES = (27, 28, 29, 30, 31, 32)
#: Suavizado temporal de cada landmark (0 = nada, 1 = congelado).
SUAVIZADO = 0.5
ALTURA_CADERA_M = 0.95


def ejes_de_camara(camara_xy, cuerpo_xy) -> tuple[np.ndarray, np.ndarray]:
    """`(derecha, adelante)` de la imagen en el suelo del Robotat.

    La camara mira de su poste al operador: `adelante` es esa direccion y
    `derecha` (el `x` de la imagen) la perpendicular hacia la derecha.
    """
    f = np.asarray(cuerpo_xy, float) - np.asarray(camara_xy, float)
    n = np.linalg.norm(f)
    f = f / n if n > 1e-6 else np.array([1.0, 0.0])
    return np.array([f[1], -f[0]]), f


def al_robotat(mundo: np.ndarray, derecha, adelante) -> np.ndarray:
    """Landmarks de MediaPipe (x der., y abajo, z lejos) a ejes del Robotat, sin trasladar.

    No se compensa que las camaras miren hacia abajo: MediaPipe ya entrega el
    cuerpo casi vertical. Medido en la sesion 2026-10-31 11:00, la espalda
    queda a 6.6 grados de la vertical (mediana) sin compensar, y a 14.6 y 25.3
    compensando el cabeceo de la camara en un sentido u otro.
    """
    x, y, z = mundo[:, 0:1], mundo[:, 1:2], mundo[:, 2:3]
    horizontal = x * np.append(derecha, 0.0) + z * np.append(adelante, 0.0)
    return horizontal + (-y) * np.array([0.0, 0.0, 1.0])


def colocar(rel: np.ndarray, vis: np.ndarray, marker, mano: str) -> np.ndarray:
    """Traslada `rel` (centrado en la cadera) para que la muneca de `mano` caiga en el marker.

    La altura sale de los pies si se ven (apoyados en el suelo) y si no, de
    `ALTURA_CADERA_M`; la posicion horizontal, del marker.
    """
    pies = [i for i in PIES if vis[i] > 0.5]
    altura = -rel[pies, 2].min() if pies else ALTURA_CADERA_M
    cadera = np.array([marker[0], marker[1], altura]) - np.array([*rel[MUNECA[mano], :2], 0.0])
    return rel + cadera


def mano_del_marker(muestras) -> str:
    """Que mano lleva el marker: la muneca cuya altura se parece mas a la del marker."""
    errores = {m: [] for m in MUNECA}
    for rel, vis, marker in muestras:
        pies = [i for i in PIES if vis[i] > 0.5]
        altura = -rel[pies, 2].min() if pies else ALTURA_CADERA_M
        for m, i in MUNECA.items():
            if vis[i] > 0.5:
                errores[m].append(abs(altura + rel[i, 2] - marker[2]))
    return min(errores, key=lambda m: np.median(errores[m]) if errores[m] else np.inf)


def main() -> int:
    parser = argparse.ArgumentParser(description="Esqueleto 3D del operador en el marco del Robotat.")
    parser.add_argument("carpeta", type=Path)
    parser.add_argument("--fps", type=float, default=FPS)
    parser.add_argument("--desfase", type=float, default=-0.10,
                        help="segundos que el HD va por detras del registro (el que estima renderizar_sesion_hd)")
    args = parser.parse_args()

    carpeta = args.carpeta.resolve()
    dia, sesion = carpeta.parent.name, carpeta.name
    inicio, poses, estados, _ = leer(carpeta / REGISTRO)
    marker = marker_de_la_sesion(PROJECT_DIR / "results" / "data" / "control_camara_dron1" / dia / f"{sesion}.csv")
    if marker is None:
        print("ERROR: esta sesion no tiene el marker 65 en su CSV.", file=sys.stderr)
        return 1
    camaras_ip = cargar_config()["camaras_ip"]
    if not isinstance(camaras_ip, dict):
        print("ERROR: escena_robotat.json no dice que camara esta en cada posicion.", file=sys.stderr)
        return 1
    cuerpo = cuerpo_desde_marker(marker)
    ffprobe = _ffprobe(buscar_ffmpeg())
    fuentes = {n: FuenteHD(carpeta / f"{n}_hd.mkv", marcas_de_tiempo(ffprobe, carpeta / f"{n}_hd.mkv"))
               for n in camaras_ip if (carpeta / f"{n}_hd.mkv").is_file()}

    from pose.detector import POSE_CONNECTIONS, PoseDetector
    detectores = {n: PoseDetector() for n in fuentes}       # uno por camara: el seguimiento no se mezcla
    t_estados = [e["t"] for e in estados]
    t0, t1 = estados[0]["t"], estados[-1]["t"]

    crudos = []                                              # (t, camara, rel, vis, marker)
    try:
        for k in range(int((t1 - t0) * args.fps)):
            t = t0 + k / args.fps
            i = bisect.bisect_right(t_estados, t) - 1
            cam = estados[i].get("activa") if i >= 0 else None
            frames = {n: f.en(t + args.desfase) for n, f in fuentes.items()}
            m, b = marker.en(t), cuerpo.en(t)
            if cam not in fuentes or frames.get(cam) is None or m is None or b is None:
                continue
            img = frames[cam]
            img = cv2.resize(img, (ANCHO_DETECCION, int(img.shape[0] * ANCHO_DETECCION / img.shape[1])))
            _, mundo = detectores[cam].process_full(img)
            if mundo is None:
                continue
            arr = np.array([[p.x, p.y, p.z] for p in mundo])
            vis = np.array([p.visibility for p in mundo])
            derecha, adelante = ejes_de_camara(camaras_ip[cam][:2], b[0][:2])
            crudos.append((t, cam, al_robotat(arr, derecha, adelante), vis, m[0]))
            if k % int(args.fps * 15) == 0:
                print(f"  {t - t0:5.0f} s de {t1 - t0:.0f} s", flush=True)
    finally:
        for f in fuentes.values():
            f.cerrar()
        for d in detectores.values():
            d.close()
    if not crudos:
        print("ERROR: MediaPipe no encontro a nadie en la camara activa.", file=sys.stderr)
        return 1

    mano = mano_del_marker([(rel, vis, m) for _, _, rel, vis, m in crudos])
    lm = np.stack([colocar(rel, vis, m, mano) for _, _, rel, vis, m in crudos])
    for k in range(1, len(lm)):                              # suavizado exponencial, sin saltar huecos
        if crudos[k][0] - crudos[k - 1][0] < 2.5 / args.fps and crudos[k][1] == crudos[k - 1][1]:
            lm[k] = SUAVIZADO * lm[k - 1] + (1 - SUAVIZADO) * lm[k]
    salida = carpeta / NOMBRE
    np.savez_compressed(salida, t_unix=np.array([c[0] for c in crudos]), lm=lm,
                        vis=np.stack([c[3] for c in crudos]),
                        camara=np.array([c[1] for c in crudos]),
                        conexiones=np.array(sorted(POSE_CONNECTIONS)), mano=mano)
    print(f"{len(lm)} poses ({len(lm) / args.fps:.0f} s), marker en la mano {mano}: {salida}")
    return 0


def cargar(carpeta: Path):
    """`(t_unix, lm, vis, conexiones)` de `cuerpo3d.npz`, o `None` si no hay."""
    ruta = Path(carpeta) / NOMBRE
    if not ruta.is_file():
        return None
    d = np.load(ruta, allow_pickle=False)
    return d["t_unix"], d["lm"], d["vis"], d["conexiones"]


if __name__ == "__main__":
    raise SystemExit(main())

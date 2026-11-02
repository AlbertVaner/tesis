r"""Exporta un vuelo del Robotat (uno, dos o tres drones) a un `.mat` para MATLAB.

Junta en un solo archivo, en la misma linea de tiempo:

* cada dron (`results/data/dron_robotat/<dia>/dron_robotat_DronN_*.csv`):
  posicion del mocap, orientacion, posicion del EKF, objetivo, modo, bateria
  y sus eventos (despegue, aterrizaje, paro...);
* si el vuelo fue por gestos, el CSV del controlador por camara
  (`results/data/control_camara_dron1/<dia>/sesion_*.csv`): gesto, modo,
  comportamiento (SEGUIR, ORBITAR...), las ordenes de cada momento y la
  posicion del **marker 65**;
* si se reconstruyo (`external/gesture_detection/reconstruir_cuerpo.py`), el
  **esqueleto 3D** del operador: `rejilla.cuerpo` (T x 33 x 3) y
  `rejilla.cuerpo_conexiones`;
* una `rejilla` comun a 30 Hz con todo interpolado, lista para animar con
  `animar_vuelo_robotat.m` (junto a este script).

Que archivos van juntos
-----------------------
Se parte de un CSV de dron (por defecto el mas reciente) y se le juntan los
de los otros drones arrancados a menos de 60 s y el CSV de gestos que se
solapa en el tiempo. Cada CSV cuenta `t_s` desde que arranco el suyo; para
ponerlos en la misma linea de tiempo se usa la hora de pared `t_unix` de
cada fila. Los CSV anteriores al 2026-10-28 no la tienen: se reconstruye con
la hora del nombre del archivo, que solo tiene precision de 1 s (se avisa).

Uso, desde la raiz del repositorio:

    python .\controllers\shared\exportar_vuelo_matlab.py
    python .\controllers\shared\exportar_vuelo_matlab.py results\data\dron_robotat\2026-10-17\dron_robotat_Dron1_20261017_120709.csv
    python .\controllers\shared\exportar_vuelo_matlab.py <csv> --gestos results\data\control_camara_dron1\2026-10-17\sesion_124228.csv

Sale `results/data/dron_robotat/<dia>/vuelo_<HHMMSS>.mat`. En MATLAB:

    animar_vuelo_robotat('results/data/dron_robotat/<dia>/vuelo_<HHMMSS>.mat')
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[2]
DATOS_DRONES = PROJECT_DIR / "results" / "data" / "dron_robotat"
DATOS_GESTOS = PROJECT_DIR / "results" / "data" / "control_camara_dron1"

#: Drones de la misma sesion: los que arrancaron a menos de esto del primero.
MISMA_SESION_S = 60.0
FPS_REJILLA = 30.0
#: Un hueco de mocap mas largo que esto queda como NaN, no se interpola.
HUECO_MAX_S = 0.5
#: Cuanto se mantiene visible una orden en la rejilla.
ORDEN_VISIBLE_S = 4.0

_DRON = re.compile(r"dron_robotat_(Dron\d)_(\d{8}_\d{6})")


# ------------------------------------------------------------------ lectura


def _num(valor: str) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def leer_csv(ruta: Path) -> list[dict]:
    with Path(ruta).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def inicio_por_nombre(ruta: Path) -> float | None:
    """Hora de pared del arranque segun el nombre del archivo (precision 1 s)."""
    ruta = Path(ruta)
    m = _DRON.search(ruta.stem)
    if m:
        return datetime.strptime(m.group(2), "%Y%m%d_%H%M%S").timestamp()
    m = re.search(r"sesion_(\d{6})", ruta.stem)
    if m:
        try:
            dia = datetime.strptime(ruta.parent.name, "%Y-%m-%d")
        except ValueError:
            return None
        hora = datetime.strptime(m.group(1), "%H%M%S")
        return dia.replace(hour=hora.hour, minute=hora.minute, second=hora.second).timestamp()
    return None


def tiempos_unix(filas: list[dict], ruta: Path, avisos: list[str]) -> np.ndarray:
    """`t_unix` de cada fila; sin esa columna, inicio del nombre + `t_s`."""
    t_unix = np.array([_num(f.get("t_unix", "")) for f in filas])
    if len(filas) and np.isfinite(t_unix).all():
        return t_unix
    inicio = inicio_por_nombre(ruta)
    if inicio is None:
        raise ValueError(f"{Path(ruta).name}: sin t_unix ni hora en el nombre")
    avisos.append(f"{Path(ruta).name}: sin t_unix; hora reconstruida del nombre (+-1 s)")
    return inicio + np.array([_num(f.get("t_s", "")) for f in filas])


def _xyz(filas: list[dict], prefijo: str) -> np.ndarray:
    return np.array([[_num(f.get(f"{prefijo}_{e}", "")) for e in "xyz"] for f in filas]).reshape(-1, 3)


def _texto(filas: list[dict], campo: str) -> np.ndarray:
    return np.array([f.get(campo, "") or "" for f in filas], dtype=object)


def leer_dron(ruta: Path, avisos: list[str]) -> dict:
    filas = leer_csv(ruta)
    t = tiempos_unix(filas, ruta, avisos)
    evento = _texto(filas, "evento")
    muestra = evento == ""
    ev = ~muestra

    def col(campo):
        return np.array([_num(f.get(campo, "")) for f in filas])

    return {
        "nombre": _DRON.search(Path(ruta).stem).group(1),
        "archivo": str(Path(ruta).relative_to(PROJECT_DIR)) if Path(ruta).is_relative_to(PROJECT_DIR)
        else str(ruta),
        "t_unix": t[muestra],
        "pos": _xyz(filas, "mocap")[muestra],
        "yaw_deg": col("mocap_yaw_deg")[muestra],
        "roll_deg": col("roll_deg")[muestra],
        "pitch_deg": col("pitch_deg")[muestra],
        "ekf": _xyz(filas, "ekf")[muestra],
        "objetivo": _xyz(filas, "objetivo")[muestra],
        "bateria_v": col("bateria_v")[muestra],
        "modo": _texto(filas, "modo")[muestra],
        "eventos": {"t_unix": t[ev], "evento": evento[ev], "detalle": _texto(filas, "detalle")[ev]},
    }


def leer_gestos(ruta: Path, avisos: list[str]) -> dict:
    filas = leer_csv(ruta)
    t = tiempos_unix(filas, ruta, avisos)
    marker = _xyz(filas, "marker") if filas and "marker_x" in filas[0] else np.full((len(filas), 3), np.nan)
    return {
        "archivo": str(Path(ruta).relative_to(PROJECT_DIR)) if Path(ruta).is_relative_to(PROJECT_DIR)
        else str(ruta),
        "t_unix": t,
        "gesto": _texto(filas, "gesto"),
        "confirmado": np.array([_num(f.get("confirmado", "")) == 1 for f in filas]),
        "modo": _texto(filas, "modo"),
        "comportamiento": _texto(filas, "comportamiento"),
        "estado": _texto(filas, "estado"),
        "gesto_dinamico": _texto(filas, "gesto_dinamico"),
        "novedad": _texto(filas, "novedad"),
        "marker": marker,
    }


# --------------------------------------------------------- juntar la sesion


def drones_de_la_sesion(ruta: Path) -> list[Path]:
    """`ruta` y los CSV de otros drones arrancados a menos de `MISMA_SESION_S`."""
    ruta = Path(ruta)
    inicio = inicio_por_nombre(ruta)
    por_dron: dict[str, tuple[float, Path]] = {}
    for p in ruta.parent.glob("dron_robotat_Dron*_*.csv"):
        m = _DRON.search(p.stem)
        t = inicio_por_nombre(p)
        if not m or t is None or abs(t - inicio) > MISMA_SESION_S:
            continue
        delta = abs(t - inicio)
        if m.group(1) not in por_dron or delta < por_dron[m.group(1)][0]:
            por_dron[m.group(1)] = (delta, p)
    por_dron[_DRON.search(ruta.stem).group(1)] = (0.0, ruta)
    return [p for _, (_, p) in sorted(por_dron.items())]


def gestos_que_se_solapan(t0: float, t1: float, dia: str) -> Path | None:
    """CSV de gestos del mismo dia con mas tiempo en comun con `[t0, t1]`."""
    mejor = None
    for p in (DATOS_GESTOS / dia).glob("sesion_*.csv"):
        filas = leer_csv(p)
        if not filas:
            continue
        try:
            t = tiempos_unix(filas, p, [])
        except ValueError:
            continue
        comun = min(t1, np.nanmax(t)) - max(t0, np.nanmin(t))
        if comun > 1.0 and (mejor is None or comun > mejor[0]):
            mejor = (comun, p)
    return None if mejor is None else mejor[1]


# ------------------------------------------------------------------ rejilla


def interpolar(t_rejilla: np.ndarray, t: np.ndarray, valores: np.ndarray,
               hueco_max_s: float = HUECO_MAX_S) -> np.ndarray:
    """`valores` (N o N x k) en `t_rejilla`; NaN fuera de rango y en huecos largos."""
    valores = np.asarray(valores, dtype=float)
    plano = valores.ndim == 1
    v = valores.reshape(len(t), -1)
    salida = np.full((len(t_rejilla), v.shape[1]), np.nan)
    validos = np.isfinite(v).all(axis=1) & np.isfinite(t)
    if validos.sum() >= 2:
        tv, vv = t[validos], v[validos]
        orden = np.argsort(tv)
        tv, vv = tv[orden], vv[orden]
        for k in range(v.shape[1]):
            salida[:, k] = np.interp(t_rejilla, tv, vv[:, k], left=np.nan, right=np.nan)
        # Distancia a la muestra valida mas cercana: si es grande, es un hueco.
        i = np.clip(np.searchsorted(tv, t_rejilla), 1, len(tv) - 1)
        cerca = np.minimum(np.abs(t_rejilla - tv[i - 1]), np.abs(tv[i] - t_rejilla))
        salida[cerca > hueco_max_s] = np.nan
    return salida[:, 0] if plano else salida


def escalon(t_rejilla: np.ndarray, t: np.ndarray, valores: np.ndarray, vacio="") -> np.ndarray:
    """El ultimo valor registrado antes de cada instante (texto o lo que sea)."""
    salida = np.full(len(t_rejilla), vacio, dtype=object)
    if len(t) == 0:
        return salida
    orden = np.argsort(t)
    t, valores = t[orden], np.asarray(valores, dtype=object)[orden]
    i = np.searchsorted(t, t_rejilla, side="right") - 1
    salida[i >= 0] = valores[i[i >= 0]]
    return salida


def ultima_orden(t_rejilla: np.ndarray, t: np.ndarray, textos: np.ndarray) -> np.ndarray:
    """La orden mas reciente de los ultimos `ORDEN_VISIBLE_S`, o vacio."""
    hay = np.array([bool(x) for x in textos], dtype=bool)
    t, textos = t[hay], textos[hay]
    salida = escalon(t_rejilla, t, textos)
    previo = escalon(t_rejilla, t, t, vacio=-np.inf).astype(float)
    salida[t_rejilla - previo > ORDEN_VISIBLE_S] = ""
    return salida


def leer_cuerpo(ruta_gestos: Path) -> dict | None:
    """Esqueleto 3D de `reconstruir_cuerpo.py` para la sesion de `ruta_gestos`, si se reconstruyo.

    Vive en `results/captures/control_camara_dron1/<dia>/<sesion>/cuerpo3d.npz`.
    """
    ruta_gestos = Path(ruta_gestos)
    npz = (PROJECT_DIR / "results" / "captures" / "control_camara_dron1" / ruta_gestos.parent.name
           / ruta_gestos.stem / "cuerpo3d.npz")
    if not npz.is_file():
        return None
    d = np.load(npz, allow_pickle=False)
    return {"t_unix": d["t_unix"], "lm": d["lm"], "vis": d["vis"], "conexiones": d["conexiones"]}


def construir(drones: list[dict], gestos: dict | None, fps: float = FPS_REJILLA,
              cuerpo: dict | None = None) -> dict:
    """Todo junto, con `t` en segundos desde el primer dato y la rejilla comun."""
    inicios = [d["t_unix"].min() for d in drones if len(d["t_unix"])]
    finales = [d["t_unix"].max() for d in drones if len(d["t_unix"])]
    t0, t1 = min(inicios), max(finales)
    t_unix = np.arange(t0, t1, 1.0 / fps)
    t = t_unix - t0

    rejilla: dict = {"t": t, "nombres": np.array([d["nombre"] for d in drones], dtype=object)}
    rejilla["pos"] = np.stack([interpolar(t_unix, d["t_unix"], d["pos"]) for d in drones], axis=2)
    rejilla["yaw_deg"] = np.stack([interpolar(t_unix, d["t_unix"], d["yaw_deg"]) for d in drones], axis=1)
    rejilla["objetivo"] = np.stack([interpolar(t_unix, d["t_unix"], d["objetivo"], 2.0) for d in drones],
                                   axis=2)
    rejilla["modo_dron"] = np.stack([escalon(t_unix, d["t_unix"], d["modo"]) for d in drones], axis=1)
    eventos = np.concatenate([d["eventos"]["t_unix"] for d in drones]) if drones else np.array([])
    textos = np.concatenate([np.array([f"{d['nombre']}: {e}" for e in d["eventos"]["evento"]], dtype=object)
                             for d in drones]) if drones else np.array([], dtype=object)
    rejilla["evento"] = ultima_orden(t_unix, eventos, textos)

    salida = {"t0_unix": t0, "fps": fps, "rejilla": rejilla, "drones": {}}
    for d in drones:
        d = dict(d)
        d["t"] = d["t_unix"] - t0
        d["eventos"] = dict(d["eventos"], t=d["eventos"]["t_unix"] - t0)
        salida["drones"][d["nombre"]] = d

    if gestos is not None:
        tg = gestos["t_unix"]
        rejilla["marker"] = interpolar(t_unix, tg, gestos["marker"])
        gesto = np.array([g if c or g == "NO_GESTURE" else f"{g}?"
                          for g, c in zip(gestos["gesto"], gestos["confirmado"])], dtype=object)
        rejilla["gesto"] = escalon(t_unix, tg, gesto)
        rejilla["modo"] = escalon(t_unix, tg, gestos["modo"])
        rejilla["comportamiento"] = escalon(t_unix, tg, gestos["comportamiento"])
        # Solo las ordenes ("senalero -> DESPEGAR"), no los cambios de camara ni los rechazos.
        ordenes = np.array([" | ".join(x for x in str(n).split(" | ") if "->" in x)
                            for n in gestos["novedad"]], dtype=object)
        rejilla["orden"] = ultima_orden(t_unix, tg, ordenes)
        salida["gestos"] = dict(gestos, t=tg - t0)
    else:
        rejilla["marker"] = np.full((len(t), 3), np.nan)
        for campo in ("gesto", "modo", "comportamiento", "orden"):
            rejilla[campo] = np.full(len(t), "", dtype=object)
    if cuerpo is not None:
        # T x 33 x 3; los huecos (nadie a la vista) quedan en NaN.
        lm = cuerpo["lm"].reshape(len(cuerpo["t_unix"]), -1)
        rejilla["cuerpo"] = interpolar(t_unix, cuerpo["t_unix"], lm, 0.3).reshape(len(t), 33, 3)
        rejilla["cuerpo_conexiones"] = cuerpo["conexiones"] + 1        # indices de MATLAB
    return salida


# ------------------------------------------------------------------ salida


def _para_mat(valor):
    """dict -> struct, arrays de texto -> cell, lo demas tal cual."""
    if isinstance(valor, dict):
        return {k: _para_mat(v) for k, v in valor.items()}
    if isinstance(valor, np.ndarray) and valor.dtype == object:
        celda = np.empty(valor.shape, dtype=object)
        for i, x in np.ndenumerate(valor):
            celda[i] = "" if x is None else str(x)
        return celda
    return valor


def guardar(vuelo: dict, ruta: Path) -> Path:
    from scipy.io import savemat

    ruta.parent.mkdir(parents=True, exist_ok=True)
    savemat(str(ruta), {"vuelo": _para_mat(vuelo)}, long_field_names=True, do_compression=True)
    return ruta


def ultimo_csv_de_dron() -> Path | None:
    csvs = sorted(DATOS_DRONES.glob("*/dron_robotat_Dron*_*.csv"), key=lambda p: p.stat().st_mtime)
    return csvs[-1] if csvs else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta un vuelo del Robotat a .mat para MATLAB.")
    parser.add_argument("csv", nargs="?", type=Path,
                        help="un CSV de dron de la sesion; por defecto el mas reciente")
    parser.add_argument("--gestos", type=Path,
                        help="CSV del controlador por camara; por defecto el que se solapa en el tiempo")
    parser.add_argument("--sin-gestos", action="store_true")
    parser.add_argument("--fps", type=float, default=FPS_REJILLA)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()

    base = args.csv or ultimo_csv_de_dron()
    if base is None or not base.is_file() or not _DRON.search(base.stem):
        print("ERROR: hace falta un CSV dron_robotat_DronN_*.csv", file=sys.stderr)
        return 1
    avisos: list[str] = []
    rutas = drones_de_la_sesion(base)
    drones = [leer_dron(p, avisos) for p in rutas]
    drones = [d for d in drones if len(d["t_unix"])]
    if not drones:
        print("ERROR: los CSV no tienen muestras", file=sys.stderr)
        return 1
    print("Drones: " + ", ".join(f"{d['nombre']} ({Path(d['archivo']).name})" for d in drones))

    gestos = cuerpo = None
    if not args.sin_gestos:
        t0 = min(d["t_unix"].min() for d in drones)
        t1 = max(d["t_unix"].max() for d in drones)
        ruta_gestos = args.gestos or gestos_que_se_solapan(t0, t1, base.parent.name)
        if ruta_gestos is not None:
            gestos = leer_gestos(ruta_gestos, avisos)
            con_marker = np.isfinite(gestos["marker"]).all(axis=1).sum()
            print(f"Gestos: {Path(ruta_gestos).name} ({con_marker} muestras del marker 65)")
            cuerpo = leer_cuerpo(ruta_gestos)
            print(f"Esqueleto 3D: {len(cuerpo['t_unix'])} poses" if cuerpo is not None else
                  "Esqueleto 3D: no reconstruido (external/gesture_detection/reconstruir_cuerpo.py)")
        else:
            print("Gestos: ninguna sesion por camara se solapa con este vuelo")

    vuelo = construir(drones, gestos, args.fps, cuerpo)
    for aviso in avisos:
        print(f"  aviso: {aviso}")
    hora = datetime.fromtimestamp(vuelo["t0_unix"]).strftime("%H%M%S")
    salida = args.salida or base.parent / f"vuelo_{hora}.mat"
    guardar(vuelo, salida)
    print(f"Duracion: {vuelo['rejilla']['t'][-1]:.1f} s a {args.fps:g} Hz")
    print(f"MATLAB: {salida}")
    print(f"  animar_vuelo_robotat('{salida.as_posix()}')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

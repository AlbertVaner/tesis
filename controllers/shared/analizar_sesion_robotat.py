"""Gráficas en PDF y resumen de una sesión del controlador sobre el Robotat.

Cada CSV de `results/data/dron_robotat/<día>/` produce una carpeta
`results/graphs/dron_robotat/<día>/<sesión>/` con una figura PDF por tema y
un `00_resumen.txt` con las cifras que se miran siempre (dispersión del hover,
sobrepaso del despegue, empuje, batería, calidad del mocap). El controlador
la genera solo al cerrar cada sesión; este módulo también sirve a mano:

    .\\.venv\\Scripts\\python.exe .\\controllers\\shared\\analizar_sesion_robotat.py            (última sesión)
    .\\.venv\\Scripts\\python.exe .\\controllers\\shared\\analizar_sesion_robotat.py ruta.csv
    .\\.venv\\Scripts\\python.exe .\\controllers\\shared\\analizar_sesion_robotat.py --todas   (todas las del día)
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import cm  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401  (registra la proyeccion 3d)

PROJECT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_DIR / "results" / "data" / "dron_robotat"
GRAPH_DIR = PROJECT_DIR / "results" / "graphs" / "dron_robotat"

#: Modos en los que el dron no vuela: fuera de las figuras de trayectoria.
MODOS_EN_TIERRA = ("SIN_CONECTAR", "PREFLIGHT", "LISTO", "EN_TIERRA", "EMERGENCIA")
#: Eventos que se marcan con una línea vertical en las gráficas temporales.
EVENTOS_MARCADOS = {
    "TAKEOFF": ("Despegue", "tab:green"),
    "LAND": ("Aterrizar", "tab:blue"),
    "LANDED": ("En tierra", "tab:gray"),
    "LAND_SEGURIDAD": ("Aterrizaje de seguridad", "tab:orange"),
    "EMERGENCIA": ("Emergencia", "tab:red"),
    "GO_TO": ("Paso", "tab:purple"),
    "FLUIDO_INICIO": ("Fluido", "tab:cyan"),
}


def session_day(path: Path) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", path.stem)
    return "-".join(match.groups()) if match else "sin_fecha"


def session_output_dir(path: Path) -> Path:
    return GRAPH_DIR / session_day(path) / path.stem


def _num(row: dict, key: str) -> float | None:
    value = row.get(key, "")
    if value in ("", None):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def cargar(source: Path) -> tuple[list[dict], list[dict]]:
    """Filas de muestra (evento vacío) y filas de evento, con números ya convertidos."""
    samples: list[dict] = []
    events: list[dict] = []
    with source.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {k: (_num(raw, k) if k not in ("evento", "detalle", "modo") else raw.get(k, "")) for k in raw}
            if row.get("t_s") is None:
                continue
            (events if row["evento"] else samples).append(row)
    return samples, events


def _serie(samples: list[dict], key: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for row in samples:
        value = row.get(key)
        if value is not None:
            xs.append(row["t_s"])
            ys.append(value)
    return xs, ys


def _marcar_eventos(ax, events: list[dict]) -> None:
    vistos: set[str] = set()
    for event in events:
        nombre = event["evento"]
        if nombre not in EVENTOS_MARCADOS:
            continue
        etiqueta, color = EVENTOS_MARCADOS[nombre]
        ax.axvline(event["t_s"], color=color, alpha=0.35, linewidth=1,
                   label=etiqueta if nombre not in vistos else None)
        vistos.add(nombre)


def _guardar(figure, output: Path, nombre: str) -> Path:
    path = output / nombre
    figure.savefig(path, format="pdf", bbox_inches="tight")
    plt.close(figure)
    return path


def ventana_de_vuelo(samples, events, margen_s: float = 5.0) -> tuple[float, float]:
    """(t inicio, t fin) alrededor del vuelo: del despegue al aterrizaje con margen.

    Sin despegue se devuelve toda la sesión. Sirve para que veinte minutos de
    dron en tierra tras aterrizar no aplasten la parte que interesa.
    """
    fin_sesion = samples[-1]["t_s"] if samples else 0.0
    despegues = [e["t_s"] for e in events if e["evento"] == "TAKEOFF"]
    if not despegues:
        return 0.0, fin_sesion
    finales = [e["t_s"] for e in events if e["evento"] in ("LANDED", "EMERGENCIA") and e["t_s"] > despegues[0]]
    fin = finales[-1] if finales else fin_sesion
    return max(0.0, despegues[0] - margen_s), min(fin_sesion, fin + margen_s)


def figura_altura(samples, events, output: Path) -> Path:
    figure, ax = plt.subplots(figsize=(11, 4.5))
    for key, etiqueta, estilo in (("mocap_z", "mocap", "-"), ("ekf_z", "EKF", "--"), ("objetivo_z", "objetivo", ":")):
        xs, ys = _serie(samples, key)
        if xs:
            ax.plot(xs, ys, estilo, label=etiqueta)
    _marcar_eventos(ax, events)
    ax.set_xlim(*ventana_de_vuelo(samples, events))
    ax.set_xlabel("t (s)")
    ax.set_ylabel("z (m)")
    ax.set_title("Altura: mocap, EKF y objetivo")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=8)
    return _guardar(figure, output, "01_altura.pdf")


def figura_trayectoria(samples, output: Path, radio_max: float | None) -> Path:
    figure, ax = plt.subplots(figsize=(6.5, 6.5))
    xs, _ = _serie(samples, "mocap_x")
    _, ys = _serie(samples, "mocap_y")
    n = min(len(xs), len(ys))
    if n:
        ax.plot(xs[:n], ys[:n], "-", linewidth=1, label="mocap")
        ax.plot(xs[0], ys[0], "go", label="inicio")
        ax.plot(xs[n - 1], ys[n - 1], "rs", label="fin")
    ox, _ = _serie(samples, "objetivo_x")
    _, oy = _serie(samples, "objetivo_y")
    m = min(len(ox), len(oy))
    if m:
        ax.plot(ox[:m], oy[:m], ":", linewidth=1, label="objetivo")
    origen = next((row for row in samples if row.get("objetivo_x") is not None), None)
    if origen is not None and radio_max:
        circulo = plt.Circle((origen["objetivo_x"], origen["objetivo_y"]), radio_max,
                             fill=False, linestyle="--", color="tab:red", alpha=0.5, label="geocerca")
        ax.add_patch(circulo)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title("Trayectoria horizontal")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _guardar(figure, output, "02_trayectoria_xy.pdf")


def figura_error_y_mocap(samples, events, output: Path) -> Path:
    figure, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    xs, ys = _serie(samples, "error_ekf_mocap_m")
    ax1.plot(xs, ys, label="EKF − mocap")
    ax1.axhline(0.15, color="tab:red", linestyle="--", alpha=0.5, label="corte 0.15 m")
    _marcar_eventos(ax1, events)
    ax1.set_ylabel("error (m)")
    ax1.set_title("Error EKF–mocap y calidad del flujo del Robotat")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="upper right")
    xs, ys = _serie(samples, "mocap_frames_hz")
    ax2.plot(xs, ys, label="frames/s")
    xs, ys = _serie(samples, "mocap_hueco_max_s")
    ax2b = ax2.twinx()
    ax2b.plot(xs, [v * 1000 for v in ys], color="tab:orange", alpha=0.7, label="hueco máx (ms)")
    xs, ys = _serie(samples, "mocap_congelado")
    if xs and any(ys):
        ax2.fill_between(xs, 0, [50 * v for v in ys], color="tab:red", alpha=0.2, label="congelado")
    ax2.set_xlabel("t (s)")
    ax2.set_ylabel("frames/s")
    ax2b.set_ylabel("hueco (ms)")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8, loc="upper left")
    ax2b.legend(fontsize=8, loc="upper right")
    return _guardar(figure, output, "03_error_ekf_y_mocap.pdf")


def figura_bateria_empuje(samples, events, output: Path) -> Path:
    figure, ax = plt.subplots(figsize=(11, 4.5))
    xs, ys = _serie(samples, "bateria_v")
    ax.plot(xs, ys, color="tab:green", label="batería (V)")
    ax.axhline(3.0, color="tab:red", linestyle="--", alpha=0.5, label="aterrizaje 3.0 V")
    ax.set_ylabel("V")
    ax.set_xlabel("t (s)")
    xs, ys = _serie(samples, "empuje_cmd")
    if xs and any(ys):
        axb = ax.twinx()
        axb.plot(xs, ys, color="tab:purple", alpha=0.6, label="empuje comandado")
        axb.set_ylabel("empuje (0–65535)")
        axb.legend(fontsize=8, loc="upper right")
    _marcar_eventos(ax, events)
    ax.set_title("Batería y empuje")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    return _guardar(figure, output, "04_bateria_empuje.pdf")


def figura_velocidades(samples, events, output: Path) -> Path:
    figure, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for ax, eje in zip(axes, "xyz"):
        for key, etiqueta, estilo in ((f"mocap_v{eje}", "mocap", "-"), (f"ekf_v{eje}", "EKF", "--")):
            xs, ys = _serie(samples, key)
            if xs:
                ax.plot(xs, ys, estilo, label=etiqueta, linewidth=1)
        _marcar_eventos(ax, events)
        ax.set_ylabel(f"v{eje} (m/s)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper right")
    axes[0].set_title("Velocidad estimada por el EKF y derivada del mocap")
    axes[-1].set_xlabel("t (s)")
    return _guardar(figure, output, "05_velocidades.pdf")


# ---------------------------------------------------------------- comandos y vuelo

def _direccion_de_evento(event: dict) -> str | None:
    """Texto corto de lo que pidió una orden: '+X', '−Y', '↑', 'giro ⟲', 'freno'..."""
    nombre, detalle = event["evento"], event.get("detalle", "") or ""
    if nombre == "TAKEOFF":
        return "despegue"
    if nombre in ("LAND", "LAND_SEGURIDAD"):
        return "aterrizar"
    if nombre == "EMERGENCIA":
        return "EMERGENCIA"
    if nombre in ("VEL", "GO_TO", "TRAMO"):
        m = re.search(r"(?:ux|dx|u)=\(?([+-]?[0-9.]+)[,)]?\s*(?:uy|dy|)=?\s*([+-]?[0-9.]+)?", detalle)
        vals = {}
        for clave in ("ux", "uy", "uz", "uyaw", "dx", "dy", "dz", "dyaw"):
            mm = re.search(rf"{clave}=([+-]?[0-9.]+)", detalle)
            if mm:
                vals[clave[-1] if clave.endswith(("x", "y", "z")) else "yaw"] = float(mm.group(1))
        if nombre == "TRAMO":
            mm = re.search(r"u=\(([+-]?[0-9.]+),([+-]?[0-9.]+),([+-]?[0-9.]+)\)", detalle)
            if mm:
                vals = {"x": float(mm.group(1)), "y": float(mm.group(2)), "z": float(mm.group(3))}
                my = re.search(r"uyaw=([+-]?[0-9.]+)", detalle)
                vals["yaw"] = float(my.group(1)) if my else 0.0
        partes = []
        for eje, pos, neg in (("x", "+X", "−X"), ("y", "+Y", "−Y"), ("z", "↑", "↓")):
            v = vals.get(eje, 0.0)
            if abs(v) > 1e-6:
                partes.append(pos if v > 0 else neg)
        yaw = vals.get("yaw", 0.0)
        if abs(yaw) > 1e-6:
            partes.append("giro ⟲" if yaw > 0 else "giro ⟳")
        return " ".join(partes) if partes else "freno"
    return None


COLORES_ORDEN = {
    "despegue": "tab:green", "aterrizar": "tab:blue", "EMERGENCIA": "tab:red", "freno": "lightgray",
    "+X": "tab:orange", "−X": "tab:brown", "+Y": "tab:purple", "−Y": "tab:pink",
    "↑": "tab:cyan", "↓": "tab:olive", "giro ⟲": "gold", "giro ⟳": "khaki",
}


def _direccion_por_desplazamiento(samples: list[dict], a: float, b: float) -> str:
    """Dirección dominante del movimiento del dron entre `a` y `b` (sesiones sin evento VEL)."""
    tramo = [r for r in samples if a <= r["t_s"] <= b and all(r.get(k) is not None for k in ("mocap_x", "mocap_y", "mocap_z"))]
    if len(tramo) < 2:
        return "movimiento"
    d = [tramo[-1][f"mocap_{e}"] - tramo[0][f"mocap_{e}"] for e in "xyz"]
    partes = []
    for v, pos, neg in zip(d, ("+X", "+Y", "↑"), ("−X", "−Y", "↓")):
        if abs(v) >= 0.08:
            partes.append(pos if v > 0 else neg)
    return " ".join(partes) if partes else "movimiento"


def ordenes(events: list[dict], fin_s: float, samples: list[dict] | None = None) -> list[tuple[float, float, str]]:
    """(inicio, fin, texto) de cada orden. Una orden dura hasta la siguiente o hasta el freno."""
    out: list[tuple[float, float, str]] = []
    pendiente: tuple[float, str] | None = None
    hay_vel = any(e["evento"] == "VEL" for e in events)
    if not hay_vel and samples:
        # Sesiones anteriores al evento VEL: cada tramo fluido, por su desplazamiento.
        inicio = None
        for event in events:
            if event["evento"] == "FLUIDO_INICIO":
                inicio = event["t_s"]
            elif event["evento"] == "FLUIDO_FIN" and inicio is not None:
                out.append((inicio, event["t_s"], _direccion_por_desplazamiento(samples, inicio, event["t_s"])))
                inicio = None
    for event in events:
        texto = _direccion_de_evento(event)
        if texto is None:
            continue
        t = event["t_s"]
        if pendiente is not None:
            out.append((pendiente[0], t, pendiente[1]))
            pendiente = None
        if texto == "freno":
            continue
        if texto in ("despegue", "aterrizar"):
            out.append((t, t + 4.0, texto))
        elif texto == "EMERGENCIA":
            out.append((t, t + 0.5, texto))
        else:
            pendiente = (t, texto)
    if pendiente is not None:
        out.append((pendiente[0], fin_s, pendiente[1]))
    return sorted(out)


def gestos_de_la_camara(source: Path, samples: list[dict]) -> list[tuple[float, float, str]]:
    """Gestos ejecutados por la cámara en la misma franja, con el reloj del dron.

    Busca el registro de la cámara de un dron (`control_camara_dron1/<día>/sesion_HHMMSS.csv`)
    o de dos (`dos_drones/<día>/gestos_*_AAAAMMDD_HHMMSS.csv`) cuyo arranque
    esté a menos de 3 min del CSV del dron, y alinea por hora de arranque.
    """
    m = re.search(r"(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", source.stem)
    if not m:
        return []
    inicio_dron = datetime(*map(int, m.groups()))
    dia = inicio_dron.strftime("%Y-%m-%d")
    candidatos: list[tuple[Path, datetime]] = []
    for p in (PROJECT_DIR / "results" / "data" / "control_camara_dron1" / dia).glob("sesion_*.csv"):
        mm = re.search(r"sesion_(\d{2})(\d{2})(\d{2})", p.stem)
        if mm:
            candidatos.append((p, inicio_dron.replace(hour=int(mm.group(1)), minute=int(mm.group(2)), second=int(mm.group(3)))))
    for p in (PROJECT_DIR / "results" / "data" / "dos_drones" / dia).glob("gestos_*.csv"):
        mm = re.search(r"(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", p.stem)
        if mm:
            candidatos.append((p, datetime(*map(int, mm.groups()))))
    candidatos = [(p, t) for p, t in candidatos if abs((t - inicio_dron).total_seconds()) <= 180]
    if not candidatos:
        return []
    ruta, inicio_cam = min(candidatos, key=lambda pt: abs((pt[1] - inicio_dron).total_seconds()))
    desfase = (inicio_cam - inicio_dron).total_seconds()
    fin = samples[-1]["t_s"] if samples else 0.0
    md = re.search(r"Dron(\d)", source.stem)
    clave = f"drone{md.group(1)}" if md else None
    out: list[tuple[float, float, str]] = []
    actual: tuple[float, str] | None = None
    with ruta.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            t_raw = row.get("t_s", row.get("tiempo_s", ""))
            try:
                t = float(t_raw) + desfase
            except (TypeError, ValueError):
                continue
            destino = row.get("destino")
            if destino and clave and destino not in (clave, "both", "hands"):
                continue
            gesto = row.get("gesto_mano") or row.get("comando_filtrado") or row.get("gesto") or ""
            if gesto in ("", "REPOSO", "SIN_DETECCION", "NO_GESTURE"):
                gesto = ""
            if actual is not None and gesto != actual[1]:
                out.append((actual[0], t, actual[1]))
                actual = None
            if gesto and actual is None:
                actual = (t, gesto)
    if actual is not None:
        out.append((actual[0], fin, actual[1]))
    return [(a, b, g) for a, b, g in out if b - a >= 0.15 and b >= 0 and a <= fin]


def figura_comandos_y_vuelo(samples, events, output: Path, source: Path) -> Path:
    """Línea de tiempo de órdenes (y gestos de la cámara si los hay) sobre el vuelo."""
    fin = samples[-1]["t_s"]
    t_ini, t_fin = ventana_de_vuelo(samples, events)
    lista = [o for o in ordenes(events, fin, samples) if o[1] >= t_ini and o[0] <= t_fin]
    gestos = [g for g in gestos_de_la_camara(source, samples) if g[1] >= t_ini and g[0] <= t_fin]
    ancho = max(t_fin - t_ini, 1.0)
    figure, (ax_g, ax_o, ax_z) = plt.subplots(
        3, 1, figsize=(12, 7.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.2, 2]})
    # gestos de la camara
    if gestos:
        nombres = sorted({g for _, _, g in gestos})
        colores = {g: cm.tab20(i / max(1, len(nombres))) for i, g in enumerate(nombres)}
        for a, b, g in gestos:
            ax_g.barh(0, b - a, left=a, height=0.8, color=colores[g], edgecolor="none")
            if b - a > ancho * 0.03:
                ax_g.text((a + b) / 2, 0, g, ha="center", va="center", fontsize=6, rotation=0)
        ax_g.set_yticks([])
        ax_g.set_title("Gestos vistos por la cámara")
        from matplotlib.patches import Patch
        ax_g.legend(handles=[Patch(color=colores[g], label=g) for g in nombres],
                    fontsize=6, loc="center left", bbox_to_anchor=(1.005, 0.5), frameon=False)
    else:
        ax_g.text(0.5, 0.5, "sin registro de cámara para esta sesión", ha="center", va="center",
                  transform=ax_g.transAxes, fontsize=9, color="gray")
        ax_g.set_yticks([])
    # ordenes al dron
    for a, b, texto in lista:
        color = COLORES_ORDEN.get(texto.split(" ")[0], "tab:gray")
        ax_o.barh(0, b - a, left=a, height=0.8, color=color, edgecolor="black", linewidth=0.3)
        if b - a > ancho * 0.015:
            ax_o.text((a + b) / 2, 0, texto, ha="center", va="center", fontsize=6)
    ax_o.set_yticks([])
    ax_o.set_title(f"Órdenes al dron ({len([o for o in lista if o[2] not in ('despegue', 'aterrizar', 'EMERGENCIA')])} movimientos)")
    # altura y desplazamiento
    xs, zs = _serie(samples, "mocap_z")
    ax_z.plot(xs, zs, label="altura (m)", color="tab:blue")
    xs, xv = _serie(samples, "mocap_x")
    _, yv = _serie(samples, "mocap_y")
    n = min(len(xs), len(xv), len(yv))
    if n:
        ax_z.plot(xs[:n], xv[:n], label="x (m)", color="tab:orange", alpha=0.8)
        ax_z.plot(xs[:n], yv[:n], label="y (m)", color="tab:purple", alpha=0.8)
    # Solo los hitos: las decenas de pulsos ya estan en la franja de ordenes.
    _marcar_eventos(ax_z, [e for e in events if e["evento"] in ("TAKEOFF", "LAND", "LANDED", "LAND_SEGURIDAD", "EMERGENCIA")])
    ax_z.set_xlabel("t (s)")
    ax_z.set_ylabel("m")
    ax_z.grid(alpha=0.3)
    ax_z.legend(fontsize=8, loc="upper right")
    ax_z.set_xlim(t_ini, t_fin)
    figure.subplots_adjust(right=0.84, hspace=0.35)
    return _guardar(figure, output, "07_comandos_y_vuelo.pdf")


def figura_vuelo_3d(samples, events, output: Path) -> Path:
    """Trayectoria 3D coloreada por tiempo, con las órdenes marcadas."""
    puntos = [(r["t_s"], r["mocap_x"], r["mocap_y"], r["mocap_z"]) for r in samples
              if all(r.get(k) is not None for k in ("mocap_x", "mocap_y", "mocap_z")) and r["modo"] not in MODOS_EN_TIERRA]
    figure = plt.figure(figsize=(9, 7.5))
    ax = figure.add_subplot(111, projection="3d")
    if puntos:
        ts = [p[0] for p in puntos]
        sc = ax.scatter([p[1] for p in puntos], [p[2] for p in puntos], [p[3] for p in puntos],
                        c=ts, cmap="viridis", s=4)
        ax.plot([p[1] for p in puntos], [p[2] for p in puntos], [p[3] for p in puntos], color="gray", linewidth=0.5, alpha=0.6)
        figure.colorbar(sc, ax=ax, shrink=0.6, label="t (s)")
        ax.scatter([puntos[0][1]], [puntos[0][2]], [puntos[0][3]], color="green", s=50, label="despegue")
        ax.scatter([puntos[-1][1]], [puntos[-1][2]], [puntos[-1][3]], color="red", s=50, marker="s", label="fin")
        por_t = {round(p[0], 1): p for p in puntos}
        for event in events:
            texto = _direccion_de_evento(event)
            if texto in (None, "freno", "despegue", "aterrizar"):
                continue
            cerca = min(puntos, key=lambda p: abs(p[0] - event["t_s"]))
            if abs(cerca[0] - event["t_s"]) < 0.5:
                ax.text(cerca[1], cerca[2], cerca[3], texto, fontsize=6, color="black")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_zlabel("z (m)")
    ax.set_title("Vuelo en 3D (color = tiempo; etiquetas = órdenes)")
    ax.legend(fontsize=8, loc="upper left")
    return _guardar(figure, output, "08_vuelo_3d.pdf")


def sesion_hermana(source: Path) -> Path | None:
    """CSV del otro dron arrancado a menos de 60 s, si lo hay (vuelo de dos drones)."""
    m = re.match(r"dron_robotat_(Dron\d)_(\d{8}_\d{6})", source.stem)
    if not m:
        return None
    otro = "Dron2" if m.group(1) == "Dron1" else "Dron1"
    inicio = datetime.strptime(m.group(2), "%Y%m%d_%H%M%S")
    mejor = None
    for p in source.parent.glob(f"dron_robotat_{otro}_*.csv"):
        mm = re.search(r"(\d{8}_\d{6})", p.stem)
        if not mm:
            continue
        delta = abs((datetime.strptime(mm.group(1), "%Y%m%d_%H%M%S") - inicio).total_seconds())
        if delta <= 60 and (mejor is None or delta < mejor[0]):
            mejor = (delta, p)
    return None if mejor is None else mejor[1]


def figura_vuelo_dual(source: Path, hermana: Path) -> Path:
    """Los dos drones en el mismo plano y la separación en el tiempo."""
    def inicio(p: Path) -> datetime:
        return datetime.strptime(re.search(r"(\d{8}_\d{6})", p.stem).group(1), "%Y%m%d_%H%M%S")

    fuentes = sorted([source, hermana], key=inicio)
    t0 = inicio(fuentes[0])
    datos = []
    for p in fuentes:
        samples, events = cargar(p)
        desfase = (inicio(p) - t0).total_seconds()
        datos.append((p, samples, events, desfase))
    carpeta = GRAPH_DIR / session_day(source) / f"vuelo_dual_{t0:%Y%m%d_%H%M%S}"
    carpeta.mkdir(parents=True, exist_ok=True)
    figure, (ax_xy, ax_sep) = plt.subplots(1, 2, figsize=(14, 6.5), gridspec_kw={"width_ratios": [1.1, 1]})
    series = []
    for (p, samples, events, desfase), color in zip(datos, ("tab:blue", "tab:red")):
        nombre = re.search(r"(Dron\d)", p.stem).group(1)
        pts = [(r["t_s"] + desfase, r["mocap_x"], r["mocap_y"], r["mocap_z"]) for r in samples
               if all(r.get(k) is not None for k in ("mocap_x", "mocap_y", "mocap_z")) and r["modo"] not in MODOS_EN_TIERRA]
        if not pts:
            continue
        series.append((nombre, pts))
        ax_xy.plot([q[1] for q in pts], [q[2] for q in pts], color=color, linewidth=1, label=nombre)
        ax_xy.plot(pts[0][1], pts[0][2], "o", color=color)
        ax_xy.plot(pts[-1][1], pts[-1][2], "s", color=color)
    ax_xy.set_aspect("equal", adjustable="datalim")
    ax_xy.set_xlabel("x (m)")
    ax_xy.set_ylabel("y (m)")
    ax_xy.set_title("Trayectorias de los dos drones (○ inicio, □ fin)")
    ax_xy.grid(alpha=0.3)
    ax_xy.legend(fontsize=8)
    if len(series) == 2:
        (_, a), (_, b) = series
        tb = [q[0] for q in b]
        import bisect
        ts, ds = [], []
        for t, x, y, z in a:
            i = bisect.bisect_left(tb, t)
            if i < len(b) and abs(b[i][0] - t) < 0.15:
                ts.append(t)
                ds.append(math.dist((x, y, z), b[i][1:4]))
        if ts:
            ax_sep.plot(ts, ds, color="tab:green")
            ax_sep.axhline(0.30, color="tab:red", linestyle="--", alpha=0.6, label="mínimo 0.30 m")
            ax_sep.set_ylim(bottom=0)
            ax_sep.set_xlim(min(ts) - 2, max(ts) + 2)
            ax_sep.legend(fontsize=8)
    ax_sep.set_xlabel("t (s) desde el primer preflight")
    ax_sep.set_ylabel("separación (m)")
    ax_sep.set_title("Separación entre drones")
    ax_sep.grid(alpha=0.3)
    figure.suptitle(f"Vuelo de dos drones {t0:%Y-%m-%d %H:%M:%S}")
    return _guardar(figure, carpeta, "trayectorias_y_separacion.pdf")


def figura_actitud(samples, events, output: Path) -> Path:
    figure, ax = plt.subplots(figsize=(11, 4))
    for key, etiqueta in (("roll_deg", "roll"), ("pitch_deg", "pitch"), ("ekf_yaw_deg", "yaw EKF"), ("mocap_yaw_deg", "yaw mocap")):
        xs, ys = _serie(samples, key)
        if xs:
            ax.plot(xs, ys, label=etiqueta, linewidth=1)
    _marcar_eventos(ax, events)
    ax.set_xlabel("t (s)")
    ax.set_ylabel("grados")
    ax.set_title("Actitud")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    return _guardar(figure, output, "06_actitud.pdf")


def resumen(samples: list[dict], events: list[dict]) -> dict[str, object]:
    """Cifras de la sesión. Todo lo que no se pueda calcular queda en None."""
    out: dict[str, object] = {}
    preflight = next((e for e in events if e["evento"] == "PREFLIGHT_OK"), None)
    out["parametros"] = preflight["detalle"] if preflight else ""
    out["duracion_s"] = samples[-1]["t_s"] if samples else 0.0
    out["fin"] = next((e["evento"] + (f": {e['detalle']}" if e["detalle"] else "")
                       for e in reversed(events) if e["evento"] in ("LANDED", "EMERGENCIA", "LAND_SEGURIDAD")), "sin cierre")
    vbat = [r["bateria_v"] for r in samples if r.get("bateria_v")]
    out["bateria_reposo_v"] = vbat[0] if vbat else None
    out["bateria_min_v"] = min(vbat) if vbat else None
    takeoff = next((e for e in events if e["evento"] == "TAKEOFF"), None)
    if takeoff is not None:
        tk = takeoff["t_s"]
        objetivo = takeoff.get("objetivo_z")
        tramo = [r for r in samples if tk <= r["t_s"] <= tk + 8 and r.get("mocap_z") is not None]
        if tramo:
            out["despegue_z_max_m"] = max(r["mocap_z"] for r in tramo)
            out["despegue_sobrepaso_m"] = None if objetivo is None else out["despegue_z_max_m"] - objetivo
            arriba = [r["t_s"] for r in tramo if r["mocap_z"] > 0.10]
            out["despegue_hasta_10cm_s"] = (arriba[0] - tk) if arriba else None
        hover = [r for r in samples if r["modo"] == "VUELO" and r["t_s"] > tk + 5
                 and all(r.get(k) is not None for k in ("mocap_x", "mocap_y", "mocap_z", "objetivo_x", "objetivo_y", "objetivo_z"))]
        if len(hover) >= 20:
            for eje in "xyz":
                err = [r[f"mocap_{eje}"] - r[f"objetivo_{eje}"] for r in hover]
                out[f"hover_sigma_{eje}_m"] = statistics.pstdev(err)
            out["hover_s"] = len(hover) / 10.0
            roll = [r["roll_deg"] for r in hover if r.get("roll_deg") is not None]
            out["hover_roll_sigma_deg"] = statistics.pstdev(roll) if len(roll) > 1 else None
            empuje = [r["empuje_cmd"] for r in hover if r.get("empuje_cmd")]
            out["empuje_hover"] = statistics.mean(empuje) if empuje else None
    errores = [r["error_ekf_mocap_m"] for r in samples if r.get("error_ekf_mocap_m") is not None]
    out["error_ekf_max_m"] = max(errores) if errores else None
    huecos = [r["mocap_hueco_max_s"] for r in samples if r.get("mocap_hueco_max_s") is not None]
    out["mocap_hueco_max_s"] = max(huecos) if huecos else None
    congelado = [r for r in samples if r.get("mocap_congelado")]
    out["mocap_congelado_s"] = len(congelado) / 10.0
    out["movimientos_fluidos"] = sum(1 for e in events if e["evento"] == "FLUIDO_INICIO")
    out["pasos"] = sum(1 for e in events if e["evento"] == "GO_TO")
    return out


def escribir_resumen(datos: dict[str, object], output: Path, source: Path) -> Path:
    lineas = [f"Sesión: {source.name}", ""]
    etiquetas = (
        ("duracion_s", "Duración (s)", "{:.1f}"),
        ("fin", "Final", "{}"),
        ("bateria_reposo_v", "Batería en reposo (V)", "{:.2f}"),
        ("bateria_min_v", "Batería mínima (V)", "{:.2f}"),
        ("despegue_hasta_10cm_s", "Despegue: hasta 10 cm (s)", "{:.1f}"),
        ("despegue_z_max_m", "Despegue: altura máxima (m)", "{:.3f}"),
        ("despegue_sobrepaso_m", "Despegue: sobrepaso (m)", "{:+.3f}"),
        ("hover_s", "Hover analizado (s)", "{:.1f}"),
        ("hover_sigma_x_m", "Hover σ x (m)", "{:.3f}"),
        ("hover_sigma_y_m", "Hover σ y (m)", "{:.3f}"),
        ("hover_sigma_z_m", "Hover σ z (m)", "{:.3f}"),
        ("hover_roll_sigma_deg", "Hover σ roll (°)", "{:.2f}"),
        ("empuje_hover", "Empuje medio en hover", "{:.0f}"),
        ("error_ekf_max_m", "Error EKF–mocap máximo (m)", "{:.3f}"),
        ("mocap_hueco_max_s", "Hueco máximo del mocap (s)", "{:.3f}"),
        ("mocap_congelado_s", "Pose congelada (s)", "{:.1f}"),
        ("movimientos_fluidos", "Movimientos fluidos", "{}"),
        ("pasos", "Pasos go_to", "{}"),
    )
    for clave, etiqueta, formato in etiquetas:
        valor = datos.get(clave)
        lineas.append(f"{etiqueta}: " + ("n/d" if valor is None else formato.format(valor)))
    lineas += ["", f"Parámetros: {datos.get('parametros', '')}"]
    path = output / "00_resumen.txt"
    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return path


def analyze_session(source: Path) -> Path:
    """Crea las figuras PDF y el resumen de un CSV; devuelve la carpeta de salida."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"No existe: {source}")
    samples, events = cargar(source)
    if not samples:
        raise ValueError("El CSV no contiene muestras.")
    output = session_output_dir(source)
    output.mkdir(parents=True, exist_ok=True)
    radio_max = None
    preflight = next((e for e in events if e["evento"] == "PREFLIGHT_OK"), None)
    if preflight is not None:
        match = re.search(r"radio_max_m=([0-9.]+)", preflight["detalle"])
        radio_max = float(match.group(1)) if match else None
    figura_altura(samples, events, output)
    figura_trayectoria(samples, output, radio_max)
    figura_error_y_mocap(samples, events, output)
    figura_bateria_empuje(samples, events, output)
    figura_velocidades(samples, events, output)
    figura_actitud(samples, events, output)
    figura_comandos_y_vuelo(samples, events, output, source)
    figura_vuelo_3d(samples, events, output)
    hermana = sesion_hermana(source)
    if hermana is not None:
        try:
            figura_vuelo_dual(source, hermana)
        except Exception as exc:  # la figura dual es un extra; no debe tumbar el resto
            print(f"sin figura dual: {exc}")
    escribir_resumen(resumen(samples, events), output, source)
    return output


def ultima_sesion() -> Path | None:
    candidatos = sorted(DATA_DIR.glob("*/*.csv"), key=lambda p: p.stat().st_mtime)
    return candidatos[-1] if candidatos else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gráficas PDF de una sesión del controlador sobre el Robotat")
    parser.add_argument("csv", nargs="?", help="CSV de la sesión; por defecto la última")
    parser.add_argument("--todas", action="store_true", help="todas las sesiones del último día")
    args = parser.parse_args(argv)
    if args.todas:
        ultima = ultima_sesion()
        if ultima is None:
            print("No hay sesiones.")
            return 1
        fuentes = sorted(ultima.parent.glob("*.csv"))
    else:
        fuente = Path(args.csv) if args.csv else ultima_sesion()
        if fuente is None:
            print("No hay sesiones.")
            return 1
        fuentes = [fuente]
    for fuente in fuentes:
        try:
            print(f"{fuente.name} -> {analyze_session(fuente)}")
        except ValueError as exc:
            print(f"{fuente.name}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

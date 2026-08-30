"""Genera figuras de presentación a partir de una sesión CSV del marker."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import matplotlib

# Solo guardamos PDF; evitar que Matplotlib intente abrir una ventana Tkinter.
matplotlib.use("Agg")
import matplotlib.pyplot as plt


DATA_DIR = Path(__file__).resolve().parent / "datos_marker"
GRAPH_DIR = Path(__file__).resolve().parents[1] / "gráficas"


def number(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def command_color(name: str) -> str:
    if name == "NEUTRO":
        return "#8c959b"
    if "ATERRIZAR" in name:
        return "#c83b32"
    if "SUBIR" in name:
        return "#2878b5"
    if "BAJAR" in name:
        return "#e38a19"
    return "#2d8a45"


def read_session(path: Path) -> tuple[list[dict], list[dict]]:
    with path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    return [row for row in rows if row["tipo"] == "muestra"], [row for row in rows if row["tipo"] == "evento"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea gráficas de una sesión de marker")
    parser.add_argument("csv", nargs="?", type=Path, help="CSV de sesión; si se omite usa el más reciente")
    args = parser.parse_args()
    path = args.csv
    if path is None:
        files = sorted(DATA_DIR.glob("sesion_marker_*.csv"))
        if not files:
            raise SystemExit("No hay CSV. Realice primero una sesión con control_with_marker.py")
        path = files[-1]
    samples, events = read_session(path)
    if len(samples) < 3:
        raise SystemExit("El CSV no tiene suficientes muestras para graficar")

    out = GRAPH_DIR / path.stem
    out.mkdir(parents=True, exist_ok=True)
    t = [number(row, "t_s") for row in samples]
    commands = [row["estado_marker"] or "SIN_DATOS" for row in samples]
    command_names = list(dict.fromkeys(commands))
    command_index = {name: index for index, name in enumerate(command_names)}

    # 1. Línea de tiempo de los gestos/comandos interpretados.
    fig, ax = plt.subplots(figsize=(13, 4.8))
    for name in command_names:
        indices = [index for index, command in enumerate(commands) if command == name]
        ax.scatter([t[index] for index in indices], [command_index[name]] * len(indices), s=13, color=command_color(name), label=name)
    for event in events:
        ax.axvline(number(event, "t_s"), color="#1f2933", alpha=.35, linestyle="--")
        ax.text(number(event, "t_s"), -.35, event["evento"], rotation=90, va="bottom", fontsize=8)
    ax.set_yticks(range(len(command_names)), command_names)
    ax.set_ylim(-.5, len(command_names) - .5)
    ax.margins(x=.04)
    ax.set_xlabel("Tiempo [s]")
    ax.set_title("Línea de tiempo: comandos detectados a partir del marker")
    ax.grid(axis="x", alpha=.25)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, ncol=1)
    fig.tight_layout()
    fig.savefig(out / "01_timeline_comandos.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)

    # 2. Movimiento físico del joystick respecto al cero establecido.
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    axes[0].plot(t, [number(row, "roll_rel_deg") for row in samples], label="Roll relativo", color="#e38a19")
    axes[0].axhspan(-12, 12, color="#8c959b", alpha=.13, label="Zona muerta +/-12 deg")
    axes[0].set_ylabel("Roll [deg]"); axes[0].legend(); axes[0].grid(alpha=.25)
    axes[1].plot(t, [number(row, "pitch_rel_deg") for row in samples], label="Pitch relativo", color="#c83b32")
    axes[1].axhspan(-12, 12, color="#8c959b", alpha=.13, label="Zona muerta +/-12 deg")
    axes[1].set_ylabel("Pitch [deg]"); axes[1].legend(); axes[1].grid(alpha=.25)
    axes[2].plot(t, [number(row, "marker_dz_m") for row in samples], label="Desplazamiento vertical", color="#1f77b4")
    axes[2].axhline(0, color="black", linewidth=.7)
    axes[2].set_xlabel("Tiempo [s]"); axes[2].set_ylabel("Delta Z [m]"); axes[2].legend(); axes[2].grid(alpha=.25)
    fig.suptitle("Movimiento del joystick respecto al cero", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "02_movimiento_joystick.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)

    # 3. Setpoints de velocidad realmente enviados al Crazyflie.
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    for axis, key, label, color in (
        (axes[0], "vx_cmd_m_s", "VX enviada", "#2878b5"),
        (axes[1], "vy_cmd_m_s", "VY enviada", "#2d8a45"),
        (axes[2], "vz_cmd_m_s", "VZ enviada", "#8e44ad"),
    ):
        axis.plot(t, [number(row, key) for row in samples], label=label, color=color)
        axis.axhline(0, color="black", linewidth=.7)
        axis.set_ylabel("m/s")
        axis.grid(alpha=.25)
        axis.legend()
    axes[-1].set_xlabel("Tiempo [s]")
    fig.suptitle("Comandos de velocidad enviados al dron", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "03_comandos_velocidad.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)

    # 4. Trayectoria real en el plano horizontal, coloreada por comando.
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    x = [number(row, "drone_x_m") for row in samples]
    y = [number(row, "drone_y_m") for row in samples]
    ax.plot(x, y, color="#93a1a1", linewidth=1, alpha=.65, label="Trayectoria")
    for name in command_names:
        indices = [index for index, command in enumerate(commands) if command == name]
        ax.scatter([x[index] for index in indices], [y[index] for index in indices], s=16, color=command_color(name), label=name)
    ax.scatter(x[0], y[0], s=80, marker="o", color="#1f2933", label="Inicio")
    ax.scatter(x[-1], y[-1], s=90, marker="X", color="#c83b32", label="Fin")
    ax.set_xlabel("X global [m]"); ax.set_ylabel("Y global [m]")
    ax.set_title("Trayectoria XY del dron durante el control por marker")
    ax.axis("equal"); ax.grid(alpha=.25); ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out / "04_trayectoria_xy.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)

    counts = Counter(commands)
    with (out / "resumen.txt").open("w", encoding="utf-8") as file:
        file.write(f"Sesión: {path.name}\nDuración: {t[-1]:.2f} s\nMuestras: {len(samples)}\n\n")
        file.write("Tiempo por comando detectado:\n")
        dt = (t[-1] - t[0]) / max(1, len(t) - 1)
        for name, count in counts.most_common():
            file.write(f"- {name}: {count * dt:.2f} s\n")
        file.write("\nEventos:\n")
        for event in events:
            file.write(f"- t={number(event, 't_s'):.2f} s: {event['evento']}\n")
    print(f"Análisis creado en: {out}")


if __name__ == "__main__":
    main()

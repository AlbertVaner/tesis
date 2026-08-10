"""Genera gráficas y un resumen de la última sesión de dos drones."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DATA_DIR = Path(__file__).resolve().parent / "datos_dos_drones"


def number(row: dict, key: str):
    try:
        return float(row[key]) if row.get(key, "") != "" else None
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiza logs CSV de dos drones")
    parser.add_argument("csv", nargs="?", type=Path, help="CSV a analizar (por defecto: último)")
    args = parser.parse_args()
    source = args.csv
    if source is None:
        files = sorted(DATA_DIR.glob("sesion_dos_drones_*.csv"))
        if not files:
            raise SystemExit(f"No hay CSV en {DATA_DIR}")
        source = files[-1]
    if not source.exists():
        raise SystemExit(f"No existe: {source}")

    samples: dict[str, list[dict]] = defaultdict(list)
    events: list[dict] = []
    with source.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["kind"] == "sample" and row["drone"]:
                samples[row["drone"]].append(row)
            elif row["kind"] == "event":
                events.append(row)

    output = source.parent / f"analisis_{source.stem}"
    output.mkdir(exist_ok=True)
    names = sorted(samples)
    if not names:
        raise SystemExit("El CSV no contiene muestras.")

    # Altura: MoCap, EKF y objetivo. Es la gráfica clave para detectar subida excesiva.
    figure, axes = plt.subplots(len(names), 1, figsize=(11, 4 * len(names)), sharex=True)
    if len(names) == 1:
        axes = [axes]
    for axis, name in zip(axes, names):
        rows = samples[name]
        time_s = [number(row, "t_s") for row in rows]
        for key, label, color in (("mocap_z_m", "MoCap z", "#198754"), ("ekf_z_m", "EKF z", "#0d6efd"), ("target_z_m", "Objetivo z", "#dc3545")):
            values = [number(row, key) for row in rows]
            axis.plot(time_s, values, label=label, color=color, linewidth=1.4)
        axis.set_title(name)
        axis.set_ylabel("Altura [m]")
        axis.grid(alpha=.25)
        axis.legend()
    axes[-1].set_xlabel("Tiempo [s]")
    figure.tight_layout()
    figure.savefig(output / "01_altura_mocap_ekf_objetivo.png", dpi=180)
    plt.close(figure)

    # Trayectoria horizontal: MoCap y objetivo final solicitado.
    figure, axis = plt.subplots(figsize=(8, 7))
    for name in names:
        rows = samples[name]
        x = [number(row, "mocap_x_m") for row in rows]
        y = [number(row, "mocap_y_m") for row in rows]
        axis.plot(x, y, linewidth=1.4, label=f"{name} MoCap")
        if x and y and x[0] is not None and y[0] is not None:
            axis.scatter(x[0], y[0], s=35, marker="o")
    axis.set_title("Trayectoria horizontal registrada")
    axis.set_xlabel("X [m]")
    axis.set_ylabel("Y [m]")
    axis.axis("equal")
    axis.grid(alpha=.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "02_trayectoria_xy.png", dpi=180)
    plt.close(figure)

    # Error vertical EKF - MoCap: permite detectar pérdida/desajuste del estimador.
    figure, axis = plt.subplots(figsize=(11, 4.5))
    for name in names:
        rows = samples[name]
        time_s = [number(row, "t_s") for row in rows]
        error = []
        for row in rows:
            ekf, mocap = number(row, "ekf_z_m"), number(row, "mocap_z_m")
            error.append(None if ekf is None or mocap is None else ekf - mocap)
        axis.plot(time_s, error, linewidth=1.3, label=f"{name}: EKF − MoCap")
    axis.axhline(0, color="black", linewidth=.8)
    axis.set_title("Error vertical del estimador")
    axis.set_xlabel("Tiempo [s]")
    axis.set_ylabel("Error z [m]")
    axis.grid(alpha=.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "03_error_vertical_ekf_mocap.png", dpi=180)
    plt.close(figure)

    # Calidad de entrada: frecuencia y edad del último paquete MoCap.
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for name in names:
        rows = samples[name]
        time_s = [number(row, "t_s") for row in rows]
        axes[0].plot(time_s, [number(row, "mocap_hz") for row in rows], linewidth=1.2, label=name)
        axes[1].plot(time_s, [number(row, "mocap_age_s") for row in rows], linewidth=1.2, label=name)
    axes[0].axhline(20, color="#dc3545", linewidth=.9, linestyle="--", label="Referencia 20 Hz")
    axes[0].set_ylabel("Frecuencia [Hz]")
    axes[0].set_title("Calidad del flujo MoCap")
    axes[0].grid(alpha=.25)
    axes[0].legend()
    axes[1].axhline(.10, color="#dc3545", linewidth=.9, linestyle="--", label="Referencia 0.10 s")
    axes[1].set_xlabel("Tiempo [s]")
    axes[1].set_ylabel("Edad del paquete [s]")
    axes[1].grid(alpha=.25)
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(output / "04_calidad_mocap.png", dpi=180)
    plt.close(figure)

    # Comandos low-level. Solo se crea cuando la sesion registra el lazo externo.
    command_keys = ("cmd_vx_m_s", "cmd_vy_m_s", "cmd_vz_m_s")
    has_commands = any(
        number(row, key) is not None
        for rows in samples.values()
        for row in rows
        for key in command_keys
    )
    if has_commands:
        figure, axes = plt.subplots(len(names), 1, figsize=(11, 3.4 * len(names)), sharex=True)
        if len(names) == 1:
            axes = [axes]
        for axis, name in zip(axes, names):
            rows = samples[name]
            time_s = [number(row, "t_s") for row in rows]
            for key, label, color in (
                ("cmd_vx_m_s", "vx enviada", "#0d6efd"),
                ("cmd_vy_m_s", "vy enviada", "#6f42c1"),
                ("cmd_vz_m_s", "vz enviada", "#fd7e14"),
            ):
                axis.plot(time_s, [number(row, key) for row in rows], linewidth=1.2, label=label, color=color)
            axis.axhline(0, color="black", linewidth=.7)
            axis.set_title(f"{name}: comandos de velocidad del lazo externo")
            axis.set_ylabel("Velocidad [m/s]")
            axis.grid(alpha=.25)
            axis.legend(ncol=3)
        axes[-1].set_xlabel("Tiempo [s]")
        figure.tight_layout()
        figure.savefig(output / "05_comandos_low_level.png", dpi=180)
        plt.close(figure)

    # Errores de control usados por la prueba de estabilidad.
    has_control_errors = any(
        number(row, "error_z_m") is not None
        for rows in samples.values()
        for row in rows
    )
    if has_control_errors:
        figure, axes = plt.subplots(len(names), 1, figsize=(11, 3.4 * len(names)), sharex=True)
        if len(names) == 1:
            axes = [axes]
        for axis, name in zip(axes, names):
            rows = samples[name]
            time_s = [number(row, "t_s") for row in rows]
            vertical = [number(row, "error_z_m") for row in rows]
            horizontal = []
            for row in rows:
                ex, ey = number(row, "error_x_m"), number(row, "error_y_m")
                horizontal.append(None if ex is None or ey is None else (ex * ex + ey * ey) ** .5)
            axis.plot(time_s, vertical, linewidth=1.3, label="Error vertical", color="#dc3545")
            axis.plot(time_s, horizontal, linewidth=1.3, label="Error horizontal", color="#198754")
            axis.axhline(0, color="black", linewidth=.7)
            axis.set_title(f"{name}: error respecto al objetivo")
            axis.set_ylabel("Error [m]")
            axis.grid(alpha=.25)
            axis.legend()
        axes[-1].set_xlabel("Tiempo [s]")
        figure.tight_layout()
        figure.savefig(output / "06_error_control.png", dpi=180)
        plt.close(figure)

    # La separacion se registra desde ambos lazos; una curva basta para revisar
    # que la prueba nunca se acerco al limite de seguridad.
    separation_rows = [
        row for rows in samples.values() for row in rows
        if number(row, "separation_m") is not None
    ]
    if separation_rows:
        figure, axis = plt.subplots(figsize=(11, 4.2))
        for name in names:
            rows = samples[name]
            time_s = [number(row, "t_s") for row in rows]
            separation = [number(row, "separation_m") for row in rows]
            axis.plot(time_s, separation, linewidth=1.2, label=name)
        axis.axhline(.70, color="#dc3545", linewidth=.9, linestyle="--", label="Límite 0.70 m")
        axis.set_title("Separación entre drones")
        axis.set_xlabel("Tiempo [s]")
        axis.set_ylabel("Distancia [m]")
        axis.grid(alpha=.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(output / "07_separacion_drones.png", dpi=180)
        plt.close(figure)

    duration = max((number(row, "t_s") or 0 for rows in samples.values() for row in rows), default=0)
    lines = [f"Archivo: {source.name}", f"Duración registrada: {duration:.2f} s", ""]
    for name in names:
        rows = samples[name]
        heights = [number(row, "mocap_z_m") for row in rows if number(row, "mocap_z_m") is not None]
        rates = [number(row, "mocap_hz") for row in rows if number(row, "mocap_hz") not in (None, 0)]
        lines.append(f"{name}: {len(rows)} muestras; altura MoCap máxima = {max(heights):.3f} m" if heights else f"{name}: sin altura MoCap")
        if rates:
            lines.append(f"{name}: frecuencia MoCap media = {sum(rates) / len(rates):.1f} Hz; mínima = {min(rates):.1f} Hz")
        targets = [number(row, "target_z_m") for row in rows if number(row, "target_z_m") is not None]
        if heights and targets:
            overshoot = max(height - target for height, target in zip(
                [number(row, "mocap_z_m") for row in rows],
                [number(row, "target_z_m") for row in rows],
            ) if height is not None and target is not None)
            lines.append(f"{name}: sobrepaso vertical máximo = {overshoot:+.3f} m")
        max_vz = max((abs(number(row, "cmd_vz_m_s")) for row in rows if number(row, "cmd_vz_m_s") is not None), default=None)
        if max_vz is not None:
            lines.append(f"{name}: velocidad vertical máxima enviada = {max_vz:.3f} m/s")
    separations = [number(row, "separation_m") for row in separation_rows]
    if separations:
        lines.append(f"Separación mínima registrada = {min(separations):.3f} m")
    lines += ["", "Eventos:"] + [f"t={row['t_s']} s | {row['drone']} | {row['event']}" for row in events]
    (output / "resumen.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Análisis creado en: {output}")


if __name__ == "__main__":
    main()

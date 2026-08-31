"""Comprobador visual del marker ROBOTAT. No conecta ni arma el dron."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

from marker_mocap import MocapReceiver, Pose

PROJECT_DIR = Path(__file__).resolve().parents[2]
SHARED_DIR = PROJECT_DIR / "controllers" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from gui_pdf_capture import auto_save_gui_pdf, install_gui_pdf_capture


DEFAULT_MARKER_TOPIC = "mocap/all"
DEFAULT_MARKER_ID = 64
MOCAP_TIMEOUT_S = 0.75


class OrientationChecker:
    def __init__(self, receiver: MocapReceiver) -> None:
        self.receiver = receiver
        self.zero: Pose | None = None
        self.root = tk.Tk()
        self.root.title("ROBOTAT · Verificación de marker")
        self.root.geometry("720x430")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(self.root, text="Verificación de orientación del marker", font=("Arial", 17, "bold")).pack(pady=(18, 5))
        tk.Label(self.root, text="Este programa no se conecta al Crazyflie. Primero confirme signos y ejes.", fg="#52615a").pack()
        self.pose_label = tk.Label(self.root, text="Esperando marker...", justify="left", font=("Consolas", 13))
        self.pose_label.pack(pady=18)
        self.relative_label = tk.Label(self.root, text="Referencia: no establecida", justify="left", font=("Consolas", 12), fg="#146c43")
        self.relative_label.pack(pady=8)
        self.status_label = tk.Label(self.root, text="Estado: esperando señal MQTT", font=("Arial", 11, "bold"), fg="#8a5d00")
        self.status_label.pack(pady=8)
        tk.Button(self.root, text="CAPTURAR CERO DEL MARKER", command=self.capture_zero, bg="#27843b", fg="white", font=("Arial", 11, "bold"), width=30, height=2).pack(pady=16)
        tk.Label(self.root, text="Prueba: inclina hacia adelante, atrás, izquierda y derecha; anota qué eje cambia.", fg="#52615a").pack()
        install_gui_pdf_capture(self.root, "gui_verificacion_marker")
        self.refresh()

    def capture_zero(self) -> None:
        pose = self.receiver.snapshot()
        if pose is None or pose.age_s > MOCAP_TIMEOUT_S:
            self.status_label.config(text="No se puede establecer cero: marker sin señal reciente", fg="#b3261e")
            return
        self.zero = pose
        self.status_label.config(text="Cero establecido. Mantén el marker nivelado para empezar.", fg="#146c43")

    def refresh(self) -> None:
        pose = self.receiver.snapshot()
        if pose is None:
            self.pose_label.config(text="Esperando marker en MQTT...")
        else:
            freshness = "ACTIVO" if pose.age_s <= MOCAP_TIMEOUT_S else f"SIN SEÑAL ({pose.age_s:.2f} s)"
            color = "#146c43" if pose.age_s <= MOCAP_TIMEOUT_S else "#b3261e"
            self.pose_label.config(text=(
                f"Posición global [m]\n  X = {pose.x:+.3f}    Y = {pose.y:+.3f}    Z = {pose.z:+.3f}\n\n"
                f"Orientación [°]\n  Roll  = {pose.roll_deg:+.1f}    Pitch = {pose.pitch_deg:+.1f}    Yaw = {pose.yaw_deg:+.1f}"
            ))
            self.status_label.config(text=f"Estado marker: {freshness}", fg=color)
            if self.zero is not None:
                self.relative_label.config(text=(
                    "Diferencia respecto al cero\n"
                    f"  ΔX={pose.x-self.zero.x:+.3f} m  ΔY={pose.y-self.zero.y:+.3f} m  ΔZ={pose.z-self.zero.z:+.3f} m\n"
                    f"  ΔRoll={pose.roll_deg-self.zero.roll_deg:+.1f}°  ΔPitch={pose.pitch_deg-self.zero.pitch_deg:+.1f}°"
                ))
        self.root.after(80, self.refresh)

    def close(self) -> None:
        auto_save_gui_pdf(self.root)
        self.receiver.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica posición y orientación de un marker ROBOTAT")
    parser.add_argument("--marker-topic", default=DEFAULT_MARKER_TOPIC, help="Tópico MQTT del marker")
    parser.add_argument("--marker-id", type=int, default=DEFAULT_MARKER_ID, help="ID ROBOTAT del rigid body")
    args = parser.parse_args()
    receiver = MocapReceiver(args.marker_topic, required_identifier=args.marker_id)
    receiver.start()
    OrientationChecker(receiver).run()


if __name__ == "__main__":
    main()

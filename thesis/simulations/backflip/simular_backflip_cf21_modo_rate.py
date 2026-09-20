"""Simulacion plana de un backflip con el Crazyflie 2.1 de escobillas y el FIRMWARE DE FABRICA.

Complementa a `simular_backflip_crazyflie.m` (Brushless de 44 g, controlador ideal),
que no describe los drones del laboratorio. Aqui la planta y el control son los reales:

* Masa deducida del empuje de hover recordado por dron (`cache/dron_robotat_empuje.json`)
  con la curva PWM -> empuje publicada por Bitcraze para el Crazyflie 2.x.
* Lazo de velocidad angular del firmware (PID 250/500/2.5 a 500 Hz, salida int16) y
  reparto de potencia con recorte de empuje para conservar el torque.
* El PC solo manda tres ordenes, con latencia y jitter de radio:
    1. IMPULSO : `send_setpoint` en modo rate, q = 0, empuje maximo.
    2. GIRO    : `send_setpoint` en modo rate, q = Q, empuje bajo.
    3. RECUPERA: `send_hover_setpoint`; el firmware nivela y frena la caida.
  La conmutacion 2 -> 3 se decide con el angulo integrado del giroscopo que llega
  por el log (retrasado), no con un tiempo fijo.

No envia nada a ningun dron. Uso (desde la raiz):
    python thesis/simulations/backflip/simular_backflip_cf21_modo_rate.py
"""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, replace
from pathlib import Path

G = 9.81
DT = 0.0005                      # s, integracion
CTRL_EVERY = 4                   # lazo rate del firmware a 500 Hz
BRAZO = 0.046 * math.sqrt(0.5)   # m, palanca de pitch de cada motor
J_NOMINAL = 1.6e-5               # kg m^2: 1.4e-5 del paper de Antal + marcadores


def empuje_total_n(cmd: float) -> float:
    """Curva de Bitcraze (PWM 0..256 -> gramos, los cuatro motores), en newtons."""
    pwm = 256.0 * max(0.0, min(1.0, cmd / 65535.0))
    return max(0.0, 0.409e-3 * pwm * pwm + 140.5e-3 * pwm - 0.099) * G / 1000.0


@dataclass(frozen=True)
class Dron:
    nombre: str
    hover_cmd: float
    j: float = J_NOMINAL
    escala_empuje: float = 1.0    # bateria: 1.0 cargada, ~0.85 al final
    tau_sube: float = 0.035       # s, el motor de escobillas acelera...
    tau_baja: float = 0.070       # ...mas rapido de lo que frena (no tiene freno activo)

    @property
    def masa(self) -> float:
        return empuje_total_n(self.hover_cmd) / G


@dataclass(frozen=True)
class Maniobra:
    t_impulso: float = 0.30       # s a empuje maximo antes de girar
    q_giro: float = 1100.0        # grados/s pedidos al lazo rate
    cmd_giro: float = 12000.0     # empuje durante el giro (de 65535)
    angulo_cambio: float = 285.0  # grados acumulados para pasar a RECUPERA
    latencia: float = 0.020       # s, PC + radio, por orden
    retraso_log: float = 0.025    # s, edad del angulo que ve el PC
    tilt0: float = 0.0            # grados, inclinacion al empezar
    vz0: float = 0.0


def simular(d: Dron, m: Maniobra, traza: bool = False) -> dict:
    masa = d.masa
    x = z = vx = 0.0
    vz = m.vz0
    th = math.radians(m.tilt0)   # pitch acumulado, sin envolver
    q = 0.0
    f_par = [masa * G / 2.0, masa * G / 2.0]   # empuje del par delantero y del trasero
    integ = prev_err = d_filt = 0.0
    fase, t_cambio_pedido, t_fase = 1, None, {1: 0.0}
    cola_angulo: list[tuple[float, float]] = []
    cmds = [d.hover_cmd, d.hover_cmd]
    filas = []
    z_min = z_max = x_min = x_max = 0.0
    q_max = 0.0
    n = int(1.8 / DT)
    for i in range(n):
        t = i * DT
        # --- PC: decide con informacion retrasada y sus ordenes llegan tarde ---
        cola_angulo.append((t, th))
        while len(cola_angulo) > 1 and cola_angulo[1][0] <= t - m.retraso_log:
            cola_angulo.pop(0)
        th_visto = math.degrees(cola_angulo[0][1])
        if fase == 1 and t >= m.t_impulso + m.latencia:
            fase, t_fase[2] = 2, t
        if fase == 2 and t_cambio_pedido is None and th_visto >= m.angulo_cambio:
            t_cambio_pedido = t
        if fase == 2 and t_cambio_pedido is not None and t >= t_cambio_pedido + m.latencia:
            fase, t_fase[3] = 3, t
        # --- firmware a 500 Hz ---
        if i % CTRL_EVERY == 0:
            h = DT * CTRL_EVERY
            if fase == 1:
                q_des, empuje = 0.0, 65535.0
            elif fase == 2:
                q_des, empuje = m.q_giro, m.cmd_giro
            else:
                # send_hover_setpoint: PID de actitud (Kp 6) sobre el pitch de Euler y
                # lazo de vz que, cayendo, satura el empuje. Valido solo lejos de +-90.
                # El lazo de velocidad horizontal pide hasta 20 grados para frenar vx.
                pitch_des = max(-20.0, min(20.0, 25.0 * vx))
                err_ang = pitch_des - math.degrees(math.atan2(math.sin(th), math.cos(th)))
                q_des = max(-720.0, min(720.0, 6.0 * err_ang))
                vz_des = max(-1.0, min(1.0, 2.0 * (0.0 - z)))
                empuje = max(20000.0, min(65535.0, d.hover_cmd + 1000.0 * 20.0 * (vz_des - vz)))
            err = q_des - math.degrees(q)
            integ = max(-33.3, min(33.3, integ + err * h))
            d_raw = (err - prev_err) / h
            prev_err = err
            a = h / (h + 1.0 / (2 * math.pi * 30.0))
            d_filt += a * (d_raw - d_filt)
            salida = max(-32767.0, min(32767.0, 250.0 * err + 500.0 * integ + 2.5 * d_filt))
            c_del, c_tras = empuje - salida / 2.0, empuje + salida / 2.0
            exceso = max(c_del, c_tras) - 65535.0
            if exceso > 0:                       # el firmware baja el empuje, no el torque
                c_del, c_tras = c_del - exceso, c_tras - exceso
            cmds = [max(0.0, min(65535.0, c_del)), max(0.0, min(65535.0, c_tras))]
        # --- planta ---
        for k in (0, 1):
            objetivo = d.escala_empuje * empuje_total_n(cmds[k]) / 2.0
            tau = d.tau_sube if objetivo > f_par[k] else d.tau_baja
            f_par[k] += DT * (objetivo - f_par[k]) / tau
        f = f_par[0] + f_par[1]
        torque = BRAZO * (f_par[1] - f_par[0])
        vx += DT * (-(f / masa) * math.sin(th))
        vz += DT * ((f / masa) * math.cos(th) - G)
        x += DT * vx
        z += DT * vz
        q += DT * torque / d.j
        th += DT * q
        z_min, z_max = min(z_min, z), max(z_max, z)
        x_min, x_max = min(x_min, x), max(x_max, x)
        q_max = max(q_max, abs(math.degrees(q)))
        if traza and i % 10 == 0:
            filas.append((round(t, 4), fase, x, z, vx, vz, math.degrees(th), math.degrees(q), f, cmds[0], cmds[1]))
    err_fin = abs(math.degrees(math.atan2(math.sin(th), math.cos(th))))
    vueltas = math.degrees(th) / 360.0
    ok = 0.9 < vueltas < 1.1 and err_fin < 15 and abs(math.degrees(q)) < 80 and abs(vz) < 0.5
    out = dict(ok=ok, vueltas=vueltas, sube=z_max, baja=-z_min, x_min=x_min, x_max=x_max, z_fin=z,
               err_fin=err_fin, q_max=q_max, t_giro=t_fase.get(3, float("nan")) - t_fase.get(2, float("nan")),
               acel_max=d.escala_empuje * empuje_total_n(65535) / masa)
    if traza:
        out["filas"] = filas
    return out


def monte_carlo(d: Dron, m: Maniobra, n: int, rng: random.Random) -> list[dict]:
    res = []
    for _ in range(n):
        dd = replace(d, j=d.j * rng.uniform(0.8, 1.2), escala_empuje=rng.uniform(0.85, 1.0),
                     tau_sube=d.tau_sube * rng.uniform(0.7, 1.3), tau_baja=d.tau_baja * rng.uniform(0.7, 1.3),
                     hover_cmd=d.hover_cmd * rng.uniform(0.97, 1.03))
        mm = replace(m, latencia=rng.uniform(0.010, 0.040), retraso_log=rng.uniform(0.015, 0.045),
                     tilt0=rng.uniform(-4, 4), vz0=rng.uniform(-0.1, 0.1))
        res.append(simular(dd, mm))
    return res


def pct(v: list[float], p: float) -> float:
    v = sorted(v)
    return v[min(len(v) - 1, max(0, round(p / 100 * (len(v) - 1))))]


def main() -> None:
    raiz = Path(__file__).resolve().parents[3]
    out_data = raiz / "results" / "data" / "backflip" / "2026-09-18"
    out_graph = raiz / "results" / "graphs" / "backflip" / "2026-09-18"
    out_data.mkdir(parents=True, exist_ok=True)
    out_graph.mkdir(parents=True, exist_ok=True)
    drones = [Dron("Dron 1", 45700.0), Dron("Dron 2", 41400.0), Dron("CF2.1 sin marcadores (28 g)", 33500.0)]
    lineas = []
    trazas = {}
    for d in drones:
        # Barrido corto del diseno: el que mas corridas completa y, a igualdad, el de
        # menor envolvente vertical (lo que sube mas lo que cae), que es lo que limita la sala.
        mejor = None
        for t_imp in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
            for q_g in (900.0, 1100.0, 1300.0):
                for ang in (270.0, 285.0, 300.0):
                    m = Maniobra(t_impulso=t_imp, q_giro=q_g, angulo_cambio=ang)
                    r = monte_carlo(d, m, 40, random.Random(7))
                    clave = (sum(x["ok"] for x in r),
                             -pct([x["sube"] for x in r], 95) - pct([x["baja"] for x in r], 95))
                    if mejor is None or clave > mejor[0]:
                        mejor = (clave, m)
        m = mejor[1]
        nominal = simular(d, m, traza=True)
        trazas[d.nombre] = nominal.pop("filas")
        mc = monte_carlo(d, m, 500, random.Random(20260918))
        exito = sum(x["ok"] for x in mc)
        sube95, baja95 = pct([x["sube"] for x in mc], 95), pct([x["baja"] for x in mc], 95)
        atras95 = -pct([x["x_min"] for x in mc], 5)
        adel95 = pct([x["x_max"] for x in mc], 95)
        lineas += [
            f"== {d.nombre}: hover {d.hover_cmd:.0f}/65535 -> masa {1000 * d.masa:.1f} g, "
            f"aceleracion maxima {nominal['acel_max']:.1f} m/s2 ({nominal['acel_max'] / G:.2f} g)",
            f"   diseno: impulso {m.t_impulso:.2f} s, giro {m.q_giro:.0f} grados/s, cambio a {m.angulo_cambio:.0f} grados",
            f"   nominal: ok={nominal['ok']} vueltas={nominal['vueltas']:.3f} sube={nominal['sube']:.2f} m "
            f"baja={nominal['baja']:.2f} m x=[{nominal['x_min']:.2f}, {nominal['x_max']:.2f}] m "
            f"q_max={nominal['q_max']:.0f} grados/s giro={nominal['t_giro']:.2f} s",
            f"   Monte Carlo 500: exito {exito}/500 ({exito / 5:.1f}%), sube p95 {sube95:.2f} m, baja p95 {baja95:.2f} m, "
            f"peor caida {max(x['baja'] for x in mc):.2f} m, x p95 [-{atras95:.2f}, +{adel95:.2f}] m",
        ]
        nombre = d.nombre.split(" (")[0].replace(" ", "_").replace(".", "")
        with open(out_data / f"rate_monte_carlo_{nombre}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(mc[0].keys()))
            w.writeheader()
            w.writerows(mc)
        with open(out_data / f"rate_trayectoria_nominal_{nombre}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow("t_s fase x_m z_m vx_mps vz_mps pitch_deg pitch_rate_degps empuje_N cmd_delantero cmd_trasero".split())
            w.writerows(trazas[d.nombre])
    texto = "\n".join(lineas)
    (out_data / "rate_resumen.txt").write_text(texto + "\n", encoding="utf-8")
    print(texto)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    for nombre, filas in trazas.items():
        t = [f[0] for f in filas]
        ax[0].plot([f[2] for f in filas], [f[3] for f in filas], label=nombre)
        ax[1].plot(t, [f[6] for f in filas])
        ax[2].plot(t, [f[3] for f in filas])
    ax[0].set(xlabel="x [m]", ylabel="z relativo [m]", title="Trayectoria nominal")
    ax[0].axis("equal")
    ax[0].legend(fontsize=7)
    ax[1].set(xlabel="t [s]", ylabel="pitch acumulado [grados]", title="Rotacion")
    ax[1].axhline(360, ls="--", c="gray")
    ax[2].set(xlabel="t [s]", ylabel="z relativo [m]", title="Altura")
    for a in ax:
        a.grid(True)
    fig.tight_layout()
    fig.savefig(out_graph / "rate_firmware_de_fabrica.png", dpi=160)


if __name__ == "__main__":
    main()

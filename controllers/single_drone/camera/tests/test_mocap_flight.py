"""Protecciones del backend de mocap. Sin MQTT, sin radio y sin motores.

Se comprueba lo que puede estrellar el dron o dejarlo fuera de la red:

* que la ventana de altura se respete al integrar la peticion vertical;
* que el geofence recorte **solo** lo que sale del radio, para que el operador
  siempre pueda volver hacia adentro;
* que sin poses frescas del mocap no se vuele a ciegas;
* que solo haya **un** escritor de setpoints.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\controllers\\single_drone\\camera\\tests\\test_mocap_flight.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CAMERA_DIR = TESTS_DIR.parent
if str(CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CAMERA_DIR))

import mocap_flight as mf  # noqa: E402
from control_with_marker import MAX_HEIGHT_M, MIN_HEIGHT_M  # noqa: E402
from marker_mocap import Pose  # noqa: E402

results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


def pose(x=0.0, y=0.0, z=0.0, edad_s=0.0) -> Pose:
    return Pose(x, y, z, 0.0, 0.0, 0.0, time.monotonic() - edad_s)


def backend() -> mf.MocapFlight:
    """Construye el backend sin abrir MQTT ni radio.

    `MocapReceiver` no toca la red hasta `start()`, que aqui no se llama.
    """
    return mf.MocapFlight(
        "radio://0/80/2M/E7E7E7E7E7", topico_dron="mocap/prueba",
        broker="127.0.0.1", puerto=1883,
    )


# ------------------------------------------------------- ventana de altura


def test_la_altura_no_se_sale_de_la_ventana() -> None:
    f = backend()
    despegue = pose(z=1.0)
    piso, techo = 1.0 + MIN_HEIGHT_M, 1.0 + MAX_HEIGHT_M

    objetivo = despegue.z + 0.5
    for _ in range(2000):                      # 100 s pidiendo subir
        objetivo = f._nuevo_objetivo(objetivo, despegue, +1.0)
    anotar("subir sin parar se detiene en el techo",
           abs(objetivo - techo) < 1e-9, f"{objetivo:.3f} vs {techo:.3f}")

    for _ in range(2000):                      # y bajar, en el piso
        objetivo = f._nuevo_objetivo(objetivo, despegue, -1.0)
    anotar("bajar sin parar se detiene en el piso",
           abs(objetivo - piso) < 1e-9, f"{objetivo:.3f} vs {piso:.3f}")


def test_sin_peticion_vertical_la_altura_se_queda() -> None:
    """Al soltar el gesto el dron mantiene la altura, no cae ni sigue subiendo."""
    f = backend()
    despegue = pose(z=0.4)
    objetivo = despegue.z + 0.45
    for _ in range(200):
        objetivo = f._nuevo_objetivo(objetivo, despegue, 0.0)
    anotar("sin peticion la altura no se mueve",
           abs(objetivo - (despegue.z + 0.45)) < 1e-9, f"{objetivo:.3f}")


def test_sin_despegue_no_hay_objetivo() -> None:
    f = backend()
    anotar("en tierra no se integra altura",
           f._nuevo_objetivo(None, None, 1.0) is None, "")


# -------------------------------------------------------------- geofence


def test_el_geofence_solo_recorta_lo_que_sale() -> None:
    f = backend()
    despegue = pose(0.0, 0.0, 0.0)
    fuera = pose(f.radio_max_m + 0.05, 0.0, 0.5)

    vx, vy = f._recortar_por_radio(fuera, despegue, 0.12, 0.0)
    anotar("en el limite se anula lo que se aleja",
           (vx, vy) == (0.0, 0.0), f"({vx}, {vy})")

    vx, vy = f._recortar_por_radio(fuera, despegue, -0.12, 0.0)
    anotar("en el limite se deja volver hacia adentro",
           (vx, vy) == (-0.12, 0.0), f"({vx}, {vy})")

    dentro = pose(0.1, 0.1, 0.5)
    vx, vy = f._recortar_por_radio(dentro, despegue, 0.12, 0.05)
    anotar("dentro del radio no se toca nada",
           (vx, vy) == (0.12, 0.05), f"({vx}, {vy})")


def test_sin_punto_de_despegue_no_se_recorta() -> None:
    f = backend()
    vx, vy = f._recortar_por_radio(pose(9.0, 9.0, 1.0), None, 0.1, 0.1)
    anotar("sin referencia de despegue no se inventa un geofence",
           (vx, vy) == (0.1, 0.1), f"({vx}, {vy})")


# ------------------------------------------------------- mocap y estado


def test_una_pose_vieja_no_cuenta_como_fresca() -> None:
    """Volar con una pose de hace dos segundos es volar a ciegas."""
    f = backend()
    f.dron_rx._pose = pose(z=0.5, edad_s=mf.MOCAP_TIMEOUT_S + 0.5)
    anotar("una pose caducada se descarta", f._pose() is None, "")
    anotar("y la altura pasa a desconocida", f.height_m is None, "")

    f.dron_rx._pose = pose(z=0.5)
    anotar("una pose fresca si vale", f._pose() is not None, "")


def test_la_altura_es_sobre_el_punto_de_despegue() -> None:
    f = backend()
    f._suelo_z = 1.20
    f.dron_rx._pose = pose(z=1.65)
    anotar("en tierra, altura sobre el suelo observado",
           abs(f.height_m - 0.45) < 1e-9, f"{f.height_m}")

    f.pose_despegue = pose(z=1.30)
    anotar("volando, altura sobre el punto de despegue",
           abs(f.height_m - 0.35) < 1e-9, f"{f.height_m}")


def test_en_tierra_no_se_aceptan_velocidades() -> None:
    f = backend()
    f.set_velocity(0.2, 0.2, 0.1)
    anotar("en tierra set_velocity no guarda nada",
           f._comando == (0.0, 0.0, 0.0), f"{f._comando}")


def test_durante_una_maniobra_no_se_aceptan_velocidades() -> None:
    """Mientras despega o aterriza, la camara no manda."""
    f = backend()
    f.flying = True
    f.busy = True
    f.set_velocity(0.2, 0.2, 0.1)
    anotar("ocupado ignora set_velocity", f._comando == (0.0, 0.0, 0.0),
           f"{f._comando}")


def test_tras_la_emergencia_no_se_vuelve_a_mover() -> None:
    f = backend()
    f.flying = True
    f.emergency = True
    f.set_velocity(0.2, 0.0, 0.0)
    anotar("en emergencia set_velocity no hace nada",
           f._comando == (0.0, 0.0, 0.0), f"{f._comando}")


# --------------------------------------------------- un solo escritor


def test_el_aterrizaje_no_manda_setpoints() -> None:
    """El lazo es el unico que escribe en el commander.

    Si el aterrizaje tambien enviara, los dos setpoints se pisarian a 20 Hz y
    el dron obedeceria al ultimo que llegase.
    """
    fuente = (CAMERA_DIR / "mocap_flight.py").read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("def _aterrizar("):fuente.index("# -- Comandos")]
    sin_envio = "_enviar(" not in cuerpo
    anotar("_aterrizar no llama a _enviar", sin_envio,
           "" if sin_envio else "manda setpoints en paralelo al lazo")

    inicio = fuente.index("def _lazo_de_control(")
    fin = fuente.index("def _nuevo_objetivo(")
    anotar("el lazo si envia", "_enviar(" in fuente[inicio:fin], "")


def test_la_envolvente_viene_del_controlador_de_marker() -> None:
    """Un solo limite de altura en el repositorio, no dos."""
    anotar("el techo es el mismo que el del marker",
           mf.MAX_HEIGHT_M == MAX_HEIGHT_M, f"{mf.MAX_HEIGHT_M}")
    anotar("el piso es el mismo que el del marker",
           mf.MIN_HEIGHT_M == MIN_HEIGHT_M, f"{mf.MIN_HEIGHT_M}")


def main() -> int:
    print("Backend de mocap del Dron 1")
    print("Sin MQTT, sin radio y sin motores.\n")
    print(f"  techo {MAX_HEIGHT_M} m   piso {MIN_HEIGHT_M} m   "
          f"radio {mf.MAX_RADIUS_M} m")
    print(f"  timeout de mocap {mf.MOCAP_TIMEOUT_S} s   "
          f"hover {mf.ALTURA_HOVER_M} m\n")

    for prueba in (
        test_la_altura_no_se_sale_de_la_ventana,
        test_sin_peticion_vertical_la_altura_se_queda,
        test_sin_despegue_no_hay_objetivo,
        test_el_geofence_solo_recorta_lo_que_sale,
        test_sin_punto_de_despegue_no_se_recorta,
        test_una_pose_vieja_no_cuenta_como_fresca,
        test_la_altura_es_sobre_el_punto_de_despegue,
        test_en_tierra_no_se_aceptan_velocidades,
        test_durante_una_maniobra_no_se_aceptan_velocidades,
        test_tras_la_emergencia_no_se_vuelve_a_mover,
        test_el_aterrizaje_no_manda_setpoints,
        test_la_envolvente_viene_del_controlador_de_marker,
    ):
        prueba()

    ancho = max(len(nombre) for nombre, _, _ in results)
    fallos = 0
    for nombre, ok, detalle in results:
        marca = "OK  " if ok else "FALLA"
        extra = f"   {detalle}" if detalle else ""
        print(f"  [{marca}] {nombre.ljust(ancho)}{extra}")
        fallos += not ok

    print()
    if fallos:
        print(f"{fallos} de {len(results)} comprobaciones fallaron. NO VOLAR.")
        return 1
    print(f"Las {len(results)} comprobaciones pasaron.")
    print("Esto valida la logica, no el vuelo. Primera prueba sin helices y")
    print("con el mocap confirmado en pantalla antes de despegar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

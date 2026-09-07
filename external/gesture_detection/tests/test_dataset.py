"""Dataset de gestos y comparacion 3D/2D. Sin camara y sin MediaPipe.

Se construyen tomas sinteticas de dos gestos, se guardan, se releen y se pasan
por la misma evaluacion que usa `comparar_2d_3d.py`. Lo que se verifica:

* que una toma sobreviva al viaje a disco sin perder nada;
* que no se sobrescriba material grabado;
* que la evaluacion sea **leave-one-out** de verdad, que es lo unico que
  impide que cualquier metodo parezca perfecto;
* que dos gestos separables den exactitud alta y dos indistinguibles no.

Uso, desde la raiz del repositorio:

    .\\.venv\\Scripts\\python.exe .\\external\\gesture_detection\\tests\\test_dataset.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
GESTURE_DIR = TESTS_DIR.parent
if str(GESTURE_DIR) not in sys.path:
    sys.path.insert(0, str(GESTURE_DIR))

import comparar_2d_3d as cmp  # noqa: E402
from dataset.storage import (  # noqa: E402
    N_LANDMARKS,
    Toma,
    cargar,
    cargar_todas,
    guardar,
    resumen,
)
from pose.normalize import (  # noqa: E402
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

results: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
    results.append((nombre, bool(ok), detalle))


def toma_sintetica(gesto: str, numero: int, *, persona="prueba",
                   orientacion=0.0, fps=30.0, duracion=2.0,
                   semilla=0) -> Toma:
    """Un cuerpo de pie con las munecas moviendose segun el gesto."""
    rng = np.random.default_rng(semilla)
    t = np.arange(0.0, duracion, 1.0 / fps)
    W = np.zeros((len(t), N_LANDMARKS, 3))
    W[:, LEFT_HIP] = [0.13, 0.0, 0.0]
    W[:, RIGHT_HIP] = [-0.13, 0.0, 0.0]
    W[:, LEFT_SHOULDER] = [0.19, 0.50, 0.0]
    W[:, RIGHT_SHOULDER] = [-0.19, 0.50, 0.0]

    if gesto == "aplauso":                       # manos que se juntan y separan
        sep = 0.30 * (1 + np.cos(2 * np.pi * 1.5 * t)) / 2 + 0.02
        W[:, RIGHT_WRIST] = np.stack([-sep, np.full(len(t), 0.30),
                                      np.full(len(t), 0.35)], axis=1)
        W[:, LEFT_WRIST] = np.stack([sep, np.full(len(t), 0.30),
                                     np.full(len(t), 0.35)], axis=1)
    else:                                        # brazos colgando, quietos
        W[:, RIGHT_WRIST] = [-0.22, -0.15, 0.02]
        W[:, LEFT_WRIST] = [0.22, -0.15, 0.02]
    W[:, RIGHT_ELBOW] = (W[:, RIGHT_SHOULDER] + W[:, RIGHT_WRIST]) / 2
    W[:, LEFT_ELBOW] = (W[:, LEFT_SHOULDER] + W[:, LEFT_WRIST]) / 2
    W = W + rng.normal(0.0, 0.004, W.shape)

    # La imagen: proyeccion sencilla, y = hacia abajo como en un encuadre real.
    P = np.stack([0.5 + W[:, :, 0] * 0.6, 0.6 - W[:, :, 1] * 0.6], axis=2)
    V = np.full((len(t), N_LANDMARKS), 0.95)
    return Toma(persona, gesto, numero, orientacion, W, P, V, t)


# --------------------------------------------------------------- guardado


def test_una_toma_sobrevive_al_disco() -> None:
    carpeta = Path(tempfile.mkdtemp())
    try:
        original = toma_sintetica("aplauso", 1)
        ruta = guardar(carpeta, original)
        leida = cargar(ruta)
        igual = (
            leida.persona == original.persona
            and leida.gesto == original.gesto
            and leida.numero == original.numero
            and leida.orientacion_deg == original.orientacion_deg
            and np.allclose(leida.world, original.world, atol=1e-5)
            and np.allclose(leida.imagen, original.imagen, atol=1e-5)
            and np.allclose(leida.timestamps, original.timestamps)
        )
        anotar("la toma vuelve igual del disco", igual, ruta.name)
        anotar("guarda las dos representaciones",
               leida.world.shape[2] == 3 and leida.imagen.shape[2] == 2,
               f"3D {leida.world.shape}  2D {leida.imagen.shape}")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def test_no_se_sobrescribe_material_grabado() -> None:
    carpeta = Path(tempfile.mkdtemp())
    try:
        t = toma_sintetica("aplauso", 1)
        a, b = guardar(carpeta, t), guardar(carpeta, t)
        anotar("dos tomas con el mismo nombre no se pisan", a != b,
               f"{a.name} / {b.name}")
        anotar("las dos quedan en disco", len(cargar_todas(carpeta)) == 2, "")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def test_el_resumen_cuenta_lo_que_hay() -> None:
    tomas = [toma_sintetica("aplauso", i) for i in range(3)]
    tomas += [toma_sintetica("reposo", i) for i in range(2)]
    texto = resumen(tomas)
    anotar("el resumen cuenta gestos", "aplauso 3" in texto and "reposo 2" in texto,
           texto.splitlines()[0])


def test_metadatos_de_la_toma() -> None:
    t = toma_sintetica("aplauso", 7, duracion=2.0, fps=30.0)
    anotar("duracion y fps de la toma",
           abs(t.duracion_s - 2.0) < 0.05 and abs(t.fps - 30.0) < 1.0,
           f"{t.duracion_s:.2f} s, {t.fps:.1f} fps")


# ------------------------------------------------------------- evaluacion


def _rasgos(tomas, hacer):
    salida = [hacer(t) for t in tomas]
    return [r for r in salida if r is not None], sum(r is None for r in salida)


def test_los_rasgos_salen_de_las_dos_representaciones() -> None:
    t = toma_sintetica("aplauso", 1)
    r3, r2 = cmp.rasgos_3d(t), cmp.rasgos_2d(t)
    anotar("rasgos 3D: 4 articulaciones x 3",
           r3 is not None and r3.shape[1] == 12,
           f"{None if r3 is None else r3.shape}")
    anotar("rasgos 2D: 4 articulaciones x 2",
           r2 is not None and r2.shape[1] == 8,
           f"{None if r2 is None else r2.shape}")


def test_dos_gestos_distintos_se_separan() -> None:
    tomas = [toma_sintetica("aplauso", i, semilla=i) for i in range(4)]
    tomas += [toma_sintetica("reposo", i, semilla=10 + i) for i in range(4)]
    for nombre, hacer in (("3D", cmp.rasgos_3d), ("2D", cmp.rasgos_2d)):
        rasgos, faltan = _rasgos(tomas, hacer)
        r = cmp.evaluar(cmp.matriz_de_distancias(rasgos),
                        [t.gesto for t in tomas])
        anotar(f"{nombre}: aplauso y reposo se separan",
               r["exactitud"] == 1.0 and r["separacion"] > 2.0,
               f"exactitud {100*r['exactitud']:.0f} %, "
               f"separacion {r['separacion']:.1f}x")


def test_dos_etiquetas_del_mismo_gesto_no_se_separan() -> None:
    """El control negativo: si la evaluacion diera bien aqui, no mediria nada."""
    tomas = [toma_sintetica("aplauso", i, semilla=i) for i in range(8)]
    etiquetas = ["a" if i % 2 == 0 else "b" for i in range(8)]
    rasgos, _ = _rasgos(tomas, cmp.rasgos_3d)
    r = cmp.evaluar(cmp.matriz_de_distancias(rasgos), etiquetas)
    anotar("etiquetas arbitrarias no se separan", r["exactitud"] < 0.85,
           f"exactitud {100*r['exactitud']:.0f} %")


def test_la_evaluacion_deja_fuera_la_propia_toma() -> None:
    """Sin leave-one-out, la distancia de una toma consigo misma es 0 y todo
    metodo da 100 %. Es la trampa mas facil de cometer."""
    tomas = [toma_sintetica("aplauso", i, semilla=i) for i in range(3)]
    tomas += [toma_sintetica("reposo", i, semilla=5 + i) for i in range(3)]
    rasgos, _ = _rasgos(tomas, cmp.rasgos_3d)
    D = cmp.matriz_de_distancias(rasgos)
    anotar("la diagonal de la matriz es cero", np.allclose(np.diag(D), 0.0), "")
    # Con una etiqueta unica por toma, ninguna tiene companera: la exactitud
    # tiene que ser 0. Si se usara la diagonal seria 100 %.
    unicas = [f"g{i}" for i in range(len(rasgos))]
    r = cmp.evaluar(D, unicas)
    anotar("con etiquetas unicas la exactitud es cero", r["exactitud"] == 0.0,
           f"exactitud {100*r['exactitud']:.0f} %")


def test_una_toma_sin_pose_se_descarta() -> None:
    t = toma_sintetica("aplauso", 1)
    rota = Toma(t.persona, t.gesto, t.numero, t.orientacion_deg,
                np.full_like(t.world, np.nan), np.full_like(t.imagen, np.nan),
                np.zeros_like(t.visibility), t.timestamps)
    anotar("una toma sin pose no produce rasgos",
           cmp.rasgos_3d(rota) is None and cmp.rasgos_2d(rota) is None, "")


def test_la_confusion_suma_las_tomas() -> None:
    etiquetas = ["a", "a", "b", "b"]
    texto = cmp.confusion(etiquetas, ["a", "b", "b", "b"])
    anotar("la matriz de confusion se dibuja", "real \\ leido" in texto,
           texto.splitlines()[0].strip()[:28])


def main() -> int:
    print("Dataset de gestos y comparacion 3D/2D")
    print("Sin camara, sin MediaPipe y sin dron.\n")

    for prueba in (
        test_una_toma_sobrevive_al_disco,
        test_no_se_sobrescribe_material_grabado,
        test_el_resumen_cuenta_lo_que_hay,
        test_metadatos_de_la_toma,
        test_los_rasgos_salen_de_las_dos_representaciones,
        test_dos_gestos_distintos_se_separan,
        test_dos_etiquetas_del_mismo_gesto_no_se_separan,
        test_la_evaluacion_deja_fuera_la_propia_toma,
        test_una_toma_sin_pose_se_descarta,
        test_la_confusion_suma_las_tomas,
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
        print(f"{fallos} de {len(results)} comprobaciones fallaron.")
        return 1
    print(f"Las {len(results)} comprobaciones pasaron.")
    print("Esto valida el mecanismo con material sintetico. Que 3D o 2D gane "
          "depende de las grabaciones reales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

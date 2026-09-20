"""Ningun parametro tapa a una funcion que su propia funcion llama. Sin camara.

El 2026-09-18 `seguir_persona.bucle` tenia un parametro booleano `mostrar` y
ademas llamaba a la funcion importada `mostrar(...)`: dentro de `bucle` el
nombre era el booleano y el programa moria con `'bool' object is not callable`
al primer frame. Ni compilar ni `--help` lo detectan, porque el bucle solo
corre con camara. Esta prueba lo busca en el arbol sintactico.

Uso, desde la raiz del repositorio::

    .\\.venv\\Scripts\\python.exe -m pytest -q .\\external\\gesture_detection\\tests\\test_nombres_tapados.py
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

ARCHIVOS = [
    "external/gesture_detection/seguir_persona.py",
    "external/gesture_detection/probar_vocabulario.py",
    "external/gesture_detection/probar_gestos_3d.py",
    "controllers/single_drone/camera/control_camara_dron1.py",
]


def _tapados(ruta: Path) -> list[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    importados = {
        alias.asname or alias.name
        for nodo in ast.walk(arbol) if isinstance(nodo, ast.ImportFrom)
        for alias in nodo.names
    }
    problemas = []
    for funcion in ast.walk(arbol):
        if not isinstance(funcion, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parametros = {a.arg for a in funcion.args.args + funcion.args.kwonlyargs}
        llamados = {
            n.func.id for n in ast.walk(funcion)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        for nombre in parametros & llamados & importados:
            problemas.append(f"{funcion.name}: el parametro `{nombre}` tapa a la funcion importada")
    return problemas


@pytest.mark.parametrize("archivo", ARCHIVOS)
def test_ningun_parametro_tapa_una_funcion_importada(archivo):
    assert _tapados(RAIZ / archivo) == []

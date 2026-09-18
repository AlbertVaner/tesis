"""Los tests de esta carpeta nunca escriben en `cache/` del repositorio."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _memoria_de_empuje_temporal(monkeypatch, tmp_path):
    import dron_robotat

    monkeypatch.setattr(dron_robotat, "THRUST_MEMORY_PATH", tmp_path / "empuje.json")

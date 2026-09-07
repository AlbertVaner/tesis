"""Base de los registros CSV de sesión: archivo por corrida, reloj y análisis.

Cada corrida crea `results/data/<carpeta>/<AAAA-MM-DD>/<prefijo>_<marca>.csv`
con una fila por evento o muestra y `t_s` relativo al inicio. Al cerrar, la
subclase puede generar las gráficas implementando `_analyze`.
"""

from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


class CsvSession:
    def __init__(self, columns: list[str], *, folder_name: str, filename_prefix: str) -> None:
        self.columns = list(columns)
        self.folder_name = folder_name
        self.filename_prefix = filename_prefix
        self._lock = threading.RLock()
        self._file = None
        self._writer: csv.DictWriter | None = None
        self._t0 = 0.0
        self.path: Path | None = None
        self.analysis_path: Path | None = None

    @property
    def active(self) -> bool:
        return self._writer is not None

    def elapsed_s(self) -> float:
        return round(time.monotonic() - self._t0, 4)

    def start(self) -> Path:
        with self._lock:
            self.stop(generate_graphs=False)
            now = datetime.now()
            folder = RESULTS_DIR / "data" / self.folder_name / now.strftime("%Y-%m-%d")
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder / f"{self.filename_prefix}_{now:%Y%m%d_%H%M%S}.csv"
            self._file = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._file, fieldnames=self.columns)
            self._writer.writeheader()
            self._t0 = time.monotonic()
            return self.path

    def _base_row(self, **values) -> dict:
        return {column: "" for column in self.columns} | {"t_s": self.elapsed_s()} | values

    def write(self, row: dict, *, flush: bool = False) -> bool:
        """Escribe una fila si la sesión está activa; devuelve si se escribió."""
        with self._lock:
            if self._writer is None:
                return False
            self._writer.writerow(row)
            if flush:
                self._file.flush()
            return True

    def stop(self, *, generate_graphs: bool = True) -> Path | None:
        with self._lock:
            was_active = self._file is not None
            if self._file is not None:
                self._file.flush()
                self._file.close()
            self._file = self._writer = None
            path = self.path
        if generate_graphs and was_active and path is not None and path.exists():
            try:
                self.analysis_path = self._analyze(path)
                if self.analysis_path is not None:
                    print(f"Graficas PDF guardadas en: {self.analysis_path}")
            except Exception as exc:
                print(f"ADVERTENCIA: no se pudieron generar las graficas PDF: {exc}")
        return path

    def _analyze(self, path: Path) -> Path | None:
        """Genera las gráficas de `path`; devuelve la carpeta creada o `None`."""
        return None

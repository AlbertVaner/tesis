"""Captura de webcam con selección automática y liberación segura."""

from __future__ import annotations

from collections.abc import Iterable

import cv2


class WebcamCapture:
    """Abre una webcam concreta o la primera disponible en un rango."""

    def __init__(self, capture: cv2.VideoCapture, camera_index: int):
        self._capture = capture
        self.camera_index = camera_index

    @classmethod
    def open(
        cls,
        camera_index: int | None = None,
        max_camera_index: int = 5,
    ) -> "WebcamCapture":
        if max_camera_index < 0:
            raise ValueError("max_camera_index no puede ser negativo")

        candidates = (
            [camera_index]
            if camera_index is not None
            else range(max_camera_index + 1)
        )

        for index in cls._unique_indices(candidates):
            capture = cv2.VideoCapture(index)
            if not capture.isOpened():
                capture.release()
                continue

            success, _ = capture.read()
            if success:
                return cls(capture, index)

            capture.release()

        if camera_index is not None:
            detail = f"la cámara {camera_index}"
        else:
            detail = f"ninguna cámara entre los índices 0 y {max_camera_index}"
        raise RuntimeError(f"No se pudo abrir {detail}.")

    @staticmethod
    def _unique_indices(indices: Iterable[int]) -> list[int]:
        unique: list[int] = []
        for index in indices:
            if index < 0:
                raise ValueError("El índice de cámara no puede ser negativo")
            if index not in unique:
                unique.append(index)
        return unique

    def read(self):
        """Devuelve el mismo contrato `(success, frame)` de OpenCV."""
        return self._capture.read()

    def release(self) -> None:
        self._capture.release()

    def __enter__(self) -> "WebcamCapture":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


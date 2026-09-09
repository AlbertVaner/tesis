"""Dibujo del esqueleto y métricas del primer prototipo corporal."""

from __future__ import annotations

import cv2




def draw_pose(frame, landmarks, connections) -> None:
    """Dibuja conexiones y puntos usando coordenadas normalizadas."""
    if landmarks is None:
        return

    height, width = frame.shape[:2]

    for start, end in connections:
        first = landmarks[start]
        second = landmarks[end]
        if first.visibility <= 0.1 or second.visibility <= 0.1:
            continue
        start_point = (int(first.x * width), int(first.y * height))
        end_point = (int(second.x * width), int(second.y * height))
        cv2.line(frame, start_point, end_point, (0, 160, 255), 2)

    for landmark in landmarks:
        if landmark.visibility <= 0.1:
            continue
        point = (int(landmark.x * width), int(landmark.y * height))
        cv2.circle(frame, point, 3, (0, 255, 0), -1)

"""Dibujo del esqueleto y métricas del primer prototipo corporal."""

from __future__ import annotations

import cv2


KEY_LANDMARKS = (
    ("Hombro I", "LEFT_SHOULDER"),
    ("Hombro D", "RIGHT_SHOULDER"),
    ("Codo I", "LEFT_ELBOW"),
    ("Codo D", "RIGHT_ELBOW"),
    ("Muneca I", "LEFT_WRIST"),
    ("Muneca D", "RIGHT_WRIST"),
)


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


def key_landmark_visibilities(landmarks, landmark_enum) -> list[tuple[str, float]]:
    if landmarks is None:
        return [(label, 0.0) for label, _ in KEY_LANDMARKS]

    return [
        (label, float(landmarks[getattr(landmark_enum, name).value].visibility))
        for label, name in KEY_LANDMARKS
    ]


def draw_status_panel(
    frame,
    fps: float,
    camera_index: int,
    visibilities: list[tuple[str, float]],
    pose_detected: bool,
) -> None:
    """Muestra estado, FPS y visibilidad de hombros, codos y muñecas."""
    panel_height = 160
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], panel_height), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)

    state = "POSE DETECTADA" if pose_detected else "SIN DETECCION"
    average = (
        sum(value for _, value in visibilities) / len(visibilities)
        if pose_detected and visibilities
        else 0.0
    )
    lines = (
        "MODO POSE - SIN CLASIFICACION / SIN DRON",
        f"Camara: {camera_index} | FPS: {fps:.1f} | {state}",
        f"Visibilidad promedio: {average:.2f}",
        " | ".join(f"{label}: {value:.2f}" for label, value in visibilities[:3]),
        " | ".join(f"{label}: {value:.2f}" for label, value in visibilities[3:]),
    )

    for row, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (12, 26 + row * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )

    cv2.putText(
        frame,
        "Q = salir",
        (frame.shape[1] - 105, frame.shape[0] - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (240, 240, 240),
        1,
        cv2.LINE_AA,
    )

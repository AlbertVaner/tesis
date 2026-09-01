"""Métricas geométricas para diagnosticar landmarks de MediaPipe Hands."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2


FINGER_JOINTS = {
    "T": (
        ("WRIST", "THUMB_CMC", "THUMB_MCP"),
        ("THUMB_CMC", "THUMB_MCP", "THUMB_IP"),
        ("THUMB_MCP", "THUMB_IP", "THUMB_TIP"),
    ),
    "I": (
        ("WRIST", "INDEX_FINGER_MCP", "INDEX_FINGER_PIP"),
        ("INDEX_FINGER_MCP", "INDEX_FINGER_PIP", "INDEX_FINGER_DIP"),
        ("INDEX_FINGER_PIP", "INDEX_FINGER_DIP", "INDEX_FINGER_TIP"),
    ),
    "M": (
        ("WRIST", "MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP"),
        ("MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP"),
        ("MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP"),
    ),
    "A": (
        ("WRIST", "RING_FINGER_MCP", "RING_FINGER_PIP"),
        ("RING_FINGER_MCP", "RING_FINGER_PIP", "RING_FINGER_DIP"),
        ("RING_FINGER_PIP", "RING_FINGER_DIP", "RING_FINGER_TIP"),
    ),
    "m": (
        ("WRIST", "PINKY_MCP", "PINKY_PIP"),
        ("PINKY_MCP", "PINKY_PIP", "PINKY_DIP"),
        ("PINKY_PIP", "PINKY_DIP", "PINKY_TIP"),
    ),
}


@dataclass(frozen=True)
class HandMetrics:
    handedness: str
    confidence: float
    direction: str
    angles: dict[str, tuple[float, float, float]]


def joint_angle_degrees(first, vertex, third) -> float:
    """Calcula el ángulo 3D en ``vertex`` dentro del intervalo 0–180°."""
    vector_a = (
        first.x - vertex.x,
        first.y - vertex.y,
        first.z - vertex.z,
    )
    vector_b = (
        third.x - vertex.x,
        third.y - vertex.y,
        third.z - vertex.z,
    )
    norm_a = math.sqrt(sum(component * component for component in vector_a))
    norm_b = math.sqrt(sum(component * component for component in vector_b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0

    cosine = sum(a * b for a, b in zip(vector_a, vector_b)) / (norm_a * norm_b)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def analyze_hand(landmarks, landmark_enum, handedness: str | None, confidence: float) -> HandMetrics:
    angles: dict[str, tuple[float, float, float]] = {}
    for finger, joints in FINGER_JOINTS.items():
        angles[finger] = tuple(
            joint_angle_degrees(
                landmarks[getattr(landmark_enum, first_name).value],
                landmarks[getattr(landmark_enum, vertex_name).value],
                landmarks[getattr(landmark_enum, third_name).value],
            )
            for first_name, vertex_name, third_name in joints
        )

    wrist = landmarks[landmark_enum.WRIST.value]
    middle_mcp = landmarks[landmark_enum.MIDDLE_FINGER_MCP.value]
    delta_x = middle_mcp.x - wrist.x
    delta_y = middle_mcp.y - wrist.y
    if abs(delta_y) >= abs(delta_x):
        direction = "arriba" if delta_y < 0 else "abajo"
    else:
        direction = "derecha" if delta_x > 0 else "izquierda"

    return HandMetrics(
        handedness=handedness or "Unknown",
        confidence=confidence,
        direction=direction,
        angles=angles,
    )


def draw_hand_metrics_panel(frame, metrics: list[HandMetrics], start_y: int = 168) -> None:
    """Dibuja confianza, orientación y tres ángulos por dedo."""
    line_height = 21
    line_count = 2 + len(metrics) * 6
    panel_height = min(frame.shape[0] - start_y, line_count * line_height + 12)
    if panel_height <= 0:
        return

    panel_width = min(frame.shape[1], 430)
    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (0, start_y),
        (panel_width, start_y + panel_height),
        (20, 20, 20),
        -1,
    )
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)

    lines = ["MANOS: 21 PUNTOS | ANGULOS 3D APROXIMADOS"]
    if not metrics:
        lines.append("Sin manos detalladas")
    for hand in metrics:
        lines.append(
            f"{hand.handedness} conf:{hand.confidence:.2f} dir:{hand.direction}"
        )
        for finger, angles in hand.angles.items():
            values = "/".join(f"{angle:3.0f}" for angle in angles)
            lines.append(f"  {finger}  proximal/medio/distal: {values} grados")

    max_lines = max(1, (panel_height - 8) // line_height)
    for row, line in enumerate(lines[:max_lines]):
        cv2.putText(
            frame,
            line,
            (10, start_y + 19 + row * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )

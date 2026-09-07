import time


def distance_2d(p1, p2):
    if p1 is None or p2 is None:
        return float("inf")
    dx = p1.x - p2.x
    dy = p1.y - p2.y
    return (dx * dx + dy * dy) ** 0.5


def calculate_fps(prev_time):
    current_time = time.time()
    fps = 1.0 / (current_time - prev_time) if current_time > prev_time else 0.0
    return fps, current_time

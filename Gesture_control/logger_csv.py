import os
from datetime import datetime
from pathlib import Path
import pandas as pd

class GestureLogger:
    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self):
        if not self.csv_path.exists():
            df = pd.DataFrame(columns=[
                "timestamp",
                "command_raw",
                "command_filtered",
                "right_wrist_x",
                "right_wrist_y",
                "left_wrist_x",
                "left_wrist_y",
                "right_shoulder_x",
                "right_shoulder_y",
                "left_shoulder_x",
                "left_shoulder_y",
            ])
            df.to_csv(self.csv_path, index=False)

    def log(self, timestamp, command_raw, command_filtered, landmarks):
        row = {
            "timestamp": timestamp,
            "command_raw": command_raw,
            "command_filtered": command_filtered,
            "right_wrist_x": None,
            "right_wrist_y": None,
            "left_wrist_x": None,
            "left_wrist_y": None,
            "right_shoulder_x": None,
            "right_shoulder_y": None,
            "left_shoulder_x": None,
            "left_shoulder_y": None,
        }

        if landmarks is not None:
            row.update({
                "right_wrist_x": landmarks[16].x,
                "right_wrist_y": landmarks[16].y,
                "left_wrist_x": landmarks[15].x,
                "left_wrist_y": landmarks[15].y,
                "right_shoulder_x": landmarks[12].x,
                "right_shoulder_y": landmarks[12].y,
                "left_shoulder_x": landmarks[11].x,
                "left_shoulder_y": landmarks[11].y,
            })

        df = pd.DataFrame([row])
        df.to_csv(self.csv_path, mode="a", header=False, index=False)

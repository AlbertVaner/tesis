from pathlib import Path
import pandas as pd


class HandGestureLogger:
    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self):
        if not self.csv_path.exists():
            df = pd.DataFrame(columns=[
                "timestamp",
                "handedness",
                "command_raw",
                "command_filtered",
                "orientation",
                "thumb_extended",
                "index_extended",
                "middle_extended",
                "ring_extended",
                "pinky_extended",
                "wrist_x",
                "wrist_y",
                "thumb_tip_x",
                "thumb_tip_y",
                "index_tip_x",
                "index_tip_y",
                "middle_tip_x",
                "middle_tip_y",
                "ring_tip_x",
                "ring_tip_y",
                "pinky_tip_x",
                "pinky_tip_y",
            ])
            df.to_csv(self.csv_path, index=False)

    def log(self, timestamp, handedness, command_raw, command_filtered, landmarks, debug=None):
        debug = debug or {}

        row = {
            "timestamp": timestamp,
            "handedness": handedness,
            "command_raw": command_raw,
            "command_filtered": command_filtered,
            "orientation": debug.get("orientation"),
            "thumb_extended": debug.get("thumb"),
            "index_extended": debug.get("index"),
            "middle_extended": debug.get("middle"),
            "ring_extended": debug.get("ring"),
            "pinky_extended": debug.get("pinky"),
            "wrist_x": None,
            "wrist_y": None,
            "thumb_tip_x": None,
            "thumb_tip_y": None,
            "index_tip_x": None,
            "index_tip_y": None,
            "middle_tip_x": None,
            "middle_tip_y": None,
            "ring_tip_x": None,
            "ring_tip_y": None,
            "pinky_tip_x": None,
            "pinky_tip_y": None,
        }

        if landmarks is not None:
            row.update({
                "wrist_x": landmarks[0].x,
                "wrist_y": landmarks[0].y,
                "thumb_tip_x": landmarks[4].x,
                "thumb_tip_y": landmarks[4].y,
                "index_tip_x": landmarks[8].x,
                "index_tip_y": landmarks[8].y,
                "middle_tip_x": landmarks[12].x,
                "middle_tip_y": landmarks[12].y,
                "ring_tip_x": landmarks[16].x,
                "ring_tip_y": landmarks[16].y,
                "pinky_tip_x": landmarks[20].x,
                "pinky_tip_y": landmarks[20].y,
            })

        pd.DataFrame([row]).to_csv(
            self.csv_path,
            mode="a",
            header=False,
            index=False,
        )

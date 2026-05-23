import cv2

try:
    import mediapipe as mp
    mp_drawing = mp.solutions.drawing_utils
    mp_pose = mp.solutions.pose
except Exception:
    from mediapipe.python import solutions as mp
    mp_drawing = mp.drawing_utils
    mp_pose = mp.pose

class PoseTracker:
    def __init__(self, min_detection_confidence=0.6, min_tracking_confidence=0.6):
        self.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def process(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self.pose.process(rgb_frame)
        rgb_frame.flags.writeable = True

        if results.pose_landmarks is None:
            return frame, None

        annotated_frame = frame.copy()
        mp_drawing.draw_landmarks(
            annotated_frame,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
            mp_drawing.DrawingSpec(color=(0, 128, 255), thickness=2, circle_radius=2),
        )
        return annotated_frame, results.pose_landmarks.landmark

    def close(self):
        self.pose.close()

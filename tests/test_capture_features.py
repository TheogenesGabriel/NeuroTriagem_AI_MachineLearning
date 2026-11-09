"""Captura para o RF: observações ausentes, sessões e resultado final estável."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.arm_test_logic import ArmTestEngine, ArmTestState, Config
from core.facial_asymmetry_logic import FacialAsymmetryEngine, FacialConfig
from screens.arm_test_screen import ArmTestScreen


class CaptureFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.frame = np.zeros((180, 240, 3), dtype=np.uint8)

    def arm_engine(self):
        engine = ArmTestEngine.__new__(ArmTestEngine)
        engine.cfg = Config(test_duration_s=0.5, ema_alpha=0, invert_side=False)
        engine.device = "cpu"
        engine.model = Mock()
        engine.model.predict.return_value = [object()]
        engine.reset()
        return engine

    def facial_engine(self):
        engine = FacialAsymmetryEngine.__new__(FacialAsymmetryEngine)
        engine.cfg = FacialConfig(vote_window=2)
        engine.model = Mock()
        engine.reset()
        return engine

    def face_frame(self, engine, name=None):
        boxes = [] if name is None else [SimpleNamespace(
            cls=[0], conf=[0.9], xyxy=np.array([[10, 10, 30, 30]])
        )]
        engine.model.predict.return_value = [SimpleNamespace(boxes=boxes, names={0: name})]
        engine.process_frame(self.frame)

    def test_face_without_detection_is_not_normal(self):
        engine = self.facial_engine()
        self.assertIsNone(engine.get_features()["facial_asymmetry_score"])
        self.face_frame(engine)
        self.assertIsNone(engine.get_features()["facial_asymmetry_score"])
        self.face_frame(engine, "UnknownClass")
        self.assertIsNone(engine.get_features()["facial_asymmetry_score"])
        self.face_frame(engine, "Normal_Eyes")
        self.assertEqual(engine.get_features()["facial_asymmetry_score"], 0)

    def test_face_missing_frames_expire_observation_without_turning_normal(self):
        engine = self.facial_engine()
        self.face_frame(engine, "StrongPalsy_Mouth")
        self.face_frame(engine)
        self.assertEqual(engine.get_features()["facial_asymmetry_score"], 2)
        self.face_frame(engine)
        self.assertIsNone(engine.get_features()["facial_asymmetry_score"])
        self.face_frame(engine, "SlightPalsy_Eyes")
        engine.reset()
        self.assertIsNone(engine.get_features()["facial_asymmetry_score"])

    def test_arm_snapshot_is_final_and_resets_between_sessions(self):
        engine = self.arm_engine()
        missing = {"arm_ratio": None, "arm_weak_side_code": None}
        self.assertEqual(engine.get_features(), missing)
        engine.start()
        self.assertEqual(engine.get_features(), missing)
        engine.last_frame_time = 0
        normal_pose = {2: (0.3, 0.4), 3: (0.7, 0.4), 5: (0.7, 0.4), 7: (0.3, 0.4)}
        with patch("core.arm_test_logic.extract_pose", return_value=(normal_pose, "normal", 0.9)):
            with patch("core.arm_test_logic.time.time", return_value=1):
                engine.process_frame(self.frame)
        self.assertEqual(engine.state, ArmTestState.RESULT)
        self.assertEqual(engine.get_features(), {"arm_ratio": 0.0, "arm_weak_side_code": 0})
        # Moving after completion must not change the vector sent to the RF.
        changed_pose = dict(normal_pose)
        changed_pose[7] = (0.3, 0.8)
        with patch("core.arm_test_logic.extract_pose", return_value=(changed_pose, "normal", 0.9)):
            engine.process_frame(self.frame)
        self.assertGreater(engine.ratio, 0)
        self.assertEqual(engine.get_features(), {"arm_ratio": 0.0, "arm_weak_side_code": 0})
        engine.reset()
        self.assertEqual(engine.get_features(), missing)

    def test_entering_arm_screen_resets_prior_result(self):
        engine = self.arm_engine()
        engine.state = ArmTestState.RESULT
        engine._result_features = {"arm_ratio": 0.8, "arm_weak_side_code": 1}
        with patch("screens.arm_test_screen.ArmTestEngine", return_value=engine):
            screen = ArmTestScreen(on_next=Mock())
        try:
            with patch("screens.arm_test_screen.cv2.VideoCapture"):
                screen.start_camera()
            self.assertEqual(engine.state, ArmTestState.IDLE)
            self.assertIsNone(screen.get_features()["arm_ratio"])
        finally:
            screen.stop_camera()
            screen.close()
            screen.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

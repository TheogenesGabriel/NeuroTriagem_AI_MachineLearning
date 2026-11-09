"""Prazo, isolamento e ausência de observações no teste facial."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from core.facial_asymmetry_logic import FacialAsymmetryEngine, FacialConfig
from core.facial_test_session import FacialTestSession, FacialTestState


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FacialSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.session = FacialTestSession(20, clock=self.clock)

    def finish(self):
        self.clock.advance(self.session.duration_s)
        self.session.tick()

    def test_requires_manual_start_and_exposes_only_completed_results(self):
        self.session.record_frame(2)
        self.assertEqual(self.session.state, FacialTestState.IDLE)
        self.assertEqual(self.session.total_frames, 0)
        self.assertIsNone(self.session.get_features()["facial_asymmetry_score"])
        self.session.start()
        self.session.record_frame(0)
        self.assertIsNone(self.session.get_features()["facial_asymmetry_score"])
        self.finish()
        self.assertEqual(self.session.get_features()["facial_asymmetry_score"], 0)

    def test_expires_without_frames_and_missing_is_not_normal(self):
        self.session.start()
        self.assertEqual(self.session.remaining_seconds, 20)
        self.clock.advance(19.1)
        self.assertEqual(self.session.remaining_seconds, 1)
        self.assertEqual(self.session.state, FacialTestState.ACTIVE)
        self.clock.advance(0.9)
        self.assertEqual(self.session.tick(), FacialTestState.RESULT)
        self.assertEqual(self.session.remaining_seconds, 0)
        self.assertIsNone(self.session.result_severity)
        self.assertEqual(self.session.result_label, "Sem observação válida")
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (0, 0))

    def test_frames_without_valid_observations_are_counted_but_not_normal(self):
        self.session.start()
        for _ in range(5):
            self.session.record_frame(None)
        self.finish()
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (5, 0))
        self.assertIsNone(self.session.result_severity)

    def test_maximum_uses_entire_interval_including_early_frames(self):
        self.session.start()
        self.session.record_frame(2)
        for _ in range(30):
            self.session.record_frame(0)
        self.session.record_frame(None)
        self.finish()
        self.assertEqual(self.session.result_severity, 2)
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (32, 31))

    def test_frame_at_deadline_is_excluded_and_result_is_frozen(self):
        self.session.start(2)
        self.session.record_frame(1)
        self.clock.advance(2)
        self.session.record_frame(2)
        self.assertEqual(self.session.result_severity, 1)
        self.clock.advance(50)
        self.session.record_frame(0)
        self.session.record_frame(None)
        self.assertEqual(self.session.get_features()["facial_asymmetry_score"], 1)
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (1, 1))

    def test_reading_features_finishes_overdue_capture(self):
        self.session.start()
        self.session.record_frame(1)
        self.clock.advance(20)
        self.assertEqual(self.session.get_features()["facial_asymmetry_score"], 1)
        self.assertEqual(self.session.state, FacialTestState.RESULT)

    def test_restart_clears_active_or_completed_result_and_resets_deadline(self):
        self.session.start()
        self.session.record_frame(2)
        self.clock.advance(19)
        self.session.start(5)
        self.assertEqual(self.session.remaining_seconds, 5)
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (0, 0))
        self.assertIsNone(self.session.result_severity)
        self.session.record_frame(0)
        self.finish()
        self.assertEqual(self.session.result_severity, 0)
        self.session.start()
        self.assertEqual(self.session.duration_s, 5)
        self.assertIsNone(self.session.result_severity)
        self.finish()
        self.assertIsNone(self.session.result_severity)

    def test_reset_cancels_and_prevents_old_deadline_from_finishing(self):
        self.session.start()
        self.session.record_frame(2)
        self.session.reset()
        self.clock.advance(100)
        self.assertEqual(self.session.tick(), FacialTestState.IDLE)
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (0, 0))
        self.assertIsNone(self.session.get_features()["facial_asymmetry_score"])

    def test_duration_must_be_positive_finite_and_invalid_restart_preserves_session(self):
        self.session.start()
        self.session.record_frame(1)
        for duration in (0, -1, float("nan"), float("inf"), float("-inf"), True, "bad"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    FacialTestSession(duration)
                with self.assertRaises(ValueError):
                    self.session.start(duration)
        self.assertEqual(self.session.state, FacialTestState.ACTIVE)
        self.assertEqual(self.session.valid_frames, 1)
        self.finish()
        self.assertEqual(self.session.result_severity, 1)

    def test_invalid_frame_does_not_mutate_capture(self):
        self.session.start()
        for severity in (-1, 3, "1", 1.5, True, float("nan"), float("inf")):
            with self.subTest(severity=severity):
                with self.assertRaises(ValueError):
                    self.session.record_frame(severity)
        self.assertEqual((self.session.total_frames, self.session.valid_frames), (0, 0))

    def test_result_labels_identify_operational_categories(self):
        for severity, label in ((0, "Normal"), (1, "Atenção — assimetria leve"), (2, "Alerta — assimetria alta")):
            with self.subTest(severity=severity):
                self.session.start()
                self.session.record_frame(severity)
                self.finish()
                self.assertEqual(self.session.result_label, label)

    def test_default_clock_uses_monotonic_time(self):
        with patch("core.facial_test_session.time.monotonic", return_value=10) as clock:
            session = FacialTestSession(1)
            session.start()
            clock.return_value = 11
            self.assertEqual(session.tick(), FacialTestState.RESULT)


class FacialFrameSeverityTests(unittest.TestCase):
    def setUp(self):
        self.engine = FacialAsymmetryEngine.__new__(FacialAsymmetryEngine)
        self.engine.cfg = FacialConfig(vote_window=2)
        self.engine.model = Mock()
        self.engine.reset()
        self.frame = np.zeros((180, 240, 3), dtype=np.uint8)

    def process(self, name=None):
        boxes = [] if name is None else [SimpleNamespace(
            cls=[0], conf=[0.9], xyxy=np.array([[10, 10, 30, 30]])
        )]
        self.engine.model.predict.return_value = [SimpleNamespace(boxes=boxes, names={0: name})]
        self.engine.process_frame(self.frame)

    def test_frame_severity_does_not_reuse_preview_votes(self):
        self.process("StrongPalsy_Mouth")
        self.assertEqual(self.engine.frame_severity, 2)
        self.process()
        self.assertIsNone(self.engine.frame_severity)
        self.assertEqual(self.engine.severity, 2)

    def test_missing_model_clears_raw_frame_and_detections(self):
        self.process("StrongPalsy_Eyes")
        self.engine.model = None
        self.engine.process_frame(self.frame)
        self.assertIsNone(self.engine.frame_severity)
        self.assertEqual(self.engine.detections, [])
        self.assertIsNone(self.engine.get_features()["facial_asymmetry_score"])
        self.assertEqual(len(self.engine.votes), 0)
        self.assertEqual(self.engine.severity_label, "Sem observação válida")

    def test_unknown_class_and_reset_clear_raw_frame(self):
        self.process("StrongPalsy_Eyes")
        self.process("UnknownClass")
        self.assertIsNone(self.engine.frame_severity)
        self.process("Normal_Mouth")
        self.assertEqual(self.engine.frame_severity, 0)
        self.engine.reset()
        self.assertIsNone(self.engine.frame_severity)


if __name__ == "__main__":
    unittest.main()

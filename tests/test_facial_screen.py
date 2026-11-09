"""Integração da janela temporal com os controles e a câmera da tela facial."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.facial_test_session import FACIAL_RESULT_LABELS, FacialTestSession, FacialTestState
from screens.facial_screen import FacialAsymmetryScreen


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeEngine:
    def __init__(self):
        self.cfg = SimpleNamespace(camera_index=0)
        self.model = object()
        self.next_severity = None
        self.reset()

    def reset(self):
        self.frame_severity = None
        self.severity_label = "Sem observação válida"

    def process_frame(self, frame):
        self.frame_severity = self.next_severity
        self.severity_label = FACIAL_RESULT_LABELS.get(self.frame_severity, "Sem observação válida")
        return frame


class FacialScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = FakeEngine()
        self.on_next = Mock()
        self.on_back = Mock()
        with patch("screens.facial_screen.FacialAsymmetryEngine", return_value=self.engine):
            self.screen = FacialAsymmetryScreen(self.on_next, self.on_back)
        self.clock = FakeClock()
        self.screen.session = FacialTestSession(clock=self.clock)
        self.camera = Mock()
        self.camera.isOpened.return_value = True
        self.camera.read.return_value = (True, np.zeros((180, 240, 3), dtype=np.uint8))
        self.open_camera()

    def tearDown(self):
        self.screen.close()
        self.screen.deleteLater()
        self.app.processEvents()

    def open_camera(self):
        with patch("screens.facial_screen.cv2.VideoCapture", return_value=self.camera):
            self.screen.start_camera()

    def frame(self, severity):
        self.engine.next_severity = severity
        self.screen._update_frame()

    def finish(self):
        self.clock.now += self.screen.session.duration_s
        self.screen._update_session()

    def test_preview_does_not_start_test_or_enter_model_features(self):
        self.frame(2)
        self.assertEqual(self.screen.session.state, FacialTestState.IDLE)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.assertTrue(self.screen.start_btn.isEnabled())
        self.assertFalse(self.screen.restart_btn.isEnabled())
        self.assertIn("sem teste", self.screen.next_btn.text())
        self.assertFalse(self.screen.session_timer.isActive())

    def test_start_uses_selected_duration_clears_preview_and_blocks_early_advance(self):
        self.frame(2)
        self.screen.duration_spin.setValue(5)
        self.screen.start_btn.click()
        self.assertEqual(self.screen.session.state, FacialTestState.ACTIVE)
        self.assertEqual(self.screen.session.remaining_seconds, 5)
        self.assertIsNone(self.engine.frame_severity)
        self.assertTrue(self.screen.session_timer.isActive())
        self.assertFalse(self.screen.start_btn.isEnabled())
        self.assertFalse(self.screen.duration_spin.isEnabled())
        self.assertFalse(self.screen.next_btn.isEnabled())
        self.assertTrue(self.screen.restart_btn.isEnabled())
        self.frame(0)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.screen._go_next()
        self.on_next.assert_not_called()
        self.assertTrue(self.screen.timer.isActive())
        self.finish()
        self.assertEqual(self.screen.get_features()["facial_asymmetry_score"], 0)
        self.assertEqual(self.screen.progress_bar.value(), 5)

    def test_countdown_finishes_without_camera_frames_and_missing_is_not_normal(self):
        self.screen.start_btn.click()
        self.camera.read.return_value = (False, None)
        self.clock.now += 19.2
        self.screen._update_frame()
        self.assertIn("1 s", self.screen.countdown_label.text())
        self.assertIn("Sem novos frames", self.screen.preview_label.text())
        self.clock.now += 0.8
        self.screen._update_session()
        self.assertEqual(self.screen.session.state, FacialTestState.RESULT)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.assertIn("Sem observação válida", self.screen.result_label.text())
        self.assertIn("sem resultado", self.screen.next_btn.text())
        self.assertTrue(self.screen.next_btn.isEnabled())
        self.assertFalse(self.screen.session_timer.isActive())

    def test_completed_result_uses_full_window_and_remains_frozen_with_live_preview(self):
        self.screen.start_btn.click()
        self.frame(2)
        for _ in range(20):
            self.frame(0)
        self.finish()
        self.assertEqual(self.screen.get_features()["facial_asymmetry_score"], 2)
        self.assertIn("Alerta — assimetria alta", self.screen.result_label.text())
        self.frame(0)
        self.assertIn("Normal", self.screen.preview_label.text())
        self.assertIn("Alerta — assimetria alta", self.screen.result_label.text())
        self.assertEqual(self.screen.session.total_frames, 21)
        self.screen.next_btn.click()
        self.on_next.assert_called_once_with()
        self.assertEqual(self.screen.get_features()["facial_asymmetry_score"], 2)
        self.assertFalse(self.screen.timer.isActive())
        self.assertFalse(self.screen.session_timer.isActive())
        self.assertIsNone(self.screen.cap)

    def test_slow_inference_at_deadline_cannot_change_final_result(self):
        self.screen.start_btn.click()
        self.frame(1)
        self.clock.now += 19
        original_process = self.engine.process_frame

        def slow_process(frame):
            self.clock.now += 2
            return original_process(frame)

        self.engine.process_frame = slow_process
        self.frame(2)
        self.assertEqual(self.screen.session.state, FacialTestState.RESULT)
        self.assertEqual(self.screen.get_features()["facial_asymmetry_score"], 1)
        self.assertEqual(self.screen.session.total_frames, 1)
        self.assertIn("Atenção — assimetria leve", self.screen.result_label.text())

    def test_restart_clears_and_immediately_restarts_active_and_completed_capture(self):
        self.screen.start_btn.click()
        self.frame(2)
        self.clock.now += 10
        self.screen.restart_btn.click()
        self.assertEqual(self.screen.session.state, FacialTestState.ACTIVE)
        self.assertEqual(self.screen.session.remaining_seconds, 20)
        self.assertEqual(self.screen.session.total_frames, 0)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.frame(1)
        self.finish()
        self.screen.duration_spin.setValue(7)
        self.assertEqual(self.screen.session.duration_s, 20)
        self.screen.restart_btn.click()
        self.assertEqual(self.screen.session.remaining_seconds, 7)
        self.assertEqual(self.screen.session.total_frames, 0)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.frame(0)
        self.finish()
        self.assertEqual(self.screen.get_features()["facial_asymmetry_score"], 0)

    def test_back_cancels_partial_capture_and_releases_camera_and_timers(self):
        self.screen.start_btn.click()
        self.frame(2)
        self.screen.back_btn.click()
        self.on_back.assert_called_once_with()
        self.assertEqual(self.screen.session.state, FacialTestState.IDLE)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.assertFalse(self.screen.timer.isActive())
        self.assertFalse(self.screen.session_timer.isActive())
        self.camera.release.assert_called_once_with()
        self.clock.now += 100
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])

    def test_reentering_screen_drops_prior_result_and_requires_manual_start(self):
        self.screen.start_btn.click()
        self.frame(2)
        self.finish()
        self.open_camera()
        self.assertEqual(self.screen.session.state, FacialTestState.IDLE)
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.assertEqual(self.screen.session.total_frames, 0)
        self.assertTrue(self.screen.start_btn.isEnabled())
        self.assertFalse(self.screen.session_timer.isActive())

    def test_missing_camera_or_model_disables_start_but_allows_explicit_skip(self):
        self.camera.isOpened.return_value = False
        self.open_camera()
        self.assertFalse(self.screen.start_btn.isEnabled())
        self.assertFalse(self.screen.timer.isActive())
        self.assertIn("abrir a câmera", self.screen.preview_label.text())
        self.assertTrue(self.screen.next_btn.isEnabled())
        self.screen._start_test()
        self.assertEqual(self.screen.session.state, FacialTestState.IDLE)
        self.camera.isOpened.return_value = True
        self.engine.model = None
        self.open_camera()
        self.assertIn("Modelo facial indisponível", self.screen.preview_label.text())
        self.assertFalse(self.screen.start_btn.isEnabled())
        self.screen.next_btn.click()
        self.on_next.assert_called_once_with()
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])

    def test_closing_screen_cancels_capture_and_releases_resources(self):
        self.screen.start_btn.click()
        self.frame(1)
        self.screen.close()
        self.assertFalse(self.screen.timer.isActive())
        self.assertFalse(self.screen.session_timer.isActive())
        self.camera.release.assert_called_once_with()
        self.assertIsNone(self.screen.get_features()["facial_asymmetry_score"])
        self.assertEqual(self.screen.session.state, FacialTestState.IDLE)


if __name__ == "__main__":
    unittest.main()

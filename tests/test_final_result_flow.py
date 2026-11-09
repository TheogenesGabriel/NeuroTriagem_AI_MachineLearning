"""Navegação real entre aquisição, resultado persistente e nova avaliação."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.facial_test_session import FacialTestSession
from main import MainWindow


class FinalResultFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.arm_engine = Mock()
        self.arm_engine.cfg = SimpleNamespace(camera_index=0)
        self.arm_engine.get_features.return_value = {"arm_ratio": 0.2, "arm_weak_side_code": 0}
        self.face_engine = Mock()
        self.face_engine.cfg = SimpleNamespace(camera_index=0)
        self.face_engine.model = object()
        self.model = Mock()
        self.model.model = object()
        self.model.metadata = {"data_kind": "synthetic", "label_provenance": "synthetic_rules"}
        self.model.load_error = None
        self.model.predict.return_value = {"risco": "DEMO_SINAL_MOTOR", "aviso": None}
        self.camera_patch = patch(
            "screens.facial_screen.cv2.VideoCapture",
            side_effect=AssertionError("O teste de navegação não deve abrir hardware."),
        )
        self.camera_patch.start()
        self.addCleanup(self.camera_patch.stop)
        with patch("screens.arm_test_screen.ArmTestEngine", return_value=self.arm_engine), \
                patch("screens.facial_screen.FacialAsymmetryEngine", return_value=self.face_engine), \
                patch("screens.joystick_test_screen.load_app_model", return_value=self.model):
            self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def complete_assessment(self):
        vitals = self.window.pretriagem_screen
        vitals._spo2_final = 98.0
        vitals._heart_rate_final = 80.0
        clock = SimpleNamespace(now=0)
        facial = self.window.facial_screen
        facial.session = FacialTestSession(1, clock=lambda: clock.now)
        facial.session.start()
        facial.session.record_frame(1)
        clock.now = 1
        facial.session.tick()
        joystick = self.window.joystick_test_screen
        joystick._ultimo_resultado = {
            "final": {"concluidas": 3, "total": 3},
            "resultados": {
                shape: {"estado": "CONCLUIDO", "valido": True, "tempo_ms": 5000,
                        "desvio_medio_u": 0.02, "sobreposicao_pct": 96,
                        "caminho_u": 5.8, "vel_media_u_s": 1.2, "acel_media_u_s2": 0.25,
                        "rmse_u": 0.03, "npv": 50, "amostras": 200, "maior_intervalo_ms": 22}
                for shape in ("QUADRADO", "TRIANGULO", "CIRCULO")
            },
        }
        self.window.stack.setCurrentWidget(joystick)
        with patch("screens.joystick_test_screen.QMessageBox.information") as popup:
            joystick._finish()
        popup.assert_not_called()
        self.app.processEvents()
        return self.window.final_result_screen

    def test_finish_opens_persistent_final_screen_and_infers_once(self):
        reader = Mock()
        face_camera, arm_camera = Mock(), Mock()
        self.window.joystick_test_screen.reader = reader
        self.window.facial_screen.cap = face_camera
        self.window.arm_test_screen.cap = arm_camera
        result = self.complete_assessment()
        self.assertIs(self.window.stack.currentWidget(), result)
        self.assertEqual(result.heading_label.text(), "Sinal motor")
        self.assertEqual(result.measurement_cards[0].value_label.text(), "Atenção")
        self.assertEqual(result.measurement_cards[2].value_label.text(), "80 bpm")
        self.assertEqual(result.joystick_table.rowCount(), 3)
        self.model.predict.assert_called_once_with({
            "arm_ratio": 0.2, "arm_weak_side_code": 0, "facial_asymmetry_score": 1,
            "heart_rate": 80.0, "spo2": 98.0,
        })
        reader.stop.assert_called_once()
        face_camera.release.assert_called_once()
        arm_camera.release.assert_called_once()
        self.window.joystick_test_screen._finish()
        self.app.processEvents()
        self.model.predict.assert_called_once()
        self.assertIs(self.window.stack.currentWidget(), result)
        # Mudanças posteriores nos motores não reescrevem a avaliação exibida.
        self.window.pretriagem_screen._heart_rate_final = 140
        self.window.facial_screen.session.reset()
        self.window.joystick_test_screen._ultimo_resultado["final"]["concluidas"] = 0
        self.app.processEvents()
        self.assertEqual(result.measurement_cards[2].value_label.text(), "80 bpm")
        self.assertIn("3 de 3", result.joystick_summary_label.text())

    def test_new_assessment_clears_result_and_vitals_before_pretriage(self):
        result = self.complete_assessment()
        result.details_toggle.setChecked(True)
        result.new_assessment_btn.click()
        self.app.processEvents()
        self.assertIs(self.window.stack.currentWidget(), self.window.pretriagem_screen)
        self.assertIsNone(result.presentation)
        self.assertEqual(result.heading_label.text(), "Aguardando avaliação")
        self.assertEqual(result.joystick_table.rowCount(), 0)
        self.assertFalse(result.details_toggle.isChecked())
        self.assertEqual(self.window.pretriagem_screen.get_vitals(), {"heart_rate": 0.0, "spo2": 0.0})
        self.assertFalse(self.window.pretriagem_screen.next_btn.isEnabled())
        self.model.predict.assert_called_once()

    def test_home_button_returns_home_without_reclassifying(self):
        result = self.complete_assessment()
        result.home_btn.click()
        self.app.processEvents()
        self.assertIs(self.window.stack.currentWidget(), self.window.home_screen)
        self.model.predict.assert_called_once()
        self.assertFalse(self.window.facial_screen.timer.isActive())
        self.assertFalse(self.window.facial_screen.session_timer.isActive())
        self.assertFalse(self.window.arm_test_screen.timer.isActive())


if __name__ == "__main__":
    unittest.main()

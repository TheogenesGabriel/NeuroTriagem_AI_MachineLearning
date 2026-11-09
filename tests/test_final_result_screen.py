"""Snapshot persistente, atualização e navegação da tela final."""

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from screens.final_result_screen import FinalResultScreen


class FinalResultScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.new_assessment = Mock()
        self.home = Mock()
        self.screen = FinalResultScreen(self.new_assessment, self.home)
        self.screen.resize(1000, 750)
        self.screen.show()
        self.app.processEvents()

    def tearDown(self):
        self.screen.close()
        self.screen.deleteLater()
        self.app.processEvents()

    def sample(self):
        return {
            "heading": "Sinais motores e vitais",
            "subtitle": "Regras acionadas no protótipo.",
            "tone": "alert",
            "timestamp": "02/11/2026 · 10:30",
            "disclaimer": "Resultado experimental.",
            "cards": [
                {"label": "Face", "value": "Atenção — assimetria leve", "detail": "Grau 1", "tone": "attention"},
                {"label": "Braço", "value": "Lado esquerdo", "detail": "Razão 0,8", "tone": "alert"},
                {"label": "Batimentos", "value": "120 BPM", "detail": "Medição recebida", "tone": "attention"},
                {"label": "SpO₂", "value": "98%", "detail": "Medição recebida", "tone": "neutral"},
            ],
            "notices": ["O modelo divergiu da regra neste caso."],
            "model_status": "Modelo de demonstração",
            "reference": "Regra de sinal motor acionada",
            "details": "A previsão original foi preservada.",
            "joystick_summary": "3 de 3 trajetórias concluídas",
            "joystick_rows": [["Quadrado", "Concluído", "5,00", "0,02", "96%", "Válidos"]],
        }

    def test_snapshot_survives_input_mutation_without_recalculation(self):
        data = self.sample()
        self.screen.set_result(data)
        data["heading"] = "Mudou depois"
        data["cards"][0]["value"] = "Mudou depois"
        data["joystick_rows"][0][1] = "Mudou depois"
        self.assertEqual(self.screen.heading_label.text(), "Sinais motores e vitais")
        self.assertEqual(self.screen.measurement_cards[0].value_label.text(), "Atenção — assimetria leve")
        self.assertEqual(self.screen.joystick_table.item(0, 1).text(), "Concluído")
        self.assertEqual(self.screen.presentation["joystick_rows"][0][1], "Concluído")

    def test_new_result_replaces_notices_table_and_expanded_details(self):
        self.screen.set_result(self.sample())
        self.screen.details_toggle.click()
        self.assertTrue(self.screen.details_panel.isVisible())
        self.screen.set_result({"heading": "Resultado indisponível", "tone": "unavailable"})
        self.assertEqual(self.screen.joystick_table.rowCount(), 0)
        self.assertFalse(self.screen.notices_label.isVisible())
        self.assertEqual(self.screen.notices_label.text(), "")
        self.assertEqual(self.screen.reference_label.text(), "")
        self.assertFalse(self.screen.details_panel.isVisible())
        self.assertEqual(self.screen.measurement_cards[0].value_label.text(), "—")

    def test_clear_removes_previous_assessment(self):
        self.screen.set_result(self.sample())
        self.screen.clear_result()
        self.assertIsNone(self.screen.presentation)
        self.assertEqual(self.screen.heading_label.text(), "Aguardando avaliação")
        self.assertEqual(self.screen.timestamp_label.text(), "")
        self.assertEqual(self.screen.joystick_table.rowCount(), 0)
        self.assertEqual(self.screen.details_label.text(), "")

    def test_navigation_buttons_dispatch_without_mutating_result(self):
        self.screen.set_result(self.sample())
        self.screen.new_assessment_btn.click()
        self.screen.home_btn.click()
        self.new_assessment.assert_called_once()
        self.home.assert_called_once()
        self.assertEqual(self.screen.heading_label.text(), "Sinais motores e vitais")

    def test_dynamic_text_is_plain_and_warnings_are_not_hidden_in_details(self):
        data = self.sample()
        data["heading"] = "<b>Classe externa</b>"
        data["notices"] = ["<a href='test'>Medição ausente</a>"]
        self.screen.set_result(data)
        self.assertEqual(self.screen.heading_label.textFormat(), Qt.PlainText)
        self.assertEqual(self.screen.notices_label.textFormat(), Qt.PlainText)
        self.assertEqual(self.screen.heading_label.text(), data["heading"])
        self.assertTrue(self.screen.notices_label.isVisible())
        self.assertFalse(self.screen.details_panel.isVisible())

    def test_small_view_keeps_footer_accessible_and_body_scrollable(self):
        data = self.sample()
        data["details"] = "Explicação adicional.\n" * 25
        self.screen.set_result(data)
        self.screen.resize(720, 480)
        self.screen.details_toggle.click()
        self.app.processEvents()
        self.assertGreater(self.screen.scroll_area.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(self.screen.new_assessment_btn.geometry().bottom(), self.screen.height())
        self.assertLessEqual(self.screen.home_btn.geometry().bottom(), self.screen.height())


if __name__ == "__main__":
    unittest.main()

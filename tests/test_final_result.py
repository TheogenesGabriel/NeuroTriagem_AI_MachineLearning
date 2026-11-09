"""Preservação da previsão e das medições no resumo final."""

from copy import deepcopy
import unittest

from core.final_result import build_final_result


class FinalResultPresentationTests(unittest.TestCase):
    def payload(self):
        return {
            "veredito": {"risco": "DEMO_SEM_REGRA_ACIONADA", "confianca": .95},
            "features": dict(arm_ratio=.2, arm_weak_side_code=0, facial_asymmetry_score=0, heart_rate=80, spo2=98),
            "joystick": {"final": {"concluidas": 1, "total": 3}, "resultados": {}},
            "generated_at": "2026-11-02T14:22:00-03:00",
        }

    def test_divergence_keeps_actual_prediction_and_shows_reference_as_notice(self):
        payload = self.payload()
        payload["features"].update(heart_rate=59.99, spo2=94.99)
        result = build_final_result(payload)
        self.assertEqual(result["heading"], "Nenhuma regra acionada")
        self.assertIn("faixa vital", result["reference"])
        self.assertIn("divergiu", " ".join(result["notices"]))
        self.assertIn("não exclui AVC", result["subtitle"])
        self.assertNotIn("95%", str(result))

    def test_invalid_or_missing_values_never_become_normal_and_other_measurements_survive(self):
        payload = self.payload()
        payload["veredito"]["risco"] = "indefinido"
        payload["features"].update(facial_asymmetry_score=None, heart_rate=0, spo2=101)
        result = build_final_result(payload)
        self.assertEqual(result["heading"], "Classificação indisponível")
        self.assertEqual(result["cards"][0]["value"], "Sem resultado")
        self.assertIn("0,2", result["cards"][1]["detail"])
        self.assertEqual(result["cards"][2]["value"], "Não medido")
        self.assertEqual(result["cards"][3]["value"], "Valor inválido")
        self.assertIn("Medições inválidas: SpO₂", " ".join(result["notices"]))
        self.assertIn("assimetria facial", " ".join(result["notices"]))

    def test_valid_motor_zeros_are_preserved_and_missing_vitals_do_not_hide_divergence(self):
        payload = self.payload()
        payload["features"].update(arm_ratio=0, heart_rate=None)
        result = build_final_result(payload)
        self.assertEqual(result["cards"][0]["value"], "Normal")
        self.assertEqual(result["cards"][1]["value"], "Sem lado indicado")
        self.assertEqual(result["cards"][1]["detail"], "Razão de assimetria: 0")
        self.assertIn("Dados incompletos", result["reference"])
        self.assertIn("divergiu", " ".join(result["notices"]))

    def test_joystick_stays_descriptive_and_invalid_metrics_are_not_displayed(self):
        payload = self.payload()
        before = build_final_result(payload)
        payload["joystick"]["resultados"] = {
            "QUADRADO": dict(estado="CONCLUIDO", valido=1, tempo_ms=9540, desvio_medio_u=.048, sobreposicao_pct=92.97),
            "TRIANGULO": dict(estado="TEMPO_LIMITE", valido=1, tempo_ms=90000, desvio_medio_u=.3, sobreposicao_pct=20),
            "CIRCULO": dict(estado="NAO_INICIADO", valido=0, tempo_ms=0, desvio_medio_u=0, sobreposicao_pct=0),
        }
        snapshot = deepcopy(payload)
        result = build_final_result(payload)
        self.assertEqual(result["heading"], before["heading"])
        self.assertEqual(result["cards"], before["cards"])
        self.assertEqual(result["reference"], before["reference"])
        self.assertEqual(result["joystick_rows"][0][2:5], ["9,54", "0,048", "92,97%"])
        self.assertIn("Parcial", result["joystick_rows"][1][1])
        self.assertEqual(result["joystick_rows"][2][2:5], ["—", "—", "—"])
        self.assertEqual(payload, snapshot)


if __name__ == "__main__":
    unittest.main()

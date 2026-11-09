"""Integração do artefato demonstrativo, prioridade e texto para a interface."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from core.random_forest_model import FEATURE_NAMES, RiscoRandomForest, save_artifact
from core.random_forest_runtime import (
    DEMO_MODEL_PATH, build_result_text, get_model_status, load_app_model,
)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = joblib.load(DEMO_MODEL_PATH)
        cls.sample = dict(zip(FEATURE_NAMES, [0.2, 0, 0, 80, 98]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.candidate = Path(self.temp.name) / "candidate.joblib"

    def load_demo(self):
        with patch("core.random_forest_runtime.DEFAULT_MODEL_PATH", self.candidate):
            return load_app_model()

    def test_project_loads_exact_synthetic_artifact_in_demo_mode_only(self):
        model = self.load_demo()
        self.assertIsNotNone(model.model, model.load_error)
        self.assertEqual(model.model_path, DEMO_MODEL_PATH)
        self.assertTrue(model.allow_demo)
        self.assertEqual(model.metadata["label_provenance"], "synthetic_rules")
        self.assertIn("sintéticos", get_model_status(model))
        self.assertIsNone(RiscoRandomForest(DEMO_MODEL_PATH).model)
        result = model.predict(self.sample)
        expected = self.artifact["pipeline"].predict_proba([list(self.sample.values())])[0]
        np.testing.assert_allclose(list(result["probabilidades"].values()), expected)

    def test_explicit_real_candidate_is_prioritized(self):
        # Esta fixture testa roteamento de metadados, não fornece evidência clínica.
        save_artifact(self.artifact["pipeline"], self.candidate, metadata={
            "data_kind": "real", "target_description": "Fixture exclusivamente de roteamento.",
        })
        with patch("core.random_forest_runtime.DEFAULT_MODEL_PATH", self.candidate):
            model = load_app_model()
        self.assertEqual(model.model_path, self.candidate)
        self.assertFalse(model.allow_demo)
        self.assertIn("dados reais", get_model_status(model))

    def test_invalid_real_candidate_does_not_silently_load_demo(self):
        self.candidate.write_bytes(b"corrupt")
        with patch("core.random_forest_runtime.DEFAULT_MODEL_PATH", self.candidate):
            model = load_app_model()
        self.assertIsNone(model.model)
        self.assertEqual(model.model_path, self.candidate)
        self.assertIn("indisponível", get_model_status(model))

    def test_missing_demo_is_reported_without_failure(self):
        with patch("core.random_forest_runtime.DEFAULT_MODEL_PATH", self.candidate):
            with patch("core.random_forest_runtime.DEMO_MODEL_PATH", Path(self.temp.name) / "absent.joblib"):
                model = load_app_model()
        self.assertEqual(model.predict(self.sample)["risco"], "indefinido")
        self.assertIn("indisponível", get_model_status(model))

    def test_demo_with_different_rules_is_rejected(self):
        path = Path(self.temp.name) / "different.joblib"
        save_artifact(self.artifact["pipeline"], path, metadata={
            **self.artifact["metadata"], "rule_version": "other",
        })
        with patch("core.random_forest_runtime.DEFAULT_MODEL_PATH", self.candidate):
            with patch("core.random_forest_runtime.DEMO_MODEL_PATH", path):
                model = load_app_model()
        self.assertIsNone(model.model)
        self.assertIn("incompatível", model.load_error)

    def test_disagreement_is_explicit_without_replacing_prediction(self):
        sample = dict(zip(FEATURE_NAMES, [0.2, 0, 0, 59.99, 94.99]))
        result = self.load_demo().predict(sample)
        text = build_result_text(result, sample)
        self.assertEqual(result["risco"], "DEMO_SEM_REGRA_ACIONADA")
        self.assertIn("Previsão do Random Forest: Nenhuma regra acionada", text)
        self.assertIn("Regra de referência: Regra de faixa vital acionada", text)
        self.assertIn("divergiu", text)
        self.assertIn("não exclui AVC", text)
        self.assertNotIn("DEMO_", text)
        self.assertNotIn("%", text)

    def test_missing_measurements_remain_visible_even_if_prediction_disagrees(self):
        sample = dict(self.sample, heart_rate=0)
        prediction = {"risco": "DEMO_SEM_REGRA_ACIONADA", "aviso": None}
        text = build_result_text(prediction, sample)
        self.assertIn("Medições ausentes: batimentos cardíacos (BPM)", text)
        self.assertIn("Dados incompletos", text)
        self.assertIn("divergiu", text)

    def test_no_measurements_and_bad_values_are_not_shown_as_normal(self):
        model = self.load_demo()
        text = build_result_text(model.predict({}), {})
        self.assertIn("Resultado indisponível", text)
        self.assertIn("Sem medições", text)
        bad = dict(self.sample, spo2=101)
        text = build_result_text(model.predict(bad), bad)
        self.assertIn("Resultado indisponível", text)
        self.assertIn("medições inválidas", text)


if __name__ == "__main__":
    unittest.main()

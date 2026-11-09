"""Contrato de inferência e persistência, com fixtures inteiramente artificiais."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from core.random_forest_model import (
    DEFAULT_MODEL_PATH, EXPERIMENTAL_WARNING, FEATURE_NAMES, PROJECT_ROOT,
    RiscoRandomForest, build_pipeline, normalize_features, save_artifact,
)


class RandomForestModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Estas classes e medições só exercitam o contrato de software.
        cls.X = np.array([
            [0.0, 0, 0, 70, 98], [0.1, 0, 0, 75, 97],
            [0.2, 0, 1, 80, 96], [0.3, 1, 1, 85, 95],
            [0.7, 1, 2, 90, 94], [0.9, 2, 2, 100, 93],
            [0.0, 0, 0, 72, 99], [0.15, 0, 1, 78, 98],
            [0.6, 2, 1, 95, 95], [0.8, 1, 2, 105, 94],
            [np.nan, 0, 0, 74, 97], [0.5, 2, np.nan, 98, 95],
        ], dtype=float)
        cls.y = np.array(["classe_a"] * 4 + ["classe_b"] * 2
                         + ["classe_a"] * 2 + ["classe_b"] * 2
                         + ["classe_a", "classe_b"])
        cls.pipeline = build_pipeline(n_estimators=8, random_state=42)
        cls.pipeline.fit(cls.X, cls.y)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.joblib"
        self.metadata = {
            "data_kind": "synthetic",
            "target_description": "Classes artificiais exclusivas de teste de software.",
        }
        self.features = dict(zip(FEATURE_NAMES, [0.0, 0, 0, 72.0, 98.0]))

    def save(self):
        return save_artifact(self.pipeline, self.path, metadata=self.metadata)

    def model(self):
        self.save()
        return RiscoRandomForest(self.path, allow_demo=True)

    def test_roundtrip_preserves_pipeline_predictions_and_probabilities(self):
        model = self.model()
        self.assertIsNone(model.load_error)
        self.assertFalse(model.metadata["clinical_validation"])
        result = model.predict(self.features)
        expected = self.pipeline.predict_proba([list(self.features.values())])[0]
        expected_class = str(self.pipeline.classes_[int(np.argmax(expected))])
        self.assertEqual(result["risco"], expected_class)
        np.testing.assert_allclose(list(result["probabilidades"].values()), expected)
        self.assertAlmostEqual(sum(result["probabilidades"].values()), 1.0)
        self.assertAlmostEqual(result["confianca"], max(expected))
        self.assertIn(EXPERIMENTAL_WARNING, result["aviso"])
        self.assertIn("DEMONSTRAÇÃO SINTÉTICA", result["aviso"])

    def test_default_model_path_is_absolute_and_stable_after_cwd_change(self):
        self.assertEqual(DEFAULT_MODEL_PATH, PROJECT_ROOT / "models" / "random_forest_risco.joblib")
        self.assertTrue(DEFAULT_MODEL_PATH.is_absolute())
        original_cwd = Path.cwd()
        try:
            os.chdir(self.temp.name)
            model = RiscoRandomForest()
            self.assertEqual(model.model_path, DEFAULT_MODEL_PATH)
        finally:
            os.chdir(original_cwd)

    def test_missing_file_returns_indefinite_without_crashing(self):
        model = RiscoRandomForest(self.path)
        result = model.predict(self.features)
        self.assertIsNone(model.model)
        self.assertEqual(result["risco"], "indefinido")
        self.assertIsNone(result["confianca"])
        self.assertEqual(result["probabilidades"], {})
        self.assertIn("não treinado", result["aviso"])

    def test_corrupt_and_legacy_artifacts_are_rejected(self):
        self.path.write_bytes(b"not a joblib artifact")
        corrupt = RiscoRandomForest(self.path, allow_demo=True)
        self.assertIsNone(corrupt.model)
        self.assertIn("indisponível", corrupt.load_error)
        joblib.dump(self.pipeline.named_steps["forest"], self.path)
        legacy = RiscoRandomForest(self.path, allow_demo=True)
        self.assertIsNone(legacy.model)
        self.assertIn("antigo ou incompatível", legacy.load_error)

    def test_schema_feature_order_and_sklearn_version_must_match(self):
        mutations = [
            ("schema_version", -1, "antigo ou incompatível"),
            ("feature_names", list(reversed(FEATURE_NAMES)), "features incompatível"),
            ("sklearn_version", "0.0.0", "mesma versão"),
        ]
        for key, value, expected in mutations:
            with self.subTest(field=key):
                self.save()
                artifact = joblib.load(self.path)
                artifact[key] = value
                joblib.dump(artifact, self.path)
                model = RiscoRandomForest(self.path, allow_demo=True)
                self.assertIsNone(model.model)
                self.assertIn(expected, model.load_error)

    def test_synthetic_artifact_needs_explicit_demo_opt_in(self):
        self.save()
        blocked = RiscoRandomForest(self.path)
        self.assertIsNone(blocked.model)
        self.assertIn("sintético", blocked.predict(self.features)["aviso"])
        enabled = RiscoRandomForest(self.path, allow_demo=True)
        self.assertIsNotNone(enabled.model)
        self.assertIn("DEMONSTRAÇÃO SINTÉTICA", enabled.predict(self.features)["aviso"])

    def test_synthetic_export_cannot_overwrite_app_activation_path(self):
        # Use um destino temporário para verificar o bloqueio sem tocar o modelo do usuário.
        self.path.write_bytes(b"existing artifact")
        with patch("core.random_forest_model.DEFAULT_MODEL_PATH", self.path.resolve()):
            with self.assertRaisesRegex(ValueError, "fora do caminho"):
                self.save()
        self.assertEqual(self.path.read_bytes(), b"existing artifact")

    def test_export_requires_provenance_and_label_description(self):
        for metadata in ({}, {"data_kind": "unknown", "target_description": "fixture"},
                         {"data_kind": "synthetic", "target_description": "  "}):
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValueError):
                    save_artifact(self.pipeline, self.path, metadata=metadata)
        self.assertFalse(self.path.exists())

    def test_all_missing_returns_indefinite_but_partial_is_imputed_and_reported(self):
        model = self.model()
        result = model.predict({})
        self.assertEqual(result["risco"], "indefinido")
        self.assertIn("Sem medições", result["aviso"])
        legacy_missing = model.predict({"heart_rate": 0.0, "spo2": 0.0})
        self.assertEqual(legacy_missing["risco"], "indefinido")
        partial = dict(self.features, facial_asymmetry_score=None, spo2=0.0)
        result = model.predict(partial)
        self.assertIn(result["risco"], self.pipeline.classes_)
        self.assertIn("Valores ausentes imputados", result["aviso"])
        self.assertIn("facial_asymmetry_score", result["aviso"])
        self.assertIn("spo2", result["aviso"])

    def test_real_zero_observations_are_kept_and_missing_vitals_become_nan(self):
        values = normalize_features([[0, 0, 0, 0, 0]])
        np.testing.assert_array_equal(values[0, :3], [0, 0, 0])
        self.assertTrue(np.isnan(values[0, 3:]).all())
        result = self.model().predict(self.features)
        self.assertNotIn("Valores ausentes", result["aviso"])

    def test_bpm_is_an_input_and_ecg_is_reserved_for_a_future_schema(self):
        self.assertIn("heart_rate", FEATURE_NAMES)
        self.assertNotIn("ecg", FEATURE_NAMES)
        model = self.model()
        without_ecg = model.predict(self.features)
        with_unused_ecg = model.predict(dict(self.features, ecg="not used"))
        self.assertEqual(without_ecg, with_unused_ecg)

    def test_incompatible_imputer_is_rejected_on_load(self):
        self.save()
        artifact = joblib.load(self.path)
        artifact["pipeline"].steps[1] = ("imputer", "passthrough")
        joblib.dump(artifact, self.path)
        model = RiscoRandomForest(self.path, allow_demo=True)
        self.assertIsNone(model.model)
        self.assertIn("Imputador incompatível", model.load_error)

    def test_invalid_strings_nonfinite_and_domains_fail_without_prediction(self):
        model = self.model()
        cases = [
            ("arm_ratio", "not numeric"), ("arm_ratio", float("inf")),
            ("heart_rate", float("-inf")), ("arm_ratio", -0.1),
            ("arm_weak_side_code", 3), ("arm_weak_side_code", 0.5),
            ("facial_asymmetry_score", -1), ("facial_asymmetry_score", 2.1),
            ("heart_rate", -1), ("spo2", 101), ("spo2", -1),
            ("heart_rate", 2 ** 2048),
        ]
        for name, value in cases:
            with self.subTest(feature=name, value=value):
                result = model.predict(dict(self.features, **{name: value}))
                self.assertEqual(result["risco"], "indefinido")
                self.assertIsNone(result["confianca"])
                self.assertEqual(result["probabilidades"], {})
                self.assertIn("Não foi possível", result["aviso"])

    def test_training_rejects_empty_rows_and_entirely_missing_columns(self):
        empty_row = np.vstack([self.X, [np.nan] * len(FEATURE_NAMES)])
        with self.assertRaisesRegex(ValueError, "sem nenhuma medição"):
            build_pipeline(n_estimators=8).fit(empty_row, np.append(self.y, "classe_a"))
        empty_column = self.X.copy()
        empty_column[:, 3] = np.nan
        with self.assertRaisesRegex(ValueError, "heart_rate"):
            build_pipeline(n_estimators=8).fit(empty_column, self.y)


if __name__ == "__main__":
    unittest.main()

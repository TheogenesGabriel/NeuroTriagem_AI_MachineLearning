"""Verifica fronteiras de avaliação e compatibilidade do artefato exportado."""

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.model_selection import RandomizedSearchCV

from core.random_forest_model import FEATURE_NAMES, RiscoRandomForest, save_artifact
from core.random_forest_training import load_dataset, make_demo_dataset, train_evaluate


FAST_PARAMETERS = {
    "forest__n_estimators": [12], "forest__max_depth": [4],
    "forest__min_samples_leaf": [2],
}


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.X, cls.y, cls.groups = make_demo_dataset(n_patients=90, random_state=7)
        with patch("core.random_forest_training.RandomizedSearchCV", wraps=RandomizedSearchCV) as search:
            cls.result = train_evaluate(
                cls.X, cls.y, cls.groups, n_iter=1,
                parameter_distributions=FAST_PARAMETERS, permutation_repeats=2,
            )
            cls.inner_folds = search.call_args.kwargs["cv"]

    def test_holdout_and_every_cv_fold_separate_patients(self):
        train = self.result["train_indices"]
        test = self.result["test_indices"]
        self.assertEqual(set(train) | set(test), set(range(len(self.y))))
        self.assertFalse(set(train) & set(test))
        self.assertFalse(set(self.groups[train]) & set(self.groups[test]))
        for fit, validation in self.inner_folds:
            self.assertFalse(set(self.groups[train][fit]) & set(self.groups[train][validation]))
            self.assertEqual(set(self.y[train][fit]), set(self.y))
            self.assertEqual(set(self.y[train][validation]), set(self.y))

    def test_imputation_is_fitted_on_training_values_only(self):
        imputer = next(step for _, step in self.result["pipeline"].steps if isinstance(step, SimpleImputer))
        expected = np.nanmedian(self.X[self.result["train_indices"]], axis=0)
        np.testing.assert_allclose(imputer.statistics_, expected)

    def test_holdout_features_do_not_change_fitted_forest(self):
        changed = self.X.copy()
        changed[self.result["test_indices"], 0] = 10000
        other = train_evaluate(
            changed, self.y, self.groups, n_iter=1,
            parameter_distributions=FAST_PARAMETERS, permutation_repeats=1,
        )
        for first, second in zip(
            self.result["pipeline"].named_steps["forest"].estimators_,
            other["pipeline"].named_steps["forest"].estimators_,
        ):
            np.testing.assert_array_equal(first.tree_.threshold, second.tree_.threshold)
            np.testing.assert_array_equal(first.tree_.value, second.tree_.value)

    def test_report_is_json_serializable_and_includes_baseline_and_per_class_metrics(self):
        report = self.result["report"]
        json.dumps(report, allow_nan=False)
        json.dumps(self.result["cv_results"], allow_nan=False)
        self.assertAlmostEqual(report["test"]["dummy"]["balanced_accuracy"], 1 / 3)
        self.assertEqual(set(report["test"]["random_forest"]["per_class"]), set(self.y))
        self.assertEqual(report["split"]["group_overlap"], 0)
        self.assertNotIn(self.groups[0], json.dumps(report))

    def test_small_class_group_count_has_actionable_error(self):
        mask = np.arange(len(self.y)) < 12
        with self.assertRaisesRegex(ValueError, "pacientes"):
            train_evaluate(self.X[mask], self.y[mask], self.groups[mask], n_iter=1)

    def test_demo_artifact_roundtrip_and_default_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.joblib"
            save_artifact(self.result["pipeline"], path, metadata={
                "data_kind": "synthetic", "target_description": "Classes artificiais de teste de software.",
                "evaluation": self.result["report"],
            })
            features = dict(zip(FEATURE_NAMES, self.X[0]))
            expected = str(self.result["pipeline"].predict(self.X[:1])[0])
            demo = RiscoRandomForest(path, allow_demo=True).predict(features)
            self.assertEqual(demo["risco"], expected)
            self.assertEqual(RiscoRandomForest(path).predict(features)["risco"], "indefinido")


class DatasetTests(unittest.TestCase):
    def write_csv(self, path, rows, fields=None):
        fields = fields or ["patient_id", *FEATURE_NAMES, "risco"]
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def rows(self):
        return [
            dict(zip(["patient_id", *FEATURE_NAMES, "risco"], ["P1", 0.2, 0, 1, "", 98, "A"])),
            dict(zip(["patient_id", *FEATURE_NAMES, "risco"], ["P2", 0.4, 2, 2, 81, 0, "B"])),
            dict(zip(["patient_id", *FEATURE_NAMES, "risco"], ["P3", 0.1, 0, 0, 72, 96, "A"])),
        ]

    def test_loader_orders_features_and_preserves_missing_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            self.write_csv(path, self.rows(), ["risco", *reversed(FEATURE_NAMES), "patient_id"])
            X, y, groups = load_dataset(path)
            self.assertEqual(X[0, 0], 0.2)
            self.assertTrue(np.isnan(X[0, 3]))
            self.assertTrue(np.isnan(X[1, 4]))
            self.assertEqual(y.tolist(), ["A", "B", "A"])
            self.assertEqual(groups.tolist(), ["P1", "P2", "P3"])

    def test_rejects_missing_ids_labels_duplicates_and_invalid_values(self):
        mutations = [
            ("patient_id", ""), ("risco", ""), ("arm_ratio", "not-a-number"),
            ("spo2", 101), ("arm_weak_side_code", 4), ("heart_rate", "inf"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            for column, value in mutations:
                with self.subTest(column=column, value=value):
                    rows = self.rows()
                    rows[0][column] = value
                    self.write_csv(path, rows)
                    with self.assertRaises(ValueError):
                        load_dataset(path)
            rows = self.rows()
            self.write_csv(path, rows + [rows[0]])
            with self.assertRaisesRegex(ValueError, "duplicadas"):
                load_dataset(path)

    def test_template_is_intentionally_empty_and_feature_cannot_be_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            self.write_csv(path, [])
            with self.assertRaisesRegex(ValueError, "vazio"):
                load_dataset(path)
            with self.assertRaisesRegex(ValueError, "distintas"):
                load_dataset(path, target_column="arm_ratio")


if __name__ == "__main__":
    unittest.main()

"""Regras de demonstração e casos de fronteira; não são testes clínicos."""

from collections import Counter
import json
import unittest

import numpy as np

from core.random_forest_model import FEATURE_NAMES
from core.random_forest_rules import (
    RULE_CONFIG, RULE_LABELS, RULE_VERSION, SOURCE_URLS,
    label_rule_scenarios, make_rule_demo_dataset,
)


class RuleScenarioTests(unittest.TestCase):
    def test_exact_thresholds_do_not_activate_rules(self):
        rows = [[0.6, 0, 0, 60, 95], [0.6, 0, 0, 100, 100], [0, 0, 0, 80, 98]]
        self.assertEqual(label_rule_scenarios(rows).tolist(), [RULE_LABELS[0]] * 3)

    def test_just_beyond_each_threshold_activates_only_its_rule(self):
        rows = [
            [0.60001, 0, 0, 80, 98],
            [0.1, 0, 0, 59.999, 98],
            [0.1, 0, 0, 100.001, 98],
            [0.1, 0, 0, 80, 94.999],
        ]
        self.assertEqual(label_rule_scenarios(rows).tolist(),
                         [RULE_LABELS[1], RULE_LABELS[2], RULE_LABELS[2], RULE_LABELS[2]])

    def test_left_and_right_are_laterality_not_a_severity_ranking(self):
        rows = [[0.1, 1, 0, 80, 98], [0.1, 2, 0, 80, 98]]
        self.assertEqual(label_rule_scenarios(rows).tolist(), [RULE_LABELS[1]] * 2)

    def test_motor_sign_is_retained_with_vitals_inside_reference_ranges(self):
        rows = [[0.1, 0, 1, 60, 95], [0.1, 0, 2, 100, 100], [0.7, 0, 0, 80, 98]]
        self.assertEqual(label_rule_scenarios(rows).tolist(), [RULE_LABELS[1]] * 3)

    def test_combined_motor_and_vital_rules_have_explicit_class(self):
        rows = [[0.7, 0, 0, 110, 98], [0.1, 1, 0, 80, 94], [0.1, 0, 1, 50, 98]]
        self.assertEqual(label_rule_scenarios(rows).tolist(), [RULE_LABELS[3]] * 3)

    def test_any_missing_measurement_takes_precedence_over_other_rules(self):
        rows = np.array([[0.7, 2, 2, 110, 90]] * 5, dtype=float)
        for i in range(len(FEATURE_NAMES)):
            rows[i, i] = np.nan
        self.assertEqual(label_rule_scenarios(rows).tolist(), [RULE_LABELS[4]] * 5)
        self.assertEqual(label_rule_scenarios([[None] * 5])[0], RULE_LABELS[4])

    def test_zero_vitals_are_missing_but_zero_motor_measurements_are_observations(self):
        rows = [[0, 0, 0, 0, 98], [0, 0, 0, 80, 0], [0, 0, 0, 80, 98]]
        self.assertEqual(label_rule_scenarios(rows).tolist(),
                         [RULE_LABELS[4], RULE_LABELS[4], RULE_LABELS[0]])

    def test_invalid_measurements_are_rejected_instead_of_labeled(self):
        for row in ([0.1, 3, 0, 80, 98], [0.1, 0, 0, 80, 101],
                    [-1, 0, 0, 80, 98], [0.1, 0, 0, float("inf"), 98]):
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    label_rule_scenarios([row])

    def test_config_is_serializable_and_labels_do_not_claim_avc_or_normality(self):
        json.dumps({"version": RULE_VERSION, "config": RULE_CONFIG, "sources": SOURCE_URLS})
        self.assertEqual(RULE_VERSION, "1.0")
        for label in RULE_LABELS:
            self.assertTrue(label.startswith("DEMO_"))
            for forbidden in ("AVC", "NORMAL", "BAIXO_RISCO"):
                self.assertNotIn(forbidden, label)


class RuleDatasetTests(unittest.TestCase):
    def test_seed_reproduces_features_labels_and_groups(self):
        first = make_rule_demo_dataset(n_patients=75, random_state=17)
        second = make_rule_demo_dataset(n_patients=75, random_state=17)
        for a, b in zip(first, second):
            np.testing.assert_array_equal(a, b)
        other = make_rule_demo_dataset(n_patients=75, random_state=18)
        self.assertFalse(np.array_equal(first[0], other[0], equal_nan=True))

    def test_five_features_no_ecg_and_two_evaluations_per_group(self):
        X, y, groups = make_rule_demo_dataset(n_patients=77)
        self.assertEqual(X.shape, (154, 5))
        self.assertEqual(len(y), len(groups))
        self.assertEqual(set(Counter(groups).values()), {2})
        self.assertNotIn("ecg", FEATURE_NAMES)
        self.assertIn("heart_rate", FEATURE_NAMES)
        self.assertFalse(np.isnan(X).all(axis=1).any())
        np.testing.assert_array_equal(y, label_rule_scenarios(X))

    def test_balanced_fictitious_groups_and_varied_missingness(self):
        X, y, groups = make_rule_demo_dataset()
        self.assertEqual(set(y), set(RULE_LABELS))
        self.assertEqual(set(Counter(y).values()), {300})
        for group in np.unique(groups):
            self.assertEqual(len(set(y[groups == group])), 1)
        self.assertTrue(np.isnan(X).any(axis=0).all())
        self.assertTrue((X[:, 3] < 60).any())
        self.assertTrue((X[:, 3] > 100).any())
        self.assertTrue((X[:, 4] < 95).any())

    def test_motor_rules_include_individual_feature_triggers(self):
        X, y, _ = make_rule_demo_dataset()
        motor = X[y == RULE_LABELS[1]]
        self.assertTrue(((motor[:, 0] > 0.6) & (motor[:, 1] == 0) & (motor[:, 2] == 0)).any())
        self.assertTrue(((motor[:, 0] <= 0.6) & (motor[:, 1] > 0) & (motor[:, 2] == 0)).any())
        self.assertTrue(((motor[:, 0] <= 0.6) & (motor[:, 1] == 0) & (motor[:, 2] > 0)).any())

    def test_rejects_too_small_or_noninteger_generation(self):
        for count in (0, 24, 25.5, True):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    make_rule_demo_dataset(n_patients=count)


if __name__ == "__main__":
    unittest.main()

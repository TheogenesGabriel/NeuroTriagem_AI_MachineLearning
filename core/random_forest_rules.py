"""Cenários sintéticos para uma floresta que imita regras explícitas.

Os rótulos descrevem acionamento de regras, nunca diagnóstico ou risco de AVC.
Como o alvo é calculado das próprias entradas, métricas medem fidelidade às
regras e não fornecem validação clínica. O gerador não simula fisiologia nem
impõe uma relação epidemiológica entre sinais vitais e AVC.
"""

from __future__ import annotations

import numpy as np

from core.random_forest_model import FEATURE_NAMES, normalize_features


RULE_VERSION = "1.0"
RULE_CONFIG = {
    "arm_ratio_threshold": 0.6,
    "heart_rate_low": 60,
    "heart_rate_high": 100,
    "spo2_low": 95,
}
SOURCE_URLS = {
    "stroke_warning_signs": "https://www.stroke.org/en/about-stroke/stroke-symptoms",
    "heart_rate_reference": (
        "https://www.heart.org/en/health-topics/high-blood-pressure/"
        "the-facts-about-high-blood-pressure/all-about-heart-rate-pulse"
    ),
    "spo2_reference": "https://www.fda.gov/consumers/consumer-updates/pulse-oximeter-basics",
    "stroke_oxygen_context": "https://www.nice.org.uk/guidance/NG128/chapter/recommendations",
}
RULE_LABELS = (
    "DEMO_SEM_REGRA_ACIONADA",
    "DEMO_SINAL_MOTOR",
    "DEMO_FAIXA_VITAL",
    "DEMO_MOTOR_E_VITAL",
    "DEMO_DADOS_INCOMPLETOS",
)


def label_rule_scenarios(X) -> np.ndarray:
    """Rotula a matriz do contrato atual, com ausência tendo precedência.

    arm_ratio > 0,6 é uma escolha de engenharia já existente no projeto,
    sem validação como corte clínico. BPM fora de [60,100] e SpO2 < 95 são
    referências gerais, não evidência de presença/ausência de AVC. A função
    preserva zeros observados em face/braço; zeros legados de vitais viram NaN.
    """
    values = normalize_features(X)
    columns = {name: values[:, index] for index, name in enumerate(FEATURE_NAMES)}
    motor = (
        (columns["arm_ratio"] > RULE_CONFIG["arm_ratio_threshold"])
        | (columns["arm_weak_side_code"] > 0)
        | (columns["facial_asymmetry_score"] > 0)
    )
    vital = (
        (columns["heart_rate"] < RULE_CONFIG["heart_rate_low"])
        | (columns["heart_rate"] > RULE_CONFIG["heart_rate_high"])
        | (columns["spo2"] < RULE_CONFIG["spo2_low"])
    )
    labels = np.full(len(values), RULE_LABELS[0], dtype="<U32")
    labels[motor & ~vital] = RULE_LABELS[1]
    labels[~motor & vital] = RULE_LABELS[2]
    labels[motor & vital] = RULE_LABELS[3]
    labels[np.isnan(values).any(axis=1)] = RULE_LABELS[4]
    return labels


def make_rule_demo_dataset(n_patients=750, random_state=42):
    """Retorna X, rótulos de regra e IDs fictícios, com duas avaliações por ID.

    Distribui participantes entre cinco classes, com diferença de no máximo
    um grupo por classe. Os padrões de motor e vital variam independentemente
    dentro das classes; combinações incoerentes clinicamente são casos de teste
    de software, não alegações sobre a distribuição de pacientes. A frequência
    artificial de classes não representa prevalência de AVC.
    """
    if not isinstance(n_patients, (int, np.integer)) or n_patients < 25:
        raise ValueError("Use pelo menos 25 participantes fictícios para as cinco classes.")
    rng = np.random.default_rng(random_state)
    categories = np.arange(n_patients) % len(RULE_LABELS)
    rng.shuffle(categories)
    rows, groups = [], []

    for patient, category in enumerate(categories):
        motor_enabled = category in (1, 3)
        vital_enabled = category in (2, 3)
        if category == 4:
            motor_enabled = bool(rng.integers(0, 2))
            vital_enabled = bool(rng.integers(0, 2))

        # Máscara: 1=ratio, 2=lado, 4=face. Inclui ativação por cada atributo isolado.
        motor_mask = int(rng.integers(1, 8)) if motor_enabled else 0
        side = int(rng.integers(1, 3)) if motor_mask & 2 else 0
        face = int(rng.integers(1, 3)) if motor_mask & 4 else 0
        ratio_bounds = (0.6001, 2.0) if motor_mask & 1 else (0.0, 0.6)
        ratio_center = rng.uniform(*ratio_bounds)

        # Frequência baixa/alta e saturação baixa são dimensões de teste distintas.
        vital_patterns = ((-1, False), (1, False), (0, True), (-1, True), (1, True))
        heart_mode, low_spo2 = vital_patterns[int(rng.integers(0, 5))] if vital_enabled else (0, False)
        heart_bounds = {0: (60.0, 100.0), -1: (35.0, 59.999), 1: (100.001, 160.0)}[heart_mode]
        spo2_bounds = (75.0, 94.999) if low_spo2 else (95.0, 100.0)
        heart_center = rng.uniform(*heart_bounds)
        spo2_center = rng.uniform(*spo2_bounds)
        missing_columns = (
            rng.choice(len(FEATURE_NAMES), size=int(rng.integers(1, 3)), replace=False)
            if category == 4 else []
        )

        for _ in range(2):
            row = np.array([
                np.clip(ratio_center + rng.normal(0, 0.025), *ratio_bounds),
                side,
                face,
                np.clip(heart_center + rng.normal(0, 2.0), *heart_bounds),
                np.clip(spo2_center + rng.normal(0, 0.3), *spo2_bounds),
            ], dtype=float)
            row[missing_columns] = np.nan
            rows.append(row)
            groups.append(f"REGRAS_DEMO_{patient:05d}")

    X = np.asarray(rows, dtype=float)
    return X, label_rule_scenarios(X), np.asarray(groups, dtype=str)

"""Treino reproduzível do baseline tabular, com separação por paciente.

As classes precisam vir de uma referência independente das cinco medidas.
O gerador de demonstração apenas exercita o software; não simula um diagnóstico.
Nenhuma função deste módulo ativa modelos no aplicativo.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score, average_precision_score, balanced_accuracy_score,
    classification_report, confusion_matrix, f1_score, roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedGroupKFold

from core.random_forest_model import FEATURE_NAMES, build_pipeline, normalize_features


def _nonempty_strings(values, name):
    values = np.asarray(values, dtype=object)
    if values.ndim != 1:
        raise ValueError(f"{name} deve ser um vetor de uma dimensão.")
    result = []
    for value in values:
        if value is None or (isinstance(value, (float, np.floating)) and np.isnan(value)):
            raise ValueError(f"{name} contém valor ausente.")
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            raise ValueError(f"{name} contém valor vazio ou ausente.")
        result.append(text)
    return np.asarray(result, dtype=str)


def _validate_data(X, y, groups):
    X = normalize_features(X)
    y = _nonempty_strings(y, "Rótulos")
    groups = _nonempty_strings(groups, "Identificadores de paciente")
    if len(X) != len(y) or len(X) != len(groups):
        raise ValueError("X, rótulos e pacientes devem ter o mesmo número de linhas.")
    if not len(X):
        raise ValueError("O dataset está vazio; preencha o CSV com dados rotulados.")
    if len(np.unique(y)) < 2:
        raise ValueError("São necessárias pelo menos duas classes de referência.")
    if np.isnan(X).all(axis=1).any():
        raise ValueError("Há linha sem nenhuma medida; remova ou complete a observação.")
    _check_observed_columns(X)
    seen = set()
    for row, label, patient in zip(X, y, groups):
        key = (patient, label, *(None if np.isnan(v) else float(v) for v in row))
        if key in seen:
            raise ValueError("Há observações duplicadas para o mesmo paciente e rótulo.")
        seen.add(key)
    return X, y, groups


def _check_observed_columns(X):
    empty = [name for name, missing in zip(FEATURE_NAMES, np.isnan(X).all(axis=0)) if missing]
    if empty:
        raise ValueError("Colunas sem observações no treino: " + ", ".join(empty))


def load_dataset(path, target_column="risco", group_column="patient_id"):
    """Lê CSV UTF-8 separado por vírgula; retorna X, rótulos e IDs pseudônimos.

    Células vazias nas medidas significam ausente. Não preenche rótulos nem
    infere classes por limiares; colunas adicionais são ignoradas no modelo.
    """
    if target_column == group_column or target_column in FEATURE_NAMES or group_column in FEATURE_NAMES:
        raise ValueError("Rótulo, identificador do paciente e features devem ser colunas distintas.")
    rows = []
    labels = []
    patients = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("O CSV contém nomes de colunas duplicados.")
        missing = set(FEATURE_NAMES + [target_column, group_column]) - set(headers)
        if missing:
            raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Linha {line}: quantidade de campos diferente do cabeçalho.")
            try:
                values = [float(row[name]) if row[name].strip() else np.nan for name in FEATURE_NAMES]
            except ValueError as exc:
                raise ValueError(f"Linha {line}: medidas devem ser numéricas, com ponto decimal.") from exc
            rows.append(values)
            labels.append(row[target_column])
            patients.append(row[group_column])
    if not rows:
        raise ValueError("O dataset está vazio; preencha o CSV com dados rotulados.")
    return _validate_data(rows, labels, patients)


def make_demo_dataset(n_patients=180, random_state=42):
    """Gera duas medidas por paciente fictício e classes arbitrárias de software.

    A correlação foi construída artificialmente: métricas obtidas aqui não
    estimam desempenho em pessoas, AVC ou categorias clínicas de risco.
    """
    if not isinstance(n_patients, (int, np.integer)) or n_patients < 30:
        raise ValueError("A demonstração requer pelo menos 30 pacientes fictícios.")
    rng = np.random.default_rng(random_state)
    class_index = np.arange(n_patients) % 3
    rng.shuffle(class_index)
    rows, labels, patients = [], [], []
    for patient, category in enumerate(class_index):
        # Efeitos de indivíduo compartilhados entre as duas observações.
        center = rng.normal([0.12 + category * 0.22, 72 + category * 7, 98 - category], [0.12, 10, 1])
        for _ in range(2):
            row = [
                max(0, center[0] + rng.normal(0, 0.06)),
                float(rng.integers(0, 3)),
                float(category if rng.random() < 0.65 else rng.integers(0, 3)),
                max(1, center[1] + rng.normal(0, 3)),
                np.clip(center[2] + rng.normal(0, 0.6), 1, 100),
            ]
            rows.append(row)
            labels.append(f"CLASSE_DEMO_{'ABC'[category]}")
            patients.append(f"DEMO_{patient:04d}")
    X = np.asarray(rows, dtype=float)
    X[rng.random(X.shape) < 0.035] = np.nan
    # Preserva ao menos uma observação por linha, mesmo para outras sementes.
    X[np.isnan(X).all(axis=1), 0] = 0.0
    return X, np.asarray(labels), np.asarray(patients)


def _validate_split(X, y, groups, train, validation, description):
    if set(groups[train]) & set(groups[validation]):
        raise ValueError(f"{description}: um paciente aparece nos dois subconjuntos.")
    classes = set(y)
    if set(y[train]) != classes or set(y[validation]) != classes:
        raise ValueError(
            f"{description}: faltam classes em um subconjunto. Colete mais pacientes "
            "por classe ou reduza o número de folds antes de avaliar o teste."
        )
    _check_observed_columns(X[train])


def _check_group_support(y, groups, n_splits, description):
    for label in np.unique(y):
        count = len(np.unique(groups[y == label]))
        if count < n_splits:
            raise ValueError(
                f"{description}: classe {label!r} tem {count} pacientes; "
                f"são necessários ao menos {n_splits} para esta configuração."
            )


def _metrics(y, predicted, probability, classes):
    matrix = confusion_matrix(y, predicted, labels=classes)
    per_class = {}
    auc, ap = [], []
    for i, label in enumerate(classes):
        tp = matrix[i, i]
        fn = matrix[i].sum() - tp
        fp = matrix[:, i].sum() - tp
        tn = matrix.sum() - tp - fn - fp
        truth = (y == label).astype(int)
        per_class[str(label)] = {
            "sensitivity": float(tp / (tp + fn)),
            "specificity": float(tn / (tn + fp)),
            "support": int(tp + fn),
        }
        auc.append(float(roc_auc_score(truth, probability[:, i])))
        ap.append(float(average_precision_score(truth, probability[:, i])))
    return {
        "accuracy": float(accuracy_score(y, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
        "f1_macro": float(f1_score(y, predicted, average="macro", zero_division=0)),
        "roc_auc_ovr_macro": float(np.mean(auc)),
        "average_precision_ovr_macro": float(np.mean(ap)),
        "classification_report": classification_report(y, predicted, labels=classes, output_dict=True, zero_division=0),
        "confusion_matrix": matrix.tolist(),
        "classes": classes.tolist(),
        "per_class": per_class,
    }


def train_evaluate(
    X, y, groups, *, random_state=42, n_iter=8, cv_splits=3, test_splits=5,
    parameter_distributions=None, permutation_repeats=5,
):
    """Ajusta hiperparâmetros só no treino e avalia um holdout de pacientes.

    O primeiro fold de uma divisão fixa é o teste (~1/test_splits dos dados).
    A escolha do fold não depende do desempenho. A imputação é ajustada dentro
    de cada fold; o teste não entra na busca nem no refit. A importância por
    permutação é uma análise posterior, não uma etapa de seleção de variáveis.
    """
    X, y, groups = _validate_data(X, y, groups)
    for name, value, minimum in (("cv_splits", cv_splits, 2), ("test_splits", test_splits, 2),
                                 ("n_iter", n_iter, 1), ("permutation_repeats", permutation_repeats, 1)):
        if not isinstance(value, (int, np.integer)) or value < minimum:
            raise ValueError(f"{name} deve ser inteiro >= {minimum}.")
    _check_group_support(y, groups, test_splits, "Separação de teste")
    outer = StratifiedGroupKFold(n_splits=test_splits, shuffle=True, random_state=random_state)
    train, test = next(outer.split(X, y, groups))
    _validate_split(X, y, groups, train, test, "Teste reservado")
    X_train, y_train, groups_train = X[train], y[train], groups[train]
    _check_group_support(y_train, groups_train, cv_splits, "Validação cruzada")
    inner = StratifiedGroupKFold(n_splits=cv_splits, shuffle=True, random_state=random_state + 1)
    folds = list(inner.split(X_train, y_train, groups_train))
    for number, (fit, validation) in enumerate(folds, 1):
        _validate_split(X_train, y_train, groups_train, fit, validation, f"Fold {number}")
    parameters = parameter_distributions if parameter_distributions is not None else {
        "forest__n_estimators": [100, 200, 300],
        "forest__max_depth": [None, 4, 8, 12],
        "forest__min_samples_leaf": [1, 2, 4, 8],
        "forest__max_features": ["sqrt", None],
        "forest__class_weight": ["balanced", "balanced_subsample"],
    }
    search = RandomizedSearchCV(
        build_pipeline(random_state=random_state), parameters,
        n_iter=n_iter, scoring="balanced_accuracy", cv=folds,
        refit=True, random_state=random_state, n_jobs=1, error_score="raise",
    )
    search.fit(X_train, y_train)
    pipeline = search.best_estimator_
    classes = pipeline.classes_
    dummy = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    rf_metrics = _metrics(y[test], pipeline.predict(X[test]), pipeline.predict_proba(X[test]), classes)
    dummy_metrics = _metrics(y[test], dummy.predict(X[test]), dummy.predict_proba(X[test]), dummy.classes_)
    importance = permutation_importance(
        pipeline, X[test], y[test], n_repeats=permutation_repeats,
        random_state=random_state, scoring="balanced_accuracy", n_jobs=1,
    )
    cv_results = [
        {"params": params, "mean_balanced_accuracy": float(mean),
         "std_balanced_accuracy": float(std), "rank": int(rank)}
        for params, mean, std, rank in zip(
            search.cv_results_["params"], search.cv_results_["mean_test_score"],
            search.cv_results_["std_test_score"], search.cv_results_["rank_test_score"],
        )
    ]
    report = {
        "random_state": int(random_state), "sklearn_version": sklearn.__version__,
        "feature_names": list(FEATURE_NAMES),
        "selection_metric": "balanced_accuracy", "best_params": search.best_params_,
        "cv_best_balanced_accuracy": float(search.best_score_),
        "split": {
            "method": "StratifiedGroupKFold; primeiro fold reservado; CV somente no treino",
            "test_splits": int(test_splits), "cv_splits": int(cv_splits),
            "train_rows": int(len(train)), "test_rows": int(len(test)),
            "train_patients": int(len(np.unique(groups[train]))),
            "test_patients": int(len(np.unique(groups[test]))),
            "group_overlap": 0,
            "train_class_counts": {str(c): int(np.sum(y[train] == c)) for c in classes},
            "test_class_counts": {str(c): int(np.sum(y[test] == c)) for c in classes},
        },
        "test": {"random_forest": rf_metrics, "dummy": dummy_metrics},
        "limitations": [
            "Resultados internos não representam validação clínica ou externa.",
            "Probabilidades não foram calibradas.",
            "Cada linha tem o mesmo peso nas métricas; pacientes com mais visitas contribuem mais.",
            "Não reutilize o teste para escolher novos parâmetros, variáveis ou limiares.",
        ],
    }
    return {
        "pipeline": pipeline, "report": report, "train_indices": train, "test_indices": test,
        "cv_results": cv_results,
        "permutation_importance": {
            "feature_names": list(FEATURE_NAMES), "mean": importance.importances_mean.tolist(),
            "std": importance.importances_std.tolist(), "scoring": "balanced_accuracy",
        },
    }

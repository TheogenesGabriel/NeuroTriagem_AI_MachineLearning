"""Contrato compartilhado de treino e inferência experimental do NeuroTriagem.

Use apenas joblib de origem confiável: a desserialização executa código.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import warnings

import joblib
import numpy as np
import sklearn
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

FEATURE_NAMES = [
    "arm_ratio", "arm_weak_side_code", "facial_asymmetry_score", "heart_rate", "spo2",
]
SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "random_forest_risco.joblib"
EXPERIMENTAL_WARNING = (
    "Classificação experimental, sem validação clínica. "
    "As probabilidades do modelo não são uma estimativa calibrada de risco de AVC."
)


def normalize_features(X) -> np.ndarray:
    """Valida entradas; zero em BPM/SpO2 significa não medido, demais zeros são válidos.

    Arrays seguem FEATURE_NAMES; tabelas com nomes são reordenadas. Os limites
    são de formato/domínio, não limiares clínicos. None/NaN representam ausências.
    """
    if hasattr(X, "columns"):
        if len(X.columns) != len(FEATURE_NAMES) or set(X.columns) != set(FEATURE_NAMES):
            raise ValueError(f"Colunas de entrada devem ser exatamente {FEATURE_NAMES}.")
        X = X.loc[:, FEATURE_NAMES]
    try:
        values = np.array(X, dtype=float, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("As features devem ser numéricas; use vazio/None/NaN para ausência.") from exc
    if values.ndim != 2 or values.shape[1] != len(FEATURE_NAMES) or not len(values):
        raise ValueError(f"Esperada matriz não vazia com {len(FEATURE_NAMES)} features.")
    if np.isinf(values).any():
        raise ValueError("Features não podem conter infinito.")
    for index, name in enumerate(FEATURE_NAMES):
        column = values[:, index]
        observed = column[~np.isnan(column)]
        if name in ("arm_weak_side_code", "facial_asymmetry_score"):
            if not np.isin(observed, [0, 1, 2]).all():
                raise ValueError(f"{name} deve ser 0, 1, 2 ou ausente.")
        elif (observed < 0).any() or (name == "spo2" and (observed > 100).any()):
            raise ValueError(f"{name} fora do domínio permitido.")
        if name in ("heart_rate", "spo2"):
            values[column == 0, index] = np.nan
    return values


class FeatureNormalizer(TransformerMixin, BaseEstimator):
    """Transformação persistível no mesmo módulo usado pelo aplicativo."""

    def fit(self, X, y=None):
        values = normalize_features(X)
        empty_columns = np.isnan(values).all(axis=0)
        if empty_columns.any():
            names = [n for n, empty in zip(FEATURE_NAMES, empty_columns) if empty]
            raise ValueError(f"Treino sem observações para as features: {names}.")
        if np.isnan(values).all(axis=1).any():
            raise ValueError("Treino contém registros sem nenhuma medição.")
        self.n_features_in_ = len(FEATURE_NAMES)
        return self

    def transform(self, X):
        check_is_fitted(self, "n_features_in_")
        return normalize_features(X)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(FEATURE_NAMES, dtype=object)


def build_pipeline(random_state=42, **rf_kwargs) -> Pipeline:
    """Imputação ajustada dentro de cada fold, sem normalização desnecessária."""
    params = dict(n_estimators=200, class_weight="balanced", n_jobs=1)
    params.update(rf_kwargs)
    return Pipeline([
        ("features", FeatureNormalizer()),
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("forest", RandomForestClassifier(random_state=random_state, **params)),
    ])


def save_artifact(pipeline, path, *, metadata) -> Path:
    """Salva pipeline + contrato + procedência. Não atesta validação clínica."""
    if not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != ["features", "imputer", "forest"]:
        raise ValueError("Exporte o pipeline completo criado por build_pipeline().")
    check_is_fitted(pipeline.named_steps["forest"])
    if len(pipeline.classes_) < 2:
        raise ValueError("O classificador deve ter pelo menos duas classes de referência.")
    if metadata.get("data_kind") not in ("real", "synthetic"):
        raise ValueError("metadata.data_kind deve indicar real ou synthetic.")
    if not str(metadata.get("target_description", "")).strip():
        raise ValueError("Descreva o significado e a origem dos rótulos em target_description.")
    destination = Path(path).resolve()
    if metadata["data_kind"] == "synthetic" and destination == DEFAULT_MODEL_PATH:
        raise ValueError("A demonstração sintética deve ficar fora do caminho de ativação do aplicativo.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "sklearn_version": sklearn.__version__,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pipeline": pipeline,
        "metadata": dict(metadata, clinical_validation=False),
    }
    joblib.dump(artifact, destination)
    return destination


class RiscoRandomForest:
    """Adaptador para a interface; ausência/erro de modelo não interrompe a UI.

    allow_demo=True libera explicitamente artefatos sintéticos no notebook e no
    modo de demonstração do aplicativo (core.random_forest_runtime).
    O caminho padrão é absoluto e independe do diretório de execução do app.
    """

    def __init__(self, model_path=None, *, allow_demo=False):
        self.model_path = Path(model_path) if model_path is not None else DEFAULT_MODEL_PATH
        self.allow_demo = allow_demo
        self.model: Pipeline | None = None
        self.metadata = {}
        self.load_error = None
        self._load_if_exists()

    def _load_if_exists(self):
        self.model = None
        self.metadata = {}
        self.load_error = None
        if not self.model_path.exists():
            self.load_error = "Modelo Random Forest ainda não treinado com dados rotulados."
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", InconsistentVersionWarning)
                artifact = joblib.load(self.model_path)
            if not isinstance(artifact, dict) or artifact.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Artefato antigo ou incompatível; reexporte pelo notebook.")
            if artifact.get("feature_names") != FEATURE_NAMES:
                raise ValueError("Contrato de features incompatível com esta versão do aplicativo.")
            if artifact.get("sklearn_version") != sklearn.__version__:
                raise ValueError("Use a mesma versão de scikit-learn do treinamento ou retreine.")
            metadata = artifact.get("metadata", {})
            if metadata.get("data_kind") not in ("real", "synthetic"):
                raise ValueError("Artefato sem procedência de dados declarada.")
            if metadata["data_kind"] == "synthetic" and not self.allow_demo:
                raise ValueError("Modelo sintético de demonstração não pode classificar uma triagem.")
            pipeline = artifact.get("pipeline")
            if not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != ["features", "imputer", "forest"]:
                raise ValueError("Pipeline de inferência incompatível.")
            if not isinstance(pipeline.named_steps["features"], FeatureNormalizer):
                raise ValueError("Pré-processamento incompatível.")
            if not isinstance(pipeline.named_steps["forest"], RandomForestClassifier):
                raise ValueError("Estimador incompatível.")
            if not isinstance(pipeline.named_steps["imputer"], SimpleImputer):
                raise ValueError("Imputador incompatível.")
            check_is_fitted(pipeline.named_steps["imputer"])
            check_is_fitted(pipeline.named_steps["forest"])
            if len(pipeline.classes_) < 2:
                raise ValueError("O classificador precisa de pelo menos duas classes.")
            if pipeline.named_steps["features"].n_features_in_ != len(FEATURE_NAMES):
                raise ValueError("Quantidade de features incompatível.")
            self.model = pipeline
            self.metadata = metadata
        except Exception as exc:
            self.load_error = f"Modelo indisponível: {exc}"

    def train(self, X, y, *, data_kind, target_description, **rf_kwargs):
        """Compatibilidade; prefira train_evaluate no notebook para medir desempenho.

        data_kind e descrição são obrigatórios. Para demonstração, use outro caminho.
        """
        pipeline = build_pipeline(**rf_kwargs)
        pipeline.fit(X, y)
        save_artifact(pipeline, self.model_path, metadata={
            "data_kind": data_kind, "target_description": target_description,
            "evaluation": "not_evaluated",
        })
        self._load_if_exists()

    @staticmethod
    def _features_to_vector(features: dict) -> list:
        return [features.get(name, None) for name in FEATURE_NAMES]

    @staticmethod
    def _unavailable(message):
        return {"risco": "indefinido", "confianca": None, "probabilidades": {}, "aviso": message}

    def predict(self, features: dict) -> dict:
        if self.model is None:
            return self._unavailable(self.load_error or "Modelo indisponível.")
        try:
            values = normalize_features([self._features_to_vector(features)])
            missing = [name for name, value in zip(FEATURE_NAMES, values[0]) if np.isnan(value)]
            if len(missing) == len(FEATURE_NAMES):
                return self._unavailable("Sem medições válidas para realizar a classificação experimental.")
            probabilities = self.model.predict_proba(values)[0]
            index = int(np.argmax(probabilities))
            labels = self.model.classes_
            message = EXPERIMENTAL_WARNING
            if self.metadata.get("data_kind") == "synthetic":
                message = "DEMONSTRAÇÃO SINTÉTICA — classes artificiais. " + message
            if self.metadata.get("label_provenance") == "synthetic_rules":
                message = "IMITAÇÃO DE REGRAS — não estima presença ou ausência de AVC. " + message
            if missing:
                message += " Valores ausentes imputados: " + ", ".join(missing) + "."
            return {
                "risco": str(labels[index]),
                "confianca": float(probabilities[index]),
                "probabilidades": {str(label): float(p) for label, p in zip(labels, probabilities)},
                "aviso": message,
            }
        except (ValueError, TypeError, AttributeError) as exc:
            return self._unavailable(f"Não foi possível classificar as medições: {exc}")

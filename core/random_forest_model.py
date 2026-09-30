"""
Modelo de decisao final (Random Forest) - NeuroTriagem.AI

TODO: o dataset de treino, o conjunto final de features e os rotulos
de risco nao foram definidos nesta conversa. Esta classe define a
interface esperada (treinar / prever) e um fallback que NAO quebra a
aplicacao enquanto o modelo real nao existe.

Features candidatas usadas no placeholder abaixo, com base no que foi
discutido ate agora:
  - arm_ratio               -> ratio de assimetria do teste do braco
  - arm_weak_side_code      -> 0=nenhum, 1=esquerdo, 2=direito
  - facial_asymmetry_score  -> pior severidade da tela de assimetria facial
                               (0=normal, 1=leve, 2=forte - ver core/facial_asymmetry_logic.py)
  - heart_rate / spo2       -> dados fisiologicos vindos da BitDogLab (MAX30102)

Ajuste _features_to_vector() e train() assim que o dataset e a lista
definitiva de features existirem.
"""

from __future__ import annotations

import os

import joblib
from sklearn.ensemble import RandomForestClassifier


class RiscoRandomForest:
    def __init__(self, model_path: str = "models/random_forest_risco.joblib"):
        self.model_path = model_path
        self.model: RandomForestClassifier | None = None
        self._load_if_exists()

    def _load_if_exists(self):
        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)

    def train(self, X, y, **rf_kwargs):
        """TODO: chamar com o dataset real assim que existir."""
        self.model = RandomForestClassifier(
            n_estimators=rf_kwargs.pop("n_estimators", 200),
            random_state=rf_kwargs.pop("random_state", 42),
            **rf_kwargs,
        )
        self.model.fit(X, y)
        os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
        joblib.dump(self.model, self.model_path)

    def predict(self, features: dict) -> dict:
        """
        Recebe um dict de features ja calculadas pelas outras etapas
        (teste do braco, assimetria facial, sensores da BitDogLab) e
        devolve o veredito. Sem modelo treinado, devolve um veredito
        neutro para nao travar o fluxo da aplicacao.
        """
        if self.model is None:
            return {
                "risco": "indefinido",
                "confianca": None,
                "aviso": "Modelo Random Forest ainda nao treinado (TODO).",
            }

        vetor = self._features_to_vector(features)
        pred = self.model.predict([vetor])[0]
        proba = self.model.predict_proba([vetor])[0].max()
        return {"risco": pred, "confianca": float(proba), "aviso": None}

    @staticmethod
    def _features_to_vector(features: dict) -> list:
        # TODO: ordem/definicao final das features do modelo treinado
        return [
            features.get("arm_ratio", 0.0),
            features.get("arm_weak_side_code", 0),
            features.get("facial_asymmetry_score", 0.0),
            features.get("heart_rate", 0.0),
            features.get("spo2", 0.0),
        ]

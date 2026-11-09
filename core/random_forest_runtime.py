"""Carregamento e apresentação do protótipo integrado ao aplicativo.

A liberação de dados sintéticos é explícita e restrita ao artefato demonstrativo.
RiscoRandomForest() mantém o contrato original para candidatos de dados reais.
"""

import numpy as np

from core.facial_test_session import FACIAL_RESULT_LABELS
from core.random_forest_model import (
    DEFAULT_MODEL_PATH, FEATURE_NAMES, PROJECT_ROOT, RiscoRandomForest, normalize_features,
)
from core.random_forest_rules import RULE_CONFIG, RULE_LABELS, RULE_VERSION, label_rule_scenarios


DEMO_MODEL_PATH = PROJECT_ROOT / "models" / "random_forest_regras_experimental.joblib"
FEATURE_LABELS = {
    "arm_ratio": "assimetria do braço", "arm_weak_side_code": "lado do braço",
    "facial_asymmetry_score": "assimetria facial", "heart_rate": "batimentos cardíacos (BPM)",
    "spo2": "SpO₂",
}
RESULT_LABELS = {
    "DEMO_SINAL_MOTOR": "Regra de sinal motor acionada",
    "DEMO_FAIXA_VITAL": "Regra de faixa vital acionada",
    "DEMO_MOTOR_E_VITAL": "Regras de sinal motor e faixa vital acionadas",
    "DEMO_SEM_REGRA_ACIONADA": "Nenhuma regra acionada — não exclui AVC",
    "DEMO_DADOS_INCOMPLETOS": "Dados incompletos — há medições ausentes",
    "indefinido": "Resultado indisponível",
}


def load_app_model():
    """Prioriza candidato real instalado; senão, libera a demonstração conhecida.

    Candidato existente mas inválido permanece indisponível. Isso evita uma troca
    silenciosa para a demonstração caso haja incompatibilidade do modelo real.
    """
    if DEFAULT_MODEL_PATH.exists():
        return RiscoRandomForest(DEFAULT_MODEL_PATH)
    model = RiscoRandomForest(DEMO_MODEL_PATH, allow_demo=True)
    if model.model is not None:
        metadata = model.metadata
        matches = (
            metadata.get("data_kind") == "synthetic"
            and metadata.get("learning_task") == "rule_imitation"
            and metadata.get("label_provenance") == "synthetic_rules"
            and metadata.get("rule_version") == RULE_VERSION
            and metadata.get("rule_config") == RULE_CONFIG
            and set(model.model.classes_) == set(RULE_LABELS)
        )
        if not matches:
            model.model = None
            model.metadata = {}
            model.load_error = "Modelo de demonstração incompatível com as regras desta versão."
    return model


def get_model_status(model):
    if model.model is None:
        return "Random Forest indisponível — " + (model.load_error or "verifique o modelo instalado.")
    if model.metadata.get("data_kind") == "synthetic":
        return "Random Forest · demonstração experimental com dados sintéticos. Não diagnostica AVC."
    return "Random Forest · candidato experimental com dados reais. Sem validação clínica."


def build_result_text(veredito, features):
    """Traduz classes e distingue previsão, regra exata e disponibilidade dos dados.

    Nunca troca a previsão da floresta pela regra, nem exibe sua probabilidade
    como risco clínico. A comparação é própria do protótipo de imitação de regras.
    """
    label = str(veredito.get("risco", "indefinido"))
    demo = label in RULE_LABELS
    lines = [
        "Demonstração experimental — modelo treinado com dados sintéticos." if demo
        else "Classificação experimental",
        "Previsão do Random Forest: " + RESULT_LABELS.get(label, label),
    ]
    try:
        values = normalize_features([[features.get(name) for name in FEATURE_NAMES]])
    except (ValueError, TypeError, AttributeError):
        lines.append("Há medições inválidas; revise as entradas.")
    else:
        face = values[0, FEATURE_NAMES.index("facial_asymmetry_score")]
        face_label = "Sem resultado válido" if np.isnan(face) else FACIAL_RESULT_LABELS[int(face)]
        lines.append("Classificação facial do protótipo: " + face_label)
        missing = [FEATURE_LABELS[name] for name, value in zip(FEATURE_NAMES, values[0]) if np.isnan(value)]
        if missing:
            lines.append("Medições ausentes: " + ", ".join(missing) + ".")
        if demo:
            reference = str(label_rule_scenarios(values)[0])
            lines.append("Regra de referência: " + RESULT_LABELS[reference])
            if reference != label:
                lines.append("O modelo divergiu da regra neste caso.")
            if missing:
                lines.append("Uma previsão não substitui as medições que faltam.")
    if demo:
        lines.append("Este resultado não indica presença ou ausência de AVC.")
    # No modo conhecido, os avisos essenciais já aparecem acima em linguagem
    # de interface. Preserve mensagens específicas para falhas/outros modelos.
    if not demo and veredito.get("aviso"):
        lines.append(str(veredito["aviso"]))
    return "\n\n".join(lines)

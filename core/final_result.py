"""Apresentação da avaliação concluída, sem recalcular ou substituir a previsão."""

from datetime import datetime
import math

import numpy as np

from core.random_forest_model import FEATURE_NAMES, normalize_features
from core.random_forest_rules import RULE_LABELS, label_rule_scenarios
from core.random_forest_runtime import FEATURE_LABELS, RESULT_LABELS


CLASSIFICATIONS = {
    "DEMO_MOTOR_E_VITAL": (
        "Sinais motores e vitais", "alert",
        "O modelo indicou acionamento das regras motoras e de faixa vital do protótipo.",
    ),
    "DEMO_SINAL_MOTOR": (
        "Sinal motor", "attention",
        "O modelo indicou acionamento da regra motora a partir das entradas de face e braço.",
    ),
    "DEMO_FAIXA_VITAL": (
        "Faixa vital sinalizada", "attention",
        "O modelo indicou acionamento da regra de faixa vital a partir de BPM e SpO₂.",
    ),
    "DEMO_SEM_REGRA_ACIONADA": (
        "Nenhuma regra acionada", "neutral",
        "O modelo não sinalizou as regras do protótipo nesta avaliação. Isso não exclui AVC.",
    ),
    "DEMO_DADOS_INCOMPLETOS": (
        "Dados incompletos", "unavailable",
        "O modelo classificou a avaliação como incompleta. Confira as medições registradas abaixo.",
    ),
    "indefinido": (
        "Classificação indisponível", "unavailable",
        "Não foi possível obter uma classificação. As medições disponíveis permanecem no resumo.",
    ),
}


def _number(value, decimals=2):
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".").replace(".", ",")


def _card(label, value, detail, tone="neutral"):
    return dict(label=label, value=value, detail=detail, tone=tone)


def _measurements(features):
    """Valida cada campo para preservar os demais quando uma medida é inválida."""
    values = np.full((1, len(FEATURE_NAMES)), np.nan)
    invalid = []
    for index, name in enumerate(FEATURE_NAMES):
        row = [None] * len(FEATURE_NAMES)
        row[index] = features.get(name)
        try:
            values[0, index] = normalize_features([row])[0, index]
        except (ValueError, TypeError):
            invalid.append(name)
    return values, invalid


def _measurement_cards(values, invalid):
    v = dict(zip(FEATURE_NAMES, values[0]))
    face = v["facial_asymmetry_score"]
    if "facial_asymmetry_score" in invalid:
        facial = _card("Face", "Valor inválido", "Revise a medição facial.", "unavailable")
    elif np.isnan(face):
        facial = _card("Face", "Sem resultado", "Teste não concluído ou sem observação válida.", "unavailable")
    else:
        title, detail, tone = {
            0: ("Normal", "Sem assimetria reconhecida · grau 0", "neutral"),
            1: ("Atenção", "Assimetria leve · grau 1", "attention"),
            2: ("Alerta", "Assimetria alta · grau 2", "alert"),
        }[int(face)]
        facial = _card("Face", title, detail, tone)

    ratio, side = v["arm_ratio"], v["arm_weak_side_code"]
    arm_value = "Lado não medido" if np.isnan(side) else {0: "Sem lado indicado", 1: "Esquerdo", 2: "Direito"}[int(side)]
    arm_detail = "Razão não medida" if np.isnan(ratio) else "Razão de assimetria: " + _number(ratio)
    if np.isnan(ratio) and np.isnan(side):
        arm_value, arm_detail = "Sem resultado", "Teste não concluído ou sem observação válida."
    if any(name in invalid for name in ("arm_ratio", "arm_weak_side_code")):
        arm_detail += " · Há valor inválido."
    arm = _card("Braço", arm_value, arm_detail, "unavailable" if np.isnan(ratio) or np.isnan(side) else "neutral")

    cards = [facial, arm]
    for name, label, unit, detail in (
        ("heart_rate", "Batimentos", " bpm", "Frequência cardíaca registrada"),
        ("spo2", "SpO₂", "%", "Saturação periférica registrada"),
    ):
        value = v[name]
        if name in invalid:
            cards.append(_card(label, "Valor inválido", "Revise a leitura do sensor.", "unavailable"))
        elif np.isnan(value):
            cards.append(_card(label, "Não medido", "Sem leitura final disponível.", "unavailable"))
        else:
            cards.append(_card(label, _number(value) + unit, detail))
    return cards


def _joystick_metric(result, key, divisor=1, suffix=""):
    value = result.get(key)
    try:
        value = float(value) / divisor
        if not math.isfinite(value):
            return "—"
    except (ValueError, TypeError):
        return "—"
    return _number(value, 3 if key == "desvio_medio_u" else 2) + suffix


def _joystick_summary(session):
    final = session.get("final") or {}
    summary = (
        f"{final['concluidas']} de {final['total']} trajetórias concluídas"
        if "concluidas" in final and "total" in final else "Sem resultado final do joystick"
    )
    rows = []
    for key, label in (("QUADRADO", "Quadrado"), ("TRIANGULO", "Triângulo"), ("CIRCULO", "Círculo")):
        result = (session.get("resultados") or {}).get(key) or {}
        state = result.get("estado")
        status = {"CONCLUIDO": "Concluído", "TEMPO_LIMITE": "Parcial · tempo limite", "NAO_INICIADO": "Não iniciado"}.get(state, "Sem resultado")
        valid = bool(result.get("valido")) and state in ("CONCLUIDO", "TEMPO_LIMITE")
        rows.append([
            label, status,
            _joystick_metric(result, "tempo_ms", 1000) if valid else "—",
            _joystick_metric(result, "desvio_medio_u") if valid else "—",
            _joystick_metric(result, "sobreposicao_pct", suffix="%") if valid else "—",
            "Válidos" if valid else "Sem métricas",
        ])
    return summary, rows


def build_final_result(payload):
    """Converte um snapshot em texto; não chama predict nem usa joystick no RF."""
    verdict = payload.get("veredito") or {}
    label = str(verdict.get("risco", "indefinido"))
    heading, tone, subtitle = CLASSIFICATIONS.get(
        label, (RESULT_LABELS.get(label, label), "neutral", "Classificação retornada pelo modelo instalado.")
    )
    values, invalid = _measurements(payload.get("features") or {})
    missing = [name for name, value in zip(FEATURE_NAMES, values[0]) if np.isnan(value) and name not in invalid]
    notices = []
    if invalid:
        notices.append("Medições inválidas: " + ", ".join(FEATURE_LABELS[name] for name in invalid) + ".")
    if missing:
        notices.append("Medições ausentes: " + ", ".join(FEATURE_LABELS[name] for name in missing) + ". Uma previsão não substitui essas medições.")
    reference = None
    if label in RULE_LABELS and not invalid:
        reference_code = str(label_rule_scenarios(values)[0])
        reference = RESULT_LABELS[reference_code]
        if reference_code != label:
            notices.append("O Random Forest divergiu da regra de referência: " + reference + ". A classificação exibida é a previsão do modelo.")
    timestamp = ""
    if payload.get("generated_at"):
        try:
            timestamp = datetime.fromisoformat(payload["generated_at"]).strftime("%d/%m/%Y às %H:%M")
        except (TypeError, ValueError):
            pass
    joystick_summary, joystick_rows = _joystick_summary(payload.get("joystick") or {})
    details = "Previsão do Random Forest: " + RESULT_LABELS.get(label, label)
    if verdict.get("aviso"):
        details += "\n\n" + str(verdict["aviso"])
    return dict(
        heading=heading, subtitle=subtitle, tone=tone, timestamp=timestamp,
        model_status=str(payload.get("model_status") or "Estado do modelo não informado."),
        disclaimer="Resultado experimental do protótipo. Não confirma nem exclui AVC.",
        cards=_measurement_cards(values, invalid), notices=notices, reference=reference,
        joystick_summary=joystick_summary, joystick_rows=joystick_rows, details=details,
    )

"""
Motor de deteccao de assimetria facial - NeuroTriagem.AI
-----------------------------------------------------------
Modelo real: YOLOv8 de DETECCAO (nao pose), treinado no Roboflow,
projeto "face-paralysis", 6 classes:

    Normal_Eyes        Normal_Mouth
    SlightPalsy_Eyes   SlightPalsy_Mouth
    StrongPalsy_Eyes   StrongPalsy_Mouth

Ou seja, cada classe ja carrega a regiao do rosto (olhos/boca) e o
grau de severidade (Normal / Leve / Forte). Nao ha keypoints aqui,
entao a logica e bem mais simples que o teste do braco: rodar
deteccao por frame, desenhar as caixas, e manter uma janela de votos
(por severidade) pra suavizar o veredito exibido - mesma ideia do
`class_vote_window` do teste do braco, so que aplicada a severidade
em vez de lado (esquerda/direita).

Interface exposta pra tela (screens/facial_screen.py):
    engine.reset()                  -> zera a janela de votos
    engine.process_frame(frame_raw) -> processa 1 frame, devolve o
                                        frame anotado (BGR)
    engine.severity                 -> 0 (normal) / 1 (leve) / 2 (forte),
                                        pior grau observado na janela
    engine.severity_label           -> texto correspondente
    engine.detections               -> lista [(classe, conf, severidade), ...]
                                        do ultimo frame, se precisar em outro lugar
"""

from __future__ import annotations

import collections
import logging
import os
from dataclasses import dataclass

import cv2

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - ambiente de dev sem ultralytics ainda
    YOLO = None

from core.arm_test_logic import draw_ui_element

log = logging.getLogger("facial_asymmetry")


def _env(name: str, default, cast=str):
    val = os.environ.get(name)
    return cast(val) if val is not None else default


@dataclass
class FacialConfig:
    camera_index: int = _env("FACE_CAMERA_INDEX", 0, int)
    model_path: str = _env("FACE_MODEL_PATH", "models/facial_asymmetry_best.pt")
    conf_threshold: float = _env("FACE_CONF_THRESHOLD", 0.4, float)
    vote_window: int = _env("FACE_VOTE_WINDOW", 15, int)
    mirror_display: bool = _env("FACE_MIRROR_DISPLAY", "1") == "1"


# Severidade por classe (0=normal, 1=leve, 2=forte).
CLASS_SEVERITY = {
    "Normal_Eyes": 0,
    "Normal_Mouth": 0,
    "SlightPalsy_Eyes": 1,
    "SlightPalsy_Mouth": 1,
    "StrongPalsy_Eyes": 2,
    "StrongPalsy_Mouth": 2,
}
SEVERITY_LABEL = {0: "Normal", 1: "Assimetria leve", 2: "Assimetria forte"}
SEVERITY_COLOR = {0: (100, 255, 100), 1: (50, 200, 255), 2: (80, 80, 255)}  # BGR


class FacialAsymmetryEngine:
    def __init__(self, cfg: FacialConfig | None = None):
        self.cfg = cfg or FacialConfig()
        self.model = None

        if YOLO is not None and os.path.exists(self.cfg.model_path):
            self.model = YOLO(self.cfg.model_path)
        else:
            log.warning(
                "Modelo de assimetria facial nao encontrado em '%s' (ou ultralytics ausente). "
                "process_frame() vai apenas exibir o video cru ate o modelo ser adicionado.",
                self.cfg.model_path,
            )

        self.reset()

    def reset(self):
        self.votes: "collections.deque[int]" = collections.deque(maxlen=self.cfg.vote_window)
        self.severity = 0
        self.severity_label = SEVERITY_LABEL[0]
        self.detections: list[tuple[str, float, int]] = []

    def process_frame(self, frame_raw):
        """Recebe 1 frame BGR cru da webcam, devolve o frame anotado (BGR)."""
        cfg = self.cfg
        h, w = frame_raw.shape[:2]
        display_frame = cv2.flip(frame_raw, 1) if cfg.mirror_display else frame_raw.copy()

        if self.model is None:
            draw_ui_element(display_frame, "MODELO NAO CARREGADO (models/facial_asymmetry_best.pt ausente)",
                             (20, 30), font_scale=0.5, text_color=(200, 200, 255),
                             bg_color=(60, 20, 20), thickness=2)
            return display_frame

        results = self.model.predict(frame_raw, verbose=False, conf=cfg.conf_threshold)
        r = results[0]

        frame_severity = 0
        self.detections = []

        if r.boxes is not None and len(r.boxes) > 0:
            for box in r.boxes:
                cls_idx = int(box.cls[0])
                class_name = r.names.get(cls_idx, str(cls_idx))
                conf = float(box.conf[0])
                severity = CLASS_SEVERITY.get(class_name, 0)
                frame_severity = max(frame_severity, severity)
                self.detections.append((class_name, conf, severity))

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                if cfg.mirror_display:
                    x1, x2 = w - x2, w - x1
                color = SEVERITY_COLOR.get(severity, (255, 255, 255))
                cv2.rectangle(display_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                draw_ui_element(display_frame, f"{class_name} {conf:.2f}", (int(x1), max(20, int(y1) - 10)),
                                 font_scale=0.5, text_color=color, bg_color=(20, 20, 20), thickness=1)

        self.votes.append(frame_severity)
        # pior grau observado na janela recente (mais estavel que so o frame atual)
        self.severity = max(self.votes) if self.votes else 0
        self.severity_label = SEVERITY_LABEL[self.severity]

        draw_ui_element(display_frame, f"Status: {self.severity_label}", (20, 30),
                         font_scale=0.7, text_color=SEVERITY_COLOR[self.severity],
                         bg_color=(30, 30, 30), thickness=2)

        return display_frame

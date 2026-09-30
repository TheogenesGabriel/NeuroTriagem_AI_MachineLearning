"""
Motor do Teste do Braco (Arm Drift Test) - NeuroTriagem.AI
------------------------------------------------------------
Refatorado a partir do script standalone original (arm_test_detector_yolo.py).

A diferenca principal: aqui NAO ha loop proprio de captura, nem
cv2.imshow / cv2.waitKey. A classe ArmTestEngine expoe:

    engine.start()                  -> equivalente a apertar 's'
    engine.reset()                  -> equivalente a apertar 'r'
    engine.process_frame(frame_raw) -> processa 1 frame e devolve o
                                        frame anotado (BGR) pronto pra
                                        exibir num QLabel/QImage

Quem chama process_frame() em loop (QTimer, thread, etc.) fica por
conta da tela (screens/arm_test_screen.py). Isso deixa o motor
reutilizavel tanto na versao desktop (PySide6) quanto, no futuro, numa
eventual versao web (so trocar quem fornece o frame e quem le o
resultado).

Mantida a logica original de deteccao de lado (geometria + classe do
YOLO), inclusive o parametro invert_side e o ajuste de espelhamento
(inferencia sempre no frame cru, espelhamento so na exibicao).
"""

from __future__ import annotations

import collections
import logging
import os
import time
from dataclasses import dataclass

import cv2

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - ambiente de dev sem ultralytics ainda
    YOLO = None

log = logging.getLogger("arm_test")


def _env(name: str, default, cast=str):
    val = os.environ.get(name)
    return cast(val) if val is not None else default


@dataclass
class Config:
    camera_index: int = _env("ARM_CAMERA_INDEX", 0, int)
    model_path: str = _env("ARM_MODEL_PATH", "models/best.pt")
    conf_threshold: float = _env("ARM_CONF_THRESHOLD", 0.4, float)
    kpt_conf_threshold: float = _env("ARM_KPT_CONF_THRESHOLD", 0.1, float)

    test_duration_s: float = _env("ARM_TEST_DURATION_S", 20.0, float)
    drift_grace_s: float = _env("ARM_DRIFT_GRACE_S", 1.0, float)

    drift_ratio_threshold: float = _env("ARM_DRIFT_RATIO_THRESHOLD", 0.6, float)
    class_conf_threshold: float = _env("ARM_CLASS_CONF_THRESHOLD", 0.5, float)

    invert_side: bool = _env("ARM_INVERT_SIDE", "1") == "1"
    raised_margin: float = _env("ARM_RAISED_MARGIN", 0.25, float)
    both_down_margin: float = _env("ARM_BOTH_DOWN_MARGIN", 0.45, float)
    both_down_pause_s: float = _env("ARM_BOTH_DOWN_PAUSE_S", 0.5, float)
    min_shoulder_width: float = _env("ARM_MIN_SHOULDER_WIDTH", 0.05, float)
    tracking_loss_pause_s: float = _env("ARM_TRACKING_LOSS_PAUSE_S", 0.5, float)
    ema_alpha: float = _env("ARM_EMA_ALPHA", 0.5, float)
    class_vote_window: int = _env("ARM_CLASS_VOTE_WINDOW", 15, int)

    mirror_display: bool = _env("ARM_MIRROR_DISPLAY", "1") == "1"
    show_skeleton: bool = _env("ARM_SHOW_SKELETON", "0") == "1"


# --- Indices do skeleton treinado (Roboflow "arm-test") -------------------
KPT_CABECA = 0
KPT_CORPO = 1
KPT_OMBRO_ESQ = 2
KPT_OMBRO_DIR = 3
KPT_COTOVELO_DIR = 4
KPT_MAO_DIR = 5
KPT_COTOVELO_ESQ = 6
KPT_MAO_ESQ = 7
N_KEYPOINTS = 8

SKELETON_EDGES = [
    (KPT_CABECA, KPT_CORPO),
    (KPT_CORPO, KPT_OMBRO_ESQ),
    (KPT_CORPO, KPT_OMBRO_DIR),
    (KPT_OMBRO_ESQ, KPT_COTOVELO_ESQ),
    (KPT_COTOVELO_ESQ, KPT_MAO_ESQ),
    (KPT_OMBRO_DIR, KPT_COTOVELO_DIR),
    (KPT_COTOVELO_DIR, KPT_MAO_DIR),
]

WEAKNESS_CLASS_SIDE = {
    "fraqueza esquerda": "L",
    "fraqueza_esquerda": "L",
    "fraqueza direita": "R",
    "fraqueza_direita": "R",
}


class ArmTestState:
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    RESULT = "RESULT"


# --- Funcoes puras reaproveitadas do script original -----------------------
def extract_pose(result, cfg: Config):
    if result.keypoints is None or result.boxes is None or len(result.boxes) == 0:
        return None, None, None

    best_idx = int(result.boxes.conf.argmax())
    box_conf = float(result.boxes.conf[best_idx])
    if box_conf < cfg.conf_threshold:
        return None, None, None

    cls_idx = int(result.boxes.cls[best_idx])
    class_name = result.names.get(cls_idx, str(cls_idx))

    kpts_xyn = result.keypoints.xyn[best_idx].cpu().numpy()
    kpts_conf = (
        result.keypoints.conf[best_idx].cpu().numpy() if result.keypoints.conf is not None else None
    )

    kxy = {}
    for i in range(kpts_xyn.shape[0]):
        conf = float(kpts_conf[i]) if kpts_conf is not None else 1.0
        if conf >= cfg.kpt_conf_threshold:
            kxy[i] = (float(kpts_xyn[i][0]), float(kpts_xyn[i][1]))

    return kxy, class_name, box_conf


def determine_weak_side(ratio, lower_side, class_name, class_conf, cfg: Config):
    geo_side = lower_side if (ratio is not None and ratio > cfg.drift_ratio_threshold) else None

    cls_side = None
    if class_name is not None and class_conf is not None and class_conf >= cfg.class_conf_threshold:
        cls_side = WEAKNESS_CLASS_SIDE.get(class_name)

    if cfg.invert_side:
        inverte = {"L": "R", "R": "L", None: None}
        geo_side = inverte[geo_side]
        cls_side = inverte[cls_side]

    if geo_side is not None and cls_side is not None:
        return geo_side if geo_side == cls_side else None
    if geo_side is not None:
        return geo_side
    if cls_side is not None:
        return cls_side
    return None


def draw_ui_element(img, text, pos, font_scale=0.6, text_color=(255, 255, 255),
                     bg_color=(0, 0, 0), alpha=0.6, thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size, baseline = cv2.getTextSize(text, font, font_scale, thickness)

    x, y = pos
    pad_x, pad_y = 12, 10

    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(img.shape[1], x + text_size[0] + pad_x)
    y2 = min(img.shape[0], y + text_size[1] + baseline + pad_y)

    roi = img[y1:y2, x1:x2]
    if roi.size > 0:
        overlay = roi.copy()
        cv2.rectangle(overlay, (0, 0), (overlay.shape[1], overlay.shape[0]), bg_color, -1)
        cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)

    cv2.putText(img, text, (x, y + text_size[1]), font, font_scale, text_color, thickness, cv2.LINE_AA)


def draw_skeleton(frame, kxy, h, w, mirror: bool) -> None:
    def to_px(pt):
        x, y = pt
        if mirror:
            x = 1.0 - x
        return int(x * w), int(y * h)

    for a, b in SKELETON_EDGES:
        if a in kxy and b in kxy:
            cv2.line(frame, to_px(kxy[a]), to_px(kxy[b]), (0, 220, 100), 2, cv2.LINE_AA)

    for _idx, pt in kxy.items():
        center = to_px(pt)
        cv2.circle(frame, center, 5, (0, 150, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, center, 2, (255, 255, 255), -1, cv2.LINE_AA)


def pick_device() -> str:
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# --- Motor do teste (sem I/O de camera/janela) -----------------------------
class ArmTestEngine:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.model = None
        self.device = pick_device()

        if YOLO is not None and os.path.exists(self.cfg.model_path):
            self.model = YOLO(self.cfg.model_path)
        else:
            log.warning(
                "Modelo do teste do braco nao encontrado em '%s' (ou ultralytics ausente). "
                "process_frame() vai apenas exibir o video cru ate o modelo ser adicionado.",
                self.cfg.model_path,
            )

        self.reset()

    # -- controle externo (chamado pela tela) --
    def start(self):
        if self.state == ArmTestState.IDLE:
            self.state = ArmTestState.ACTIVE
            self.active_accum = 0.0
            self.last_frame_time = time.time()
            self.drift_side = None
            self.drift_start_accum = None
            self.both_down_since = None
            self.class_votes.clear()

    def reset(self):
        self.state = ArmTestState.IDLE
        self.active_accum = 0.0
        self.last_frame_time = None
        self.drift_side = None
        self.drift_start_accum = None
        self.result_text = None
        self.result_color = (255, 255, 255)
        self.lost_tracking_since = None
        self.both_down_since = None
        self.smoothed_diff = None
        self.class_votes: "collections.deque[str]" = collections.deque(maxlen=self.cfg.class_vote_window)

        # ultimo frame processado (exposto pra tela mostrar na UI)
        self.ratio = None
        self.lower_side = None
        self.weak_side = None
        self.class_name = None
        self.class_conf = None
        self.remaining_seconds = int(self.cfg.test_duration_s)

    # -- processamento por frame --
    def process_frame(self, frame_raw):
        """Recebe 1 frame BGR cru da webcam, devolve o frame anotado (BGR)."""
        cfg = self.cfg
        h, w = frame_raw.shape[:2]

        kxy, class_name, class_conf = None, None, None
        if self.model is not None:
            results = self.model.predict(frame_raw, verbose=False, conf=cfg.conf_threshold, device=self.device)
            kxy, class_name, class_conf = extract_pose(results[0], cfg)

        display_frame = cv2.flip(frame_raw, 1) if cfg.mirror_display else frame_raw.copy()

        if self.model is None:
            draw_ui_element(display_frame, "MODELO NAO CARREGADO (models/best.pt ausente)", (20, 30),
                             font_scale=0.55, text_color=(200, 200, 255), bg_color=(60, 20, 20), thickness=2)
            return display_frame

        arms_raised = False
        both_down = False
        ratio = None
        lower_side = None
        pose_valid = False

        if kxy is not None:
            if cfg.show_skeleton:
                draw_skeleton(display_frame, kxy, h, w, mirror=cfg.mirror_display)
            if class_name is not None:
                self.class_votes.append(class_name)

            l_wr = kxy.get(KPT_MAO_ESQ)
            l_el = kxy.get(KPT_COTOVELO_ESQ)
            r_wr = kxy.get(KPT_MAO_DIR)
            r_el = kxy.get(KPT_COTOVELO_DIR)
            l_sh = kxy.get(KPT_OMBRO_ESQ)
            r_sh = kxy.get(KPT_OMBRO_DIR)

            left_y = l_wr[1] if l_wr is not None else (l_el[1] if l_el is not None else None)
            right_y = r_wr[1] if r_wr is not None else (r_el[1] if r_el is not None else None)

            if left_y is not None and right_y is not None and l_sh is not None and r_sh is not None:
                shoulder_width = abs(r_sh[0] - l_sh[0])
                if shoulder_width > cfg.min_shoulder_width:
                    diff = left_y - right_y

                    if self.smoothed_diff is None or cfg.ema_alpha <= 0:
                        self.smoothed_diff = diff
                    else:
                        self.smoothed_diff = cfg.ema_alpha * diff + (1 - cfg.ema_alpha) * self.smoothed_diff

                    ratio = abs(self.smoothed_diff) / shoulder_width
                    lower_side = "L" if self.smoothed_diff > 0 else "R"

                    shoulder_y = (l_sh[1] + r_sh[1]) / 2.0
                    arms_raised = (left_y < shoulder_y + cfg.raised_margin) and (
                            right_y < shoulder_y + cfg.raised_margin
                    )
                    both_down = (left_y > shoulder_y + cfg.both_down_margin) and (
                            right_y > shoulder_y + cfg.both_down_margin
                    )
                    pose_valid = True

        weak_side = determine_weak_side(ratio, lower_side, class_name, class_conf, cfg)
        now = time.time()

        # expõe pra UI ler
        self.ratio, self.lower_side, self.weak_side = ratio, lower_side, weak_side
        self.class_name, self.class_conf = class_name, class_conf

        if self.state == ArmTestState.IDLE:
            draw_ui_element(display_frame, "LEVANTE OS BRACOS E CLIQUE EM 'INICIAR'", (20, 30),
                             font_scale=0.6, text_color=(255, 255, 255), bg_color=(120, 50, 50), thickness=2)

        elif self.state == ArmTestState.ACTIVE:
            if self.last_frame_time is None:
                self.last_frame_time = now
            dt = now - self.last_frame_time
            self.last_frame_time = now

            paused_both_down = False
            if pose_valid:
                self.lost_tracking_since = None
                if both_down:
                    self.both_down_since = self.both_down_since or now
                    paused_both_down = (now - self.both_down_since) >= cfg.both_down_pause_s
                else:
                    self.both_down_since = None

                if paused_both_down:
                    if self.drift_side is not None:
                        self.drift_side = None
                        self.drift_start_accum = None
                    draw_ui_element(display_frame, "LEVANTE OS BRACOS - TESTE PAUSADO", (20, 80),
                                     font_scale=0.6, text_color=(50, 50, 255), bg_color=(20, 20, 40), thickness=2)
                else:
                    self.active_accum += dt
            else:
                self.both_down_since = None
                self.lost_tracking_since = self.lost_tracking_since or now
                if now - self.lost_tracking_since >= cfg.tracking_loss_pause_s:
                    draw_ui_element(display_frame, "POSICIONE-SE NA CAMERA - TESTE PAUSADO", (20, 80),
                                     font_scale=0.6, text_color=(50, 50, 255), bg_color=(20, 20, 40), thickness=2)

            self.remaining_seconds = max(0, int(cfg.test_duration_s - self.active_accum))

            if pose_valid and not paused_both_down:
                if weak_side is not None:
                    if self.drift_side != weak_side:
                        self.drift_side = weak_side
                        self.drift_start_accum = self.active_accum
                    elif self.active_accum - self.drift_start_accum >= cfg.drift_grace_s:
                        self.state = ArmTestState.RESULT
                        if self.drift_side == "L":
                            self.result_text, self.result_color = "FRAQUEZA - BRACO ESQUERDO", (140, 125, 255)
                        else:
                            self.result_text, self.result_color = "FRAQUEZA - BRACO DIREITO", (140, 125, 255)
                else:
                    if self.drift_side is not None:
                        self.drift_side = None
                        self.drift_start_accum = None

            if self.state == ArmTestState.ACTIVE and self.active_accum >= cfg.test_duration_s:
                self.state = ArmTestState.RESULT
                self.result_text, self.result_color = "TESTE NORMAL - BRACOS OK", (100, 255, 100)

            draw_ui_element(display_frame, f"TESTE: {self.remaining_seconds:02d}s", (20, 30),
                             font_scale=0.8, text_color=(150, 255, 150), bg_color=(20, 60, 20), thickness=2)

            if self.drift_side is not None and self.drift_start_accum is not None:
                warn_remaining = max(0.0, cfg.drift_grace_s - (self.active_accum - self.drift_start_accum))
                draw_ui_element(display_frame,
                                 f"CORRIJA! {warn_remaining:0.1f}s ({'ESQ' if self.drift_side == 'L' else 'DIR'})",
                                 (20, 80), font_scale=0.7, text_color=(50, 150, 255), bg_color=(20, 40, 80),
                                 thickness=2)

        elif self.state == ArmTestState.RESULT:
            draw_ui_element(display_frame, self.result_text or "", (20, 30),
                             font_scale=0.7, text_color=self.result_color, bg_color=(40, 40, 40), thickness=2)
            draw_ui_element(display_frame, "Clique em 'Reiniciar' para um novo teste", (20, 80),
                             font_scale=0.5, text_color=(200, 200, 200), bg_color=(20, 20, 20), thickness=1)

        telemetry_parts = []
        if ratio is not None:
            telemetry_parts.append(f"Ratio: {ratio:.2f} | Lado: {lower_side} | Erguidos: {arms_raised}")
        if class_name is not None:
            telemetry_parts.append(f"Classe: {class_name} ({class_conf:.2f})")
        if telemetry_parts:
            draw_ui_element(display_frame, " | ".join(telemetry_parts), (15, h - 35),
                             font_scale=0.45, text_color=(0, 255, 255), bg_color=(15, 15, 15), alpha=0.8,
                             thickness=1)

        return display_frame

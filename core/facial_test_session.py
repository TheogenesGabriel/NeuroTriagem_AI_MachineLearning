"""Janela temporal do teste facial, independente da câmera e da inferência.

Os graus são categorias operacionais do detector. O resultado resume o maior
grau observado durante a janela completa; não representa diagnóstico de AVC.
"""

from __future__ import annotations

import math
import time
from numbers import Integral
from typing import Callable


class FacialTestState:
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    RESULT = "RESULT"


FACIAL_RESULT_LABELS = {
    0: "Normal",
    1: "Atenção — assimetria leve",
    2: "Alerta — assimetria alta",
}


class FacialTestSession:
    """Captura manual, com prazo monotônico e resultado congelado.

    ``record_frame(None)`` registra um frame processado sem observação válida.
    ``tick()`` verifica apenas o prazo, inclusive quando a câmera não fornece
    frames. A tela deve chamar ambos conforme os eventos de câmera e relógio.
    """

    def __init__(self, duration_s: float = 20.0, *, clock: Callable[[], float] | None = None):
        self.duration_s = self._validate_duration(duration_s)
        self._clock = clock if clock is not None else time.monotonic
        self.reset()

    @staticmethod
    def _validate_duration(duration_s: float) -> float:
        if isinstance(duration_s, bool):
            raise ValueError("A duração deve ser um número positivo e finito.")
        try:
            duration = float(duration_s)
        except (TypeError, ValueError):
            raise ValueError("A duração deve ser um número positivo e finito.") from None
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("A duração deve ser um número positivo e finito.")
        return duration

    def reset(self) -> None:
        """Cancela a captura e descarta qualquer resultado da sessão anterior."""
        self.state = FacialTestState.IDLE
        self.total_frames = 0
        self.valid_frames = 0
        self._started_at: float | None = None
        self._deadline: float | None = None
        self._peak_severity: int | None = None
        self._result_severity: int | None = None

    def start(self, duration_s: float | None = None) -> None:
        """Inicia ou reinicia a janela, sem aproveitar a prévia da câmera."""
        duration = self.duration_s if duration_s is None else self._validate_duration(duration_s)
        started_at = self._clock()
        self.reset()
        self.duration_s = duration
        self._started_at = started_at
        self._deadline = started_at + duration
        self.state = FacialTestState.ACTIVE

    def tick(self) -> str:
        """Conclui no prazo mesmo se nenhum frame tiver sido recebido."""
        if self.state == FacialTestState.ACTIVE and self._clock() >= self._deadline:
            self._result_severity = self._peak_severity
            self.state = FacialTestState.RESULT
        return self.state

    def record_frame(self, frame_severity: int | None) -> None:
        """Registra somente o grau bruto do frame dentro da janela ativa.

        Frames processados no prazo final ou depois dele são ignorados. Isso
        também impede que uma inferência lenta prolongue a duração do teste.
        """
        if self.tick() != FacialTestState.ACTIVE:
            return
        if frame_severity is not None and (
            isinstance(frame_severity, bool)
            or not isinstance(frame_severity, Integral)
            or frame_severity not in (0, 1, 2)
        ):
            raise ValueError("O grau do frame deve ser 0, 1, 2 ou None.")
        self.total_frames += 1
        if frame_severity is not None:
            severity = int(frame_severity)
            self.valid_frames += 1
            self._peak_severity = severity if self._peak_severity is None else max(self._peak_severity, severity)

    @property
    def remaining_seconds(self) -> int:
        self.tick()
        if self.state == FacialTestState.RESULT:
            return 0
        if self.state == FacialTestState.IDLE:
            return math.ceil(self.duration_s)
        return math.ceil(max(0.0, self._deadline - self._clock()))

    @property
    def result_severity(self) -> int | None:
        self.tick()
        return self._result_severity

    @property
    def result_label(self) -> str:
        self.tick()
        if self.state == FacialTestState.IDLE:
            return "Teste não iniciado"
        if self.state == FacialTestState.ACTIVE:
            return "Teste em andamento"
        return FACIAL_RESULT_LABELS.get(self._result_severity, "Sem observação válida")

    def get_features(self) -> dict[str, int | None]:
        """Somente uma sessão concluída pode fornecer o atributo ao modelo."""
        self.tick()
        return {"facial_asymmetry_score": self._result_severity}

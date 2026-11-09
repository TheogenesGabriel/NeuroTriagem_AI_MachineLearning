"""Prévia da câmera e captura facial com início manual e prazo definido."""

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core.facial_asymmetry_logic import FacialAsymmetryEngine
from core.facial_test_session import FacialTestSession, FacialTestState


class FacialAsymmetryScreen(QWidget):
    """A prévia é contínua; só a janela iniciada pelo usuário alimenta o RF."""

    def __init__(self, on_next, on_back):
        super().__init__()
        self._on_next = on_next
        self._on_back = on_back
        self.engine = FacialAsymmetryEngine()
        self.session = FacialTestSession()
        self.cap = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)
        # O prazo também avança quando a câmera deixa de fornecer frames.
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(100)
        self.session_timer.timeout.connect(self._update_session)

        layout = QVBoxLayout(self)
        title = QLabel("Teste de assimetria facial")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        instructions = QLabel(
            "Posicione o rosto na câmera, escolha a duração e clique em Iniciar teste. "
            "O resultado considera o maior grau de assimetria observado durante a captura."
        )
        instructions.setWordWrap(True)
        instructions.setAlignment(Qt.AlignCenter)
        layout.addWidget(instructions)

        controls = QHBoxLayout()
        duration_label = QLabel("Duração:")
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 60)
        self.duration_spin.setValue(20)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setAccessibleName("Duração do teste facial em segundos")
        self.duration_spin.valueChanged.connect(self._duration_changed)
        duration_label.setBuddy(self.duration_spin)
        self.start_btn = QPushButton("Iniciar teste")
        self.start_btn.clicked.connect(self._start_test)
        self.restart_btn = QPushButton("Reiniciar teste")
        self.restart_btn.clicked.connect(self._restart_test)
        self.restart_btn.setToolTip("Descarta a captura anterior e inicia uma nova janela de tempo.")
        controls.addWidget(duration_label)
        controls.addWidget(self.duration_spin)
        controls.addStretch()
        controls.addWidget(self.start_btn)
        controls.addWidget(self.restart_btn)
        layout.addLayout(controls)

        timing = QHBoxLayout()
        self.countdown_label = QLabel()
        self.countdown_label.setMinimumWidth(170)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName("Progresso do teste facial")
        timing.addWidget(self.countdown_label)
        timing.addWidget(self.progress_bar)
        layout.addLayout(timing)

        self.video_label = QLabel("Câmera não iniciada")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 360)
        self.video_label.setStyleSheet("background-color: #111; color: #bbb;")
        layout.addWidget(self.video_label, 1)

        self.preview_label = QLabel("Prévia da câmera indisponível.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            "font-size: 17px; font-weight: bold; padding: 8px; "
            "background-color: #eaf1f8; color: #172f48; border-radius: 5px;"
        )
        layout.addWidget(self.result_label)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        nav = QHBoxLayout()
        self.back_btn = QPushButton("Voltar")
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn = QPushButton()
        self.next_btn.clicked.connect(self._go_next)
        nav.addWidget(self.back_btn)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)
        self._refresh_session_ui()

    def _capture_ready(self):
        return self.cap is not None and self.cap.isOpened() and self.engine.model is not None

    def start_camera(self):
        self.stop_camera()
        self.engine.reset()
        self.session.reset()
        self.session.duration_s = float(self.duration_spin.value())
        self.video_label.clear()
        self.cap = cv2.VideoCapture(self.engine.cfg.camera_index)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            self.video_label.setText("Câmera indisponível")
            self.preview_label.setText("Não foi possível abrir a câmera. Você pode prosseguir sem o teste facial.")
        else:
            self.video_label.setText("Abrindo prévia da câmera…")
            self.preview_label.setText(
                "Modelo facial indisponível; a câmera mostra apenas a prévia."
                if self.engine.model is None else "Prévia da câmera — aguardando observações."
            )
            self.timer.start(1000 // 15)
        self._refresh_session_ui()

    def stop_camera(self):
        self.timer.stop()
        self.session_timer.stop()
        # Cancelar uma sessão em andamento nunca produz um resultado parcial.
        # Um resultado já concluído permanece disponível para a próxima etapa.
        self.session.tick()
        if self.session.state == FacialTestState.ACTIVE:
            self.session.reset()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self._refresh_session_ui()

    def get_features(self) -> dict:
        return self.session.get_features()

    def _duration_changed(self, value):
        if self.session.state == FacialTestState.IDLE:
            self.session.duration_s = float(value)
            self._refresh_session_ui()

    def _start_test(self):
        if self.session.state != FacialTestState.IDLE or not self._capture_ready():
            return
        self._begin_capture()

    def _restart_test(self):
        if self.session.state == FacialTestState.IDLE or not self._capture_ready():
            return
        self._begin_capture()

    def _begin_capture(self):
        self.engine.reset()
        self.session.start(self.duration_spin.value())
        self.preview_label.setText("Captura iniciada — aguardando observações do rosto.")
        self.session_timer.start()
        self._refresh_session_ui()

    def _update_session(self):
        self.session.tick()
        self._refresh_session_ui()

    def _refresh_session_ui(self):
        remaining = self.session.remaining_seconds
        state = self.session.state
        active = state == FacialTestState.ACTIVE
        complete = state == FacialTestState.RESULT
        ready = self._capture_ready()
        duration = int(self.session.duration_s)
        self.duration_spin.setEnabled(not active)
        self.start_btn.setEnabled(ready and state == FacialTestState.IDLE)
        self.restart_btn.setEnabled(ready and state != FacialTestState.IDLE)
        self.next_btn.setEnabled(not active)
        self.progress_bar.setRange(0, duration)
        self.progress_bar.setValue(duration - remaining)

        if active:
            self.countdown_label.setText(f"Tempo restante: {remaining} s")
            self.result_label.setText("Teste em andamento — coletando observações")
            self.status_label.setText(
                f"Frames com observação válida: {self.session.valid_frames} de {self.session.total_frames}. "
                "Reiniciar descarta a captura atual e começa novamente."
            )
            self.next_btn.setText("Aguarde a conclusão do teste")
        elif complete:
            self.session_timer.stop()
            self.countdown_label.setText(f"Concluído em {duration} s")
            self.result_label.setText("Resultado do teste facial: " + self.session.result_label)
            if self.session.valid_frames:
                self.status_label.setText(
                    f"Resultado preservado · {self.session.valid_frames} de {self.session.total_frames} "
                    "frames com observação válida. Classificação de assimetria do protótipo."
                )
                self.next_btn.setText("Prosseguir para teste do braço")
            else:
                self.status_label.setText(
                    "Nenhuma observação válida durante a captura. Reinicie o teste ou prossiga sem resultado facial."
                )
                self.next_btn.setText("Prosseguir sem resultado facial")
        else:
            self.countdown_label.setText(f"Janela de captura: {duration} s")
            self.result_label.setText("Resultado do teste facial: aguardando início")
            self.status_label.setText("A prévia não entra na classificação. Clique em Iniciar teste para capturar.")
            self.next_btn.setText("Prosseguir sem teste facial")

    def _update_frame(self):
        self.session.tick()
        if self.cap is None:
            self._refresh_session_ui()
            return
        ok, frame = self.cap.read()
        if not ok:
            self.preview_label.setText(
                "Sem novos frames da câmera. O prazo do teste continua contando."
                if self.session.state == FacialTestState.ACTIVE else "Sem novos frames da câmera."
            )
            self._refresh_session_ui()
            return

        annotated = self.engine.process_frame(frame)
        # O motor mantém votos para a prévia; a sessão recebe o grau bruto.
        # record_frame verifica o prazo após a inferência e ignora frames tardios.
        self.session.record_frame(self.engine.frame_severity)
        if self.engine.model is None:
            self.preview_label.setText("Modelo facial indisponível; a câmera mostra apenas a prévia.")
        else:
            self.preview_label.setText("Prévia ao vivo: " + self.engine.severity_label)
        self._show_frame(annotated)
        self._refresh_session_ui()

    def _show_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.video_label.setPixmap(
            QPixmap.fromImage(qimg).scaled(self.video_label.width(), self.video_label.height(), Qt.KeepAspectRatio)
        )

    def _go_next(self):
        if self.session.tick() == FacialTestState.ACTIVE:
            return
        self.stop_camera()
        self._on_next()

    def _go_back(self):
        self.stop_camera()
        self._on_back()

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)

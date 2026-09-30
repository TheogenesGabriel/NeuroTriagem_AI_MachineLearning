import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.arm_test_logic import ArmTestEngine, ArmTestState


class ArmTestScreen(QWidget):
    """
    3a tela: teste do braco por webcam (YOLOv8-pose). Nao e mais a
    ultima tela do fluxo - so navega pra frente, pro teste do
    joystick (4a tela), que e quem aciona o Random Forest no final.
    """

    def __init__(self, on_next):
        super().__init__()
        self._on_next = on_next

        self.engine = ArmTestEngine()

        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_frame)

        layout = QVBoxLayout(self)

        title = QLabel("Teste do Braco (Arm Drift Test)")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        self.video_label = QLabel("Camera nao iniciada")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setStyleSheet("background-color: #111; color: #888;")
        layout.addWidget(self.video_label)

        self.status_label = QLabel("Levante os bracos e clique em Iniciar")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.status_label)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Iniciar Teste")
        self.start_btn.clicked.connect(self._start_test)
        self.reset_btn = QPushButton("Reiniciar")
        self.reset_btn.clicked.connect(self._reset_test)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.reset_btn)
        layout.addLayout(controls)

        nav = QHBoxLayout()
        next_btn = QPushButton("Prosseguir para Teste do Joystick")
        next_btn.clicked.connect(self._go_next)
        nav.addStretch()
        nav.addWidget(next_btn)
        layout.addLayout(nav)

    def start_camera(self):
        self.cap = cv2.VideoCapture(self.engine.cfg.camera_index)
        self.timer.start(1000 // 15)  # ~15 fps de UI (inferencia real pode ser mais lenta em CPU)

    def stop_camera(self):
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def _start_test(self):
        self.engine.start()

    def _reset_test(self):
        self.engine.reset()
        self.status_label.setText("Levante os bracos e clique em Iniciar")

    def _update_frame(self):
        if self.cap is None:
            return
        ok, frame = self.cap.read()
        if not ok:
            return

        annotated = self.engine.process_frame(frame)
        self._update_status_label()
        self._show_frame(annotated)

    def _update_status_label(self):
        e = self.engine
        if e.state == ArmTestState.IDLE:
            self.status_label.setText("Levante os bracos e clique em Iniciar")
        elif e.state == ArmTestState.ACTIVE:
            texto = f"Testando... {e.remaining_seconds}s restantes"
            if e.ratio is not None:
                texto += f" | ratio={e.ratio:.2f} lado={e.lower_side}"
            self.status_label.setText(texto)
        elif e.state == ArmTestState.RESULT:
            self.status_label.setText(e.result_text or "Teste concluido")

    def _show_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.video_label.setPixmap(
            QPixmap.fromImage(qimg).scaled(self.video_label.width(), self.video_label.height(), Qt.KeepAspectRatio)
        )

    def _go_next(self):
        self.stop_camera()
        self._on_next()
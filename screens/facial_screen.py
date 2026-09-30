import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.facial_asymmetry_logic import FacialAsymmetryEngine


class FacialAsymmetryScreen(QWidget):
    """
    Tela de deteccao de assimetria facial.

    Usa core/facial_asymmetry_logic.py (YOLOv8 de deteccao, 6 classes:
    Normal/SlightPalsy/StrongPalsy x Eyes/Mouth). Coloque o checkpoint
    treinado em models/facial_asymmetry_best.pt.
    """

    def __init__(self, on_next, on_back):
        super().__init__()
        self._on_next = on_next
        self._on_back = on_back

        self.engine = FacialAsymmetryEngine()
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_frame)

        layout = QVBoxLayout(self)

        title = QLabel("Deteccao de Assimetria Facial")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        self.video_label = QLabel("Camera nao iniciada")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setStyleSheet("background-color: #111; color: #888;")
        layout.addWidget(self.video_label)

        self.status_label = QLabel("Aguardando...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.status_label)

        nav = QHBoxLayout()
        back_btn = QPushButton("Voltar")
        back_btn.clicked.connect(self._go_back)
        next_btn = QPushButton("Prosseguir para Teste do Braco")
        next_btn.clicked.connect(self._go_next)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(next_btn)
        layout.addLayout(nav)

    def start_camera(self):
        self.engine.reset()
        self.cap = cv2.VideoCapture(self.engine.cfg.camera_index)
        self.timer.start(1000 // 15)  # ~15 fps de UI (inferencia real pode ser mais lenta em CPU)

    def stop_camera(self):
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def _update_frame(self):
        if self.cap is None:
            return
        ok, frame = self.cap.read()
        if not ok:
            return

        annotated = self.engine.process_frame(frame)
        self.status_label.setText(f"Status: {self.engine.severity_label}")
        self._show_frame(annotated)

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

    def _go_back(self):
        self.stop_camera()
        self._on_back()

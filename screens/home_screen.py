from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class HomeScreen(QWidget):
    """Tela inicial - so titulo, subtitulo e botao pra iniciar a triagem."""

    def __init__(self, on_start):
        super().__init__()
        self._on_start = on_start

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("NeuroTriagem.AI")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 42px; font-weight: bold;")

        subtitle = QLabel("Triagem neurologica assistida - assimetria facial e teste do braco")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 16px; color: #666;")

        start_btn = QPushButton("Iniciar Triagem")
        start_btn.setFixedWidth(220)
        start_btn.setStyleSheet("font-size: 16px; padding: 10px;")
        start_btn.clicked.connect(self._on_start)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(30)
        layout.addWidget(start_btn, alignment=Qt.AlignCenter)

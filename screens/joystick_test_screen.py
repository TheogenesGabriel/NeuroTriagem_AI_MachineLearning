import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.bitdoglab_serial_client import JoystickTestSerialReader
from core.random_forest_model import RiscoRandomForest

# Mapeia o nome da direcao que vem do firmware (teste_avc.c) pra posicao
# no grid 3x3 da seta (linha, coluna).
_DIRECAO_GRID = {
    "CIMA": (0, 1),
    "ESQUERDA": (1, 0),
    "DIREITA": (1, 2),
    "BAIXO": (2, 1),
}
_SETA_TEXTO = {
    "CIMA": "\u2191",
    "ESQUERDA": "\u2190",
    "DIREITA": "\u2192",
    "BAIXO": "\u2193",
}

_COR_INATIVA = "#333"
_COR_ATIVA_A = "#2a8f2a"   # verde - "segurando" (frame 1 do pulso)
_COR_ATIVA_B = "#3fd63f"   # verde mais claro (frame 2 do pulso)
_COR_AGUARDANDO = "#1f5fbf"  # azul - direcao pedida, ainda nao alcancou o limiar


def _default_serial_port() -> str:
    env = os.environ.get("BITDOGLAB_SERIAL_PORT")
    if env:
        return env
    if sys.platform.startswith("win"):
        return "COM5"
    if sys.platform == "darwin":
        return "/dev/tty.usbmodem0000"
    return "/dev/ttyACM0"


class JoystickTestScreen(QWidget):
    """
    4a tela: teste de forca via joystick da BitDogLab (firmware
    teste_avc_joystick). Esse firmware roda isolado na placa - o
    Botao A nela inicia o teste fisicamente - e nao tem Wi-Fi/rede
    nenhuma (ver [[bitdoglab-firmware]]), entao aqui a gente so LE o
    resultado pela porta serial USB (ver core/bitdoglab_serial_client.py)
    e anima uma seta 3x3 mostrando pra qual direcao o joystick deveria
    estar apontando no momento.
    """

    def __init__(self, on_finish, bitdoglab=None, facial_screen=None, arm_test_screen=None):
        super().__init__()
        self._on_finish = on_finish
        self._bitdoglab = bitdoglab
        self._facial_screen = facial_screen
        self._arm_test_screen = arm_test_screen

        self.reader: JoystickTestSerialReader | None = None
        self.risco_model = RiscoRandomForest()
        self._ultimo_resultado: dict | None = None

        # -- estado da animacao --
        self._direcao_ativa: str | None = None
        self._segurando = False  # True enquanto o limiar esta sendo mantido (pulsa)
        self._pulso_aceso = False
        self._arrow_labels: dict[str, QLabel] = {}

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(400)
        self._pulse_timer.timeout.connect(self._tick_pulso)
        self._pulse_timer.start()

        layout = QVBoxLayout(self)

        title = QLabel("Teste do Joystick (BitDogLab)")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        info = QLabel(
            "Aperte o Botao A na BitDogLab para iniciar o teste fisico. "
            "A seta abaixo acende na direcao pedida - azul enquanto tenta "
            "alcancar, verde pulsando enquanto segura os 10s."
        )
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(self._build_arrow_pad())

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Porta serial:"))
        self.port_input = QLineEdit(_default_serial_port())
        port_row.addWidget(self.port_input)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self._toggle_connection)
        port_row.addWidget(self.connect_btn)
        layout.addLayout(port_row)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.log_view.setStyleSheet("background-color: #111; color: #0f0; font-family: monospace;")
        layout.addWidget(self.log_view)

        self.status_label = QLabel("Desconectado")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.status_label)

        nav = QHBoxLayout()
        finish_btn = QPushButton("Concluir Triagem")
        finish_btn.clicked.connect(self._finish)
        nav.addStretch()
        nav.addWidget(finish_btn)
        layout.addLayout(nav)

    # -- montagem da seta 3x3 --
    def _build_arrow_pad(self) -> QWidget:
        pad = QWidget()
        grid = QGridLayout(pad)
        grid.setSpacing(6)

        for direcao, (linha, coluna) in _DIRECAO_GRID.items():
            lbl = QLabel(_SETA_TEXTO[direcao])
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(70, 70)
            lbl.setStyleSheet(self._estilo_seta(_COR_INATIVA))
            grid.addWidget(lbl, linha, coluna)
            self._arrow_labels[direcao] = lbl

        centro = QLabel("\u25CF")
        centro.setAlignment(Qt.AlignCenter)
        centro.setFixedSize(70, 70)
        centro.setStyleSheet(self._estilo_seta("#222", tamanho_fonte=18))
        grid.addWidget(centro, 1, 1)

        wrapper = QWidget()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.addStretch()
        wrapper_layout.addWidget(pad)
        wrapper_layout.addStretch()
        return wrapper

    @staticmethod
    def _estilo_seta(cor_fundo: str, tamanho_fonte: int = 28) -> str:
        return (
            f"background-color: {cor_fundo}; color: white; border-radius: 8px; "
            f"font-size: {tamanho_fonte}px; font-weight: bold;"
        )

    def _tick_pulso(self):
        if not self._segurando or self._direcao_ativa is None:
            return
        self._pulso_aceso = not self._pulso_aceso
        cor = _COR_ATIVA_B if self._pulso_aceso else _COR_ATIVA_A
        lbl = self._arrow_labels.get(self._direcao_ativa)
        if lbl is not None:
            lbl.setStyleSheet(self._estilo_seta(cor))

    def _atualizar_seta(self, direcao_atual: str | None, segurando: bool):
        # apaga a seta anterior se mudou de direcao
        if self._direcao_ativa is not None and self._direcao_ativa != direcao_atual:
            lbl_antiga = self._arrow_labels.get(self._direcao_ativa)
            if lbl_antiga is not None:
                lbl_antiga.setStyleSheet(self._estilo_seta(_COR_INATIVA))

        self._direcao_ativa = direcao_atual
        self._segurando = segurando

        if direcao_atual is None:
            return

        lbl = self._arrow_labels.get(direcao_atual)
        if lbl is None:
            return
        lbl.setStyleSheet(self._estilo_seta(_COR_ATIVA_A if segurando else _COR_AGUARDANDO))

    # -- chamado pelo MainWindow ao entrar/sair da tela --
    def enter_screen(self):
        pass  # a conexao serial aqui e manual (botao "Conectar"), nao automatica

    def leave_screen(self):
        self._disconnect()

    # -- conexao serial --
    def _toggle_connection(self):
        if self.reader is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self):
        port = self.port_input.text().strip()
        if not port:
            QMessageBox.warning(self, "Porta serial", "Informe a porta serial (ex.: COM5 ou /dev/ttyACM0).")
            return

        self.log_view.clear()
        self._ultimo_resultado = None
        self._atualizar_seta(None, False)
        self.reader = JoystickTestSerialReader(port=port, on_line=self._on_line, on_result=self._on_result)
        self.reader.start()
        self.connect_btn.setText("Desconectar")
        self.status_label.setText("Conectado - aperte o Botao A na placa para iniciar")

    def _disconnect(self):
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        self.connect_btn.setText("Conectar")
        self.status_label.setText("Desconectado")
        self._atualizar_seta(None, False)

    # -- callbacks da thread serial --
    # NOTA: por simplicidade este scaffold atualiza widgets Qt direto
    # dessas callbacks (chamadas de outra thread). Pra uma versao mais
    # robusta, troque por sinais Qt (Signal/Slot) em vez de chamada
    # direta, que e a forma "oficialmente" thread-safe no Qt.
    def _on_line(self, linha: str):
        self.log_view.append(linha)

    def _on_result(self, resultado: dict):
        self._ultimo_resultado = resultado

        direcao_atual = resultado.get("direcao_atual")
        segundos = resultado.get("segundos_restantes")
        self._atualizar_seta(direcao_atual, segurando=segundos is not None)

        geral = resultado.get("resultado_geral")
        if geral:
            self.status_label.setText(f"Resultado: {geral}")
        elif direcao_atual and segundos is not None:
            self.status_label.setText(f"Segurando {direcao_atual}: faltam {segundos}s")
        elif direcao_atual:
            self.status_label.setText(f"Empurre o joystick para {direcao_atual}")
        else:
            feitas = ", ".join(
                f"{d}={'OK' if ok else 'FALHOU'}" for d, ok in resultado.get("direcoes", {}).items()
            )
            self.status_label.setText(f"Em andamento: {feitas}" if feitas else "Aguardando o Botao A na placa...")

    # -- conclusao da triagem (ultima tela -> aciona o Random Forest) --
    def _finish(self):
        self._disconnect()

        sensor_data = self._bitdoglab.get_latest() if self._bitdoglab else None
        facial_severity = self._facial_screen.engine.severity if self._facial_screen else 0

        arm_engine = self._arm_test_screen.engine if self._arm_test_screen else None
        side_code = {"L": 1, "R": 2, None: 0}.get(getattr(arm_engine, "weak_side", None), 0)
        arm_ratio = getattr(arm_engine, "ratio", None) or 0.0

        joystick_falhou = False
        if self._ultimo_resultado:
            geral = (self._ultimo_resultado.get("resultado_geral") or "").upper()
            if "POSSIVEL" in geral:
                joystick_falhou = True
            elif not geral:
                joystick_falhou = any(not ok for ok in self._ultimo_resultado.get("direcoes", {}).values())

        features = {
            "arm_ratio": arm_ratio,
            "arm_weak_side_code": side_code,
            "facial_asymmetry_score": facial_severity,
            "heart_rate": (sensor_data or {}).get("heart_rate", 0.0),
            "spo2": (sensor_data or {}).get("spo2", 0.0),
            # TODO: RiscoRandomForest._features_to_vector ainda nao usa esta
            # feature - somar quando o dataset/treino do modelo for definido.
            "joystick_falhou": int(joystick_falhou),
        }

        veredito = self.risco_model.predict(features)
        msg = f"Risco: {veredito['risco']}"
        if veredito["aviso"]:
            msg += f"\n({veredito['aviso']})"
        if joystick_falhou:
            msg += "\nTeste do joystick: possivel fraqueza detectada"
        QMessageBox.information(self, "Resultado da Triagem", msg)

        self._on_finish()
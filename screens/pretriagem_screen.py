from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.vitals_serial_client import (
    ESTADO_AGUARDANDO,
    ESTADO_CONCLUIDO,
    ESTADO_FALHA,
    ESTADO_LENDO,
    VitalsSerialReader,
    default_serial_port,
)

_COR_INATIVA = "#333"
_COR_LENDO = "#1f5fbf"      # azul - leitura em andamento
_COR_CONCLUIDO = "#2a8f2a"  # verde - valor final recebido
_COR_FALHA = "#a83232"      # vermelho - falha na leitura


class PreTriagemScreen(QWidget):
    """
    2a tela (logo depois da inicial): pre-triagem com sinais vitais.

    O firmware da BitDogLab roda isolado na placa - o Botao B nela inicia
    a leitura de oxigenacao (SpO2) e batimentos cardiacos (BPM) - e
    imprime o resultado pela USB serial (ver core/vitals_serial_client.py).
    Aqui a gente so LE a porta serial, mostra os valores e guarda o
    resultado final pra ser usado pelo Random Forest no fim da triagem
    (ver get_vitals()).
    """

    # Signals garantem que os widgets so sao tocados na thread da UI
    # (as callbacks do leitor serial chegam de outra thread).
    _line_received = Signal(str)
    _update_received = Signal(dict)

    def __init__(self, on_next, on_back):
        super().__init__()
        self._on_next = on_next
        self._on_back = on_back

        self.reader: VitalsSerialReader | None = None
        self._spo2_final: float | None = None
        self._heart_rate_final: float | None = None

        self._line_received.connect(self._append_log)
        self._update_received.connect(self._apply_update)

        layout = QVBoxLayout(self)

        title = QLabel("Pre-triagem (Oxigenacao e Batimentos)")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        info = QLabel(
            "Conecte a BitDogLab e aperte o Botao B nela para iniciar a leitura. "
            "Mantenha o dedo parado no sensor ate o resultado aparecer."
        )
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(self._build_value_cards())

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Porta serial:"))
        self.port_input = QLineEdit(default_serial_port())
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
        back_btn = QPushButton("Voltar")
        back_btn.clicked.connect(self._go_back)
        self.next_btn = QPushButton("Prosseguir para Assimetria Facial")
        self.next_btn.setEnabled(False)  # so libera depois do resultado final
        self.next_btn.clicked.connect(self._go_next)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)

    # -- montagem dos cartoes de valor (SpO2 / BPM) --
    def _build_value_cards(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.addStretch()

        self.spo2_card, self.spo2_value = self._make_card("Oxigenacao (SpO2)", "%")
        self.bpm_card, self.bpm_value = self._make_card("Batimentos (BPM)", "bpm")
        row.addWidget(self.spo2_card)
        row.addSpacing(16)
        row.addWidget(self.bpm_card)
        row.addStretch()
        return wrapper

    @staticmethod
    def _make_card(titulo: str, unidade: str) -> tuple[QWidget, QLabel]:
        card = QWidget()
        card.setFixedSize(220, 130)
        card.setStyleSheet(PreTriagemScreen._estilo_card(_COR_INATIVA))
        col = QVBoxLayout(card)
        col.setAlignment(Qt.AlignCenter)

        lbl_titulo = QLabel(titulo)
        lbl_titulo.setAlignment(Qt.AlignCenter)
        lbl_titulo.setStyleSheet("font-size: 14px; background: transparent;")

        lbl_valor = QLabel("--")
        lbl_valor.setAlignment(Qt.AlignCenter)
        lbl_valor.setStyleSheet("font-size: 40px; font-weight: bold; background: transparent;")

        lbl_unidade = QLabel(unidade)
        lbl_unidade.setAlignment(Qt.AlignCenter)
        lbl_unidade.setStyleSheet("font-size: 13px; background: transparent;")

        col.addWidget(lbl_titulo)
        col.addWidget(lbl_valor)
        col.addWidget(lbl_unidade)
        return card, lbl_valor

    @staticmethod
    def _estilo_card(cor_fundo: str) -> str:
        return f"background-color: {cor_fundo}; color: white; border-radius: 10px;"

    def _pintar_cards(self, cor: str):
        estilo = self._estilo_card(cor)
        self.spo2_card.setStyleSheet(estilo)
        self.bpm_card.setStyleSheet(estilo)

    # -- chamado pelo MainWindow ao entrar/sair da tela --
    def enter_screen(self):
        # Nova triagem: zera o que sobrou de uma execucao anterior.
        # A conexao serial e manual (botao "Conectar"), como no joystick.
        self._spo2_final = None
        self._heart_rate_final = None
        self.spo2_value.setText("--")
        self.bpm_value.setText("--")
        self._pintar_cards(_COR_INATIVA)
        self.next_btn.setEnabled(False)
        self.log_view.clear()

    def leave_screen(self):
        # Libera a porta serial (o teste do joystick usa a mesma porta).
        self._disconnect()

    # -- resultado da pre-triagem (consumido no fim da triagem) --
    def get_vitals(self) -> dict:
        """Valores finais medidos; 0.0 se a leitura nao foi concluida."""
        return {
            "spo2": self._spo2_final if self._spo2_final is not None else 0.0,
            "heart_rate": self._heart_rate_final if self._heart_rate_final is not None else 0.0,
        }

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
        self.reader = VitalsSerialReader(
            port=port,
            on_line=self._line_received.emit,
            on_update=self._update_received.emit,
        )
        self.reader.start()
        self.connect_btn.setText("Desconectar")
        self.status_label.setText("Conectado - aperte o Botao B na placa para iniciar")

    def _disconnect(self):
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        self.connect_btn.setText("Conectar")
        self.status_label.setText("Desconectado")

    # -- slots (rodam na thread da UI) --
    def _append_log(self, linha: str):
        self.log_view.append(linha)

    def _apply_update(self, dados: dict):
        if self.reader is None:
            return  # atualizacao tardia depois de desconectar

        estado = dados.get("estado")
        spo2 = dados.get("spo2")
        bpm = dados.get("heart_rate")

        self.spo2_value.setText(f"{spo2:.0f}" if spo2 is not None else "--")
        self.bpm_value.setText(f"{bpm:.0f}" if bpm is not None else "--")

        if estado == ESTADO_CONCLUIDO:
            self._spo2_final = spo2
            self._heart_rate_final = bpm
            self._pintar_cards(_COR_CONCLUIDO)
            self.next_btn.setEnabled(True)
            self.status_label.setText(f"Leitura concluida: SpO2 {spo2:.0f}% | {bpm:.0f} bpm")
        elif estado == ESTADO_LENDO:
            if spo2 is None and bpm is None:  # comecou uma nova medicao
                self._spo2_final = None
                self._heart_rate_final = None
                self.next_btn.setEnabled(False)
            self._pintar_cards(_COR_LENDO)
            segundos = dados.get("segundos_restantes")
            decorridos = dados.get("segundos_decorridos")
            if segundos is not None:
                self.status_label.setText(f"Lendo sinais vitais: faltam {segundos}s")
            elif decorridos is not None:
                self.status_label.setText(
                    f"Lendo sinais vitais ({decorridos}s) - mantenha o dedo parado no sensor"
                )
            else:
                self.status_label.setText("Lendo sinais vitais - mantenha o dedo parado no sensor")
        elif estado == ESTADO_FALHA:
            self._spo2_final = None
            self._heart_rate_final = None
            self._pintar_cards(_COR_FALHA)
            self.next_btn.setEnabled(False)
            self.status_label.setText(f"Falha: {dados.get('mensagem') or 'leitura invalida'}")
        elif estado == ESTADO_AGUARDANDO:
            self._spo2_final = None
            self._heart_rate_final = None
            self._pintar_cards(_COR_INATIVA)
            self.next_btn.setEnabled(False)
            self.status_label.setText("Aguardando o Botao B na placa...")

    # -- navegacao --
    def _go_back(self):
        self._disconnect()
        self._on_back()

    def _go_next(self):
        self._disconnect()
        self._on_next()

"""Tela de trajetórias 2D do NeuroTriagem_firmware (protocolo 2)."""

import time
from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.bitdoglab_serial_client import JoystickTestSerialReader
from core.random_forest_runtime import get_model_status, load_app_model
from core.vitals_serial_client import default_serial_port
from screens.joystick_trajectory_widget import JoystickTrajectoryWidget

FORMAS = ("QUADRADO", "TRIANGULO", "CIRCULO")
NOMES = {"QUADRADO": "Quadrado", "TRIANGULO": "Triângulo", "CIRCULO": "Círculo"}
SITUACOES = {
    "CONCLUIDO": "Concluído", "TEMPO_LIMITE": "Tempo limite · parcial",
    "NAO_INICIADO": "Não iniciado",
}


def _label(text="", style=""):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    if style:
        label.setStyleSheet(style)
    return label


class JoystickTestScreen(QWidget):
    """A placa conduz o teste; a tela recebe etapas e resultados pela USB.

    JOYSTICK_POSICAO acompanha o movimento durante a coleta. As amostras
    opcionais JOYSTICK_AMOSTRA continuam sendo um registro posterior.
    """

    _line_received = Signal(int, str)
    _update_received = Signal(int, dict)
    _connection_received = Signal(int, dict)
    _sample_received = Signal(int, dict)
    _position_received = Signal(int, dict)

    def __init__(self, on_finish, pretriagem_screen=None, facial_screen=None, arm_test_screen=None):
        super().__init__()
        self._on_finish = on_finish
        self._pretriagem_screen = pretriagem_screen
        self._facial_screen = facial_screen
        self._arm_test_screen = arm_test_screen
        self.reader = None
        self.risco_model = load_app_model()
        self._session_id = 0
        self._ultimo_resultado = None
        self._samples = {forma: [] for forma in FORMAS}
        self._live_samples = {forma: [] for forma in FORMAS}
        self._live_positions = {}
        self._position_received_at = {}
        self._selected_shape = FORMAS[0]
        self._line_received.connect(self._append_log, Qt.QueuedConnection)
        self._update_received.connect(self._apply_update, Qt.QueuedConnection)
        self._connection_received.connect(self._apply_connection, Qt.QueuedConnection)
        self._sample_received.connect(self._apply_sample, Qt.QueuedConnection)
        self._position_received.connect(self._apply_position, Qt.QueuedConnection)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._position_watchdog = QTimer(self)
        self._position_watchdog.setInterval(500)
        self._position_watchdog.timeout.connect(self._check_position_age)

        self.setObjectName("joystickScreen")
        self.setStyleSheet("""
            QWidget#joystickScreen { background: #f4f6fa; color: #172b4d; }
            QFrame#trajectoryCard, QFrame#instructionCard {
                background: white; border: 1px solid #dce3ed; border-radius: 10px;
            }
            QPushButton { padding: 7px 14px; }
            QPushButton:checked { background: #e5efff; color: #174e9a;
                border: 1px solid #83a9df; border-radius: 6px; }
            QPushButton#finishButton { background: #215fba; color: white;
                border: none; border-radius: 6px; padding: 10px 20px; }
            QPushButton#finishButton:disabled { background: #dce3ed; color: #66758b; }
            QTableWidget { background: white; color: #172b4d;
                gridline-color: #e5eaf1; border: 1px solid #dce3ed; }
            QTableWidget::item:selected { background: #e5efff; color: #174e9a; }
            QHeaderView::section { background: #edf2f8; color: #33465e;
                border: none; padding: 7px 4px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(_label("Teste do joystick", "font-size: 24px; font-weight: 700;"))
        layout.addWidget(_label(
            "Percorra quadrado, triângulo e círculo no sentido horário, no seu ritmo.",
            "color: #53657d; font-size: 14px;",
        ))
        self.model_status_label = _label(
            get_model_status(self.risco_model),
            "background: #fff4d6; color: #664e13; padding: 8px; border-radius: 6px;",
        )
        self.model_status_label.setAccessibleName("Modo de classificação do Random Forest")
        layout.addWidget(self.model_status_label)
        connection = QHBoxLayout()
        connection.addWidget(QLabel("Porta serial"))
        self.port_input = QLineEdit(default_serial_port())
        self.port_input.setMaximumWidth(240)
        self.port_input.setAccessibleName("Porta serial da BitDogLab")
        connection.addWidget(self.port_input)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self._toggle_connection)
        connection.addWidget(self.connect_btn)
        self.connection_label = _label("Desconectado", "color: #53657d;")
        connection.addWidget(self.connection_label, 1)
        layout.addLayout(connection)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(10)
        steps = QHBoxLayout()
        self.shape_buttons = {}
        for index, forma in enumerate(FORMAS):
            button = QPushButton(f"{index + 1}. {NOMES[forma]}")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, shape=forma: self._select_shape(shape))
            steps.addWidget(button)
            self.shape_buttons[forma] = button
        body.addLayout(steps)

        panels = QHBoxLayout()
        preview_card = QFrame()
        preview_card.setObjectName("trajectoryCard")
        preview_layout = QVBoxLayout(preview_card)
        self.trajectory = JoystickTrajectoryWidget()
        self.trajectory.setFixedHeight(230)
        preview_layout.addWidget(self.trajectory, 1)
        self.preview_caption = _label("", "color: #53657d; font-size: 12px;")
        preview_layout.addWidget(self.preview_caption)
        panels.addWidget(preview_card, 1)
        instructions = QFrame()
        instructions.setObjectName("instructionCard")
        instruction_layout = QVBoxLayout(instructions)
        instruction_layout.setContentsMargins(18, 16, 18, 16)
        self.phase_label = _label("", "color: #215fba; font-weight: 700;")
        self.status_label = _label("", "font-size: 20px; font-weight: 600;")
        self.instruction_label = _label("", "font-size: 14px; color: #33465e;")
        self.session_label = _label("", "font-size: 12px; color: #53657d;")
        instruction_layout.addWidget(self.phase_label)
        instruction_layout.addWidget(self.status_label)
        instruction_layout.addWidget(self.instruction_label)
        instruction_layout.addStretch()
        instruction_layout.addWidget(self.session_label)
        instruction_layout.addWidget(_label(
            "Na placa: A inicia um novo teste · B interrompe e abre o oxímetro.",
            "color: #53657d; font-size: 12px;",
        ))
        panels.addWidget(instructions, 1)
        body.addLayout(panels)

        body.addWidget(_label("Resultados por figura", "font-size: 16px; font-weight: 600;"))
        self.results_table = QTableWidget(3, 7)
        self.results_table.setHorizontalHeaderLabels([
            "Figura", "Situação", "Progresso", "Tempo (s)",
            "Desvio (u)", "Sobreposição", "Dados",
        ])
        self.results_table.verticalHeader().hide()
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.horizontalHeader().setMinimumSectionSize(85)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.setFixedHeight(130)
        self.results_table.cellClicked.connect(lambda row, col: self._select_shape(FORMAS[row]))
        self.results_table.horizontalHeaderItem(2).setToolTip("Pontos alcançados em ordem, informados pela placa durante e após o percurso.")
        self.results_table.horizontalHeaderItem(4).setToolTip("Distância média à curva de referência, em unidades normalizadas.")
        self.results_table.horizontalHeaderItem(5).setToolTip("Comprimento percorrido dentro da tolerância da curva (%).")
        self.results_table.horizontalHeaderItem(6).setToolTip("Integridade numérica; não indica conclusão ou normalidade clínica.")
        body.addWidget(self.results_table)

        self.details_btn = QPushButton("Mostrar métricas detalhadas")
        self.details_btn.setCheckable(True)
        self.details_label = _label("", "color: #33465e; padding: 8px;")
        self.details_label.hide()
        self.details_btn.toggled.connect(self.details_label.setVisible)
        self.details_btn.toggled.connect(lambda shown: self.details_btn.setText(
            "Ocultar métricas detalhadas" if shown else "Mostrar métricas detalhadas"))
        self.log_btn = QPushButton("Mostrar registro serial")
        self.log_btn.setCheckable(True)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(300)
        self.log_view.setFixedHeight(115)
        self.log_view.setStyleSheet("background: #172538; color: #dce8f8; font-family: monospace;")
        self.log_view.hide()
        self.log_btn.toggled.connect(self.log_view.setVisible)
        self.log_btn.toggled.connect(lambda shown: self.log_btn.setText(
            "Ocultar registro serial" if shown else "Mostrar registro serial"))
        detail_controls = QHBoxLayout()
        detail_controls.addWidget(self.details_btn)
        detail_controls.addWidget(self.log_btn)
        body.addLayout(detail_controls)
        body.addWidget(self.details_label)
        body.addWidget(_label(
            "u = deslocamento normalizado do joystick. Os resultados descrevem o movimento; "
            "não medem força nem classificam fraqueza ou risco de AVC.",
            "color: #53657d; font-size: 12px;",
        ))
        body.addWidget(self.log_view)
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.finish_hint = _label("", "color: #53657d;")
        footer.addWidget(self.finish_hint, 1)
        self.finish_btn = QPushButton("Ver classificação final")
        self.finish_btn.setObjectName("finishButton")
        self.finish_btn.clicked.connect(self._finish)
        footer.addWidget(self.finish_btn)
        layout.addLayout(footer)
        self._reset_session()

    def _reset_session(self):
        self._ultimo_resultado = None
        self._finish_emitted = False
        self._samples = {forma: [] for forma in FORMAS}
        self._live_samples = {forma: [] for forma in FORMAS}
        self._live_positions.clear()
        self._position_received_at.clear()
        self._preview_timer.stop()
        self._position_watchdog.stop()
        self.finish_btn.setEnabled(False)
        self.finish_hint.setText("A classificação final será liberada ao receber o fim do teste da placa.")
        self.phase_label.setText("PRONTO PARA COMEÇAR")
        self.status_label.setText("Conecte a BitDogLab")
        self.instruction_label.setText(
            "Depois de conectar, pressione A e solte o joystick. "
            "Mantenha-o parado enquanto a placa calibra o centro."
        )
        self.session_label.setText("0 de 3 resultados recebidos")
        self._update_table({})
        self._select_shape(FORMAS[0])

    def enter_screen(self):
        self._disconnect()
        self._reset_session()
        self.log_view.clear()
        if self._pretriagem_screen is not None:
            self.port_input.setText(self._pretriagem_screen.port_input.text())

    def leave_screen(self):
        self._disconnect()

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
        self._reset_session()
        self.log_view.clear()
        self._session_id += 1
        token = self._session_id
        self.reader = JoystickTestSerialReader(
            port=port,
            on_line=lambda line: self._line_received.emit(token, line),
            on_result=lambda result: self._update_received.emit(token, result),
            on_connection=lambda state: self._connection_received.emit(token, state),
            on_sample=lambda sample: self._sample_received.emit(token, sample),
            on_position=lambda position: self._position_received.emit(token, position),
        )
        self.port_input.setEnabled(False)
        self.connect_btn.setText("Desconectar")
        self.connection_label.setText(f"Conectando a {port}…")
        self.reader.start()

    def _disconnect(self):
        self._session_id += 1  # Invalida inclusive callbacks já enfileirados no Qt.
        reader, self.reader = self.reader, None
        if reader is not None:
            reader.stop()
        self._position_watchdog.stop()
        self._preview_timer.stop()
        self._refresh_preview()
        self.connect_btn.setText("Conectar")
        self.port_input.setEnabled(True)
        self.connection_label.setText("Desconectado")
        if self._ultimo_resultado and not self._ultimo_resultado.get("final"):
            self.phase_label.setText("CONEXÃO ENCERRADA")
            self.status_label.setText("Recepção interrompida")
            self.instruction_label.setText("Reconecte e pressione A na placa para iniciar um novo teste.")

    def _is_current(self, token):
        return token == self._session_id and self.reader is not None

    def _append_log(self, token, line):
        if self._is_current(token) and not line.startswith(("JOYSTICK_AMOSTRA,", "JOYSTICK_POSICAO,")):
            self.log_view.appendPlainText(line)

    def _apply_connection(self, token, data):
        if not self._is_current(token):
            return
        state = data.get("estado")
        if state == "CONECTADO":
            self.connection_label.setText(f"Conectado · {self.port_input.text().strip()}")
            self.status_label.setText("Pressione A na placa")
        elif state in ("ERRO", "DESCONECTADO"):
            self._disconnect()
            message = data.get("mensagem") or "Conexão serial encerrada."
            self.connection_label.setText(message)
            self.log_view.appendPlainText(message)
            if not (self._ultimo_resultado or {}).get("final"):
                self.phase_label.setText("SEM CONEXÃO")
                self.status_label.setText("Não foi possível receber o teste")
                self.instruction_label.setText("Confira a porta e a conexão USB e tente conectar novamente.")

    def _apply_update(self, token, data):
        if not self._is_current(token):
            return
        state = data.get("estado", "AGUARDANDO")
        if state == "CALIBRANDO":
            self._reset_session()
        previous = self._ultimo_resultado or {}
        self._ultimo_resultado = data
        results = data.get("resultados", {})
        final = data.get("final")
        self.finish_btn.setEnabled(final is not None and not self._finish_emitted)
        self.finish_hint.setText(
            "Teste recebido. Abra a classificação final do NeuroTriagem.AI." if final is not None else
            "A classificação final será liberada ao receber o fim do teste da placa."
        )
        self._update_table(results)
        self.session_label.setText(f"{len(results)} de 3 resultados recebidos")
        shape = data.get("forma_atual")
        if state in ("POSICIONAR", "PERCURSO") and final is None:
            if (previous.get("estado"), previous.get("forma_atual")) != (state, shape):
                self._live_positions.pop(shape, None)
                self._position_received_at.pop(shape, None)
                if shape in FORMAS:
                    self._live_samples[shape] = []
            self._position_watchdog.start()
        else:
            self._position_watchdog.stop()
        if shape in FORMAS:
            self._select_shape(shape)
        else:
            self._refresh_preview()
        name = NOMES.get(shape, "figura")
        limit = data.get("configuracao", {}).get("limite_ms", 90000) / 1000
        if final is not None:
            self.phase_label.setText("TESTE FINALIZADO")
            self.status_label.setText(f"{final['concluidas']} de {final['total']} trajetórias concluídas")
            self.instruction_label.setText(
                "Confira os resultados abaixo. Percursos parciais e não iniciados "
                "são identificados separadamente. Pressione A para repetir."
            )
        elif state == "CALIBRANDO":
            self.phase_label.setText("CALIBRAÇÃO DO CENTRO")
            self.status_label.setText("Solte o joystick")
            self.instruction_label.setText("Deixe o joystick solto e parado até a calibração terminar.")
        elif state == "PRONTO":
            self.phase_label.setText("CENTRO CALIBRADO")
            self.status_label.setText("Prepare-se para o quadrado")
            self.instruction_label.setText(
                "O cursor verde acompanha o joystick. O quadrado azul indica o próximo alvo. "
                "O OLED da placa também acompanha o movimento."
            )
        elif state == "POSICIONAR":
            self.phase_label.setText(f"{name.upper()} · POSICIONAR")
            self.status_label.setText("Vá até o ponto inicial")
            self.instruction_label.setText(
                "Leve o joystick até o marcador inicial e mantenha a posição por 0,3 s. "
                "Você tem até 30 s para se posicionar. Leve o cursor verde até o alvo azul."
            )
        elif state == "PERCURSO":
            self.phase_label.setText(f"{name.upper()} · EM ANDAMENTO")
            self.status_label.setText("Siga a figura no sentido horário")
            self.instruction_label.setText(
                f"Siga os marcadores no seu ritmo e retorne ao início. Limite: {limit:g} s. "
                "Acompanhe o cursor verde e alcance os alvos azuis em ordem. "
                "As métricas chegam ao terminar o percurso."
            )
        elif state == "RESULTADO":
            result = results.get(shape, {})
            self.phase_label.setText(f"{name.upper()} · RESULTADO RECEBIDO")
            self.status_label.setText(SITUACOES.get(result.get("estado"), "Resultado recebido"))
            self.instruction_label.setText(
                "O tempo para alcançar o ponto inicial terminou. Não há métricas deste percurso."
                if result.get("estado") == "NAO_INICIADO" else
                "O limite de tempo foi atingido; as métricas correspondem ao percurso parcial."
                if result.get("estado") == "TEMPO_LIMITE" else
                "Todos os pontos foram alcançados em ordem. Aguarde a próxima instrução da placa."
            )
        elif state == "CANCELADO":
            self.phase_label.setText("TESTE INTERROMPIDO")
            self.status_label.setText("A placa mudou para o oxímetro")
            self.instruction_label.setText("Pressione A e solte o joystick para iniciar um novo teste completo.")
        elif state == "ERRO":
            self.phase_label.setText("TESTE NÃO CONCLUÍDO")
            self.status_label.setText("Não foi possível continuar")
            self.instruction_label.setText(data.get("mensagem") or "Solte o joystick e pressione A para repetir a calibração.")
        else:
            self.phase_label.setText("AGUARDANDO A PLACA")
            self.status_label.setText("Pressione A para iniciar")
            self.instruction_label.setText("Solte o joystick e mantenha-o parado durante a calibração do centro.")

    def _apply_position(self, token, data):
        if not self._is_current(token):
            return
        session = self._ultimo_resultado or {}
        shape = data.get("forma")
        phase = data.get("fase")
        if (shape not in FORMAS or phase not in ("POSICIONAR", "PERCURSO")
                or session.get("final") is not None
                or session.get("estado") != phase or session.get("forma_atual") != shape):
            return
        previous = self._live_positions.get(shape)
        if previous and previous["fase"] == phase and data["t_ms"] <= previous["t_ms"]:
            return
        self._live_positions[shape] = dict(data)
        self._position_received_at[shape] = time.monotonic()
        if phase == "PERCURSO":
            # Telemetria a 20 Hz, até 90 s. Não mistura aproximação com percurso.
            samples = self._live_samples[shape]
            if len(samples) < 4502:
                samples.append({"t_ms": data["t_ms"], "x": data["x"], "y": data["y"]})
            row = FORMAS.index(shape)
            self.results_table.item(row, 2).setText(f"{data['progresso']}%")
            self.results_table.item(row, 3).setText(f"{data['t_ms'] / 1000:.2f}")
        if shape == self._selected_shape and not self._preview_timer.isActive():
            self._preview_timer.start()

    def _check_position_age(self):
        shape = self._selected_shape
        if time.monotonic() - self._position_received_at.get(shape, 0) > 1.5:
            self._refresh_preview()

    def _apply_sample(self, token, data):
        if not self._is_current(token):
            return
        shape = data.get("forma")
        if shape not in self._samples:
            return
        samples = self._samples[shape]
        if len(samples) >= 4502 or (samples and data["t_ms"] <= samples[-1]["t_ms"]):
            return
        samples.append(data)
        if shape == self._selected_shape and not self._preview_timer.isActive():
            self._preview_timer.start()

    def _select_shape(self, shape):
        self._selected_shape = shape
        for key, button in self.shape_buttons.items():
            button.setChecked(key == shape)
        self.results_table.selectRow(FORMAS.index(shape))
        self._refresh_preview()

    def _refresh_preview(self):
        shape = self._selected_shape
        session = self._ultimo_resultado or {}
        active = (self.reader is not None and session.get("final") is None
                  and session.get("estado") in ("POSICIONAR", "PERCURSO")
                  and session.get("forma_atual") == shape)
        position = self._live_positions.get(shape) if active else None
        fresh = position is not None and time.monotonic() - self._position_received_at.get(shape, 0) <= 1.5
        result = session.get("resultados", {}).get(shape)
        exported = self._samples[shape]
        expected_samples = (result or {}).get("amostras", 0)
        export_complete = expected_samples > 0 and len(exported) >= expected_samples
        samples = exported if export_complete else self._live_samples[shape] or exported
        self.trajectory.set_trajectory(shape, samples)
        self.trajectory.set_live_position(position if fresh else None)
        if fresh:
            progress = f"{position['progresso']}% · " if position["fase"] == "PERCURSO" else "Posicionando · "
            self.preview_caption.setText(
                f"Ao vivo · {progress}{position['t_ms'] / 1000:.1f} s · "
                f"X {position['x']:+.2f} · Y {position['y']:+.2f}"
            )
        elif active:
            if position:
                text = "Posição sem atualização. Aguardando novos dados da placa…"
            elif session.get("protocolo") and not session.get("configuracao", {}).get("telemetria_ms"):
                text = "Aguardando posição. Se o cursor não aparecer, grave o firmware com telemetria ao vivo."
            else:
                text = "Aguardando a posição do joystick enviada pela placa…"
            self.preview_caption.setText(text)
        elif export_complete:
            self.preview_caption.setText(f"{NOMES[shape]} · registro completo exportado ({len(exported)} amostras).")
        elif exported:
            count = f"{len(exported)} de {expected_samples}" if expected_samples else str(len(exported))
            self.preview_caption.setText(f"{NOMES[shape]} · registro exportado parcial ({count} amostras).")
        elif self._live_samples[shape]:
            self.preview_caption.setText(f"{NOMES[shape]} · traçado recebido durante o movimento.")
        else:
            self.preview_caption.setText(f"{NOMES[shape]} · o cursor aparecerá quando a placa enviar a posição.")
        if not result:
            self.details_label.setText(f"{NOMES[shape]}: aguardando o resultado deste percurso.")
        elif not result.get("valido") or result.get("estado") == "NAO_INICIADO":
            self.details_label.setText(f"{NOMES[shape]}: sem métricas numéricas válidas. Amostras: {result.get('amostras', 0)}.")
        else:
            self.details_label.setText(
                f"{NOMES[shape]} · {SITUACOES.get(result['estado'], result['estado'])}\n"
                f"Caminho: {result['caminho_u']:.3f} u   |   Velocidade média: {result['vel_media_u_s']:.3f} u/s   |   "
                f"Aceleração média: {result['acel_media_u_s2']:.3f} u/s²\n"
                f"Desvio médio: {result['desvio_medio_u']:.3f} u   |   RMSE: {result['rmse_u']:.3f} u   |   "
                f"Sobreposição: {result['sobreposicao_pct']:.2f}%\n"
                f"NPV (velocidades acima da média): {result['npv']}   |   Amostras: {result['amostras']}   |   "
                f"Maior intervalo: {result['maior_intervalo_ms']} ms\n"
                "Área entre curvas: não calculada. Validade indica apenas integridade numérica."
            )

    def _update_table(self, results):
        for row, shape in enumerate(FORMAS):
            result = results.get(shape)
            values = [NOMES[shape], "Aguardando", "—", "—", "—", "—", "—"]
            session = self._ultimo_resultado or {}
            if not result and session.get("forma_atual") == shape:
                values[1] = {"POSICIONAR": "Posicionando", "PERCURSO": "Em percurso"}.get(
                    session.get("estado"), "Aguardando")
            if result:
                valid = bool(result.get("valido")) and result.get("estado") != "NAO_INICIADO"
                values[1] = SITUACOES.get(result.get("estado"), result.get("estado", "—"))
                values[2] = f"{result['progresso']}%"
                values[3] = f"{result['tempo_ms'] / 1000:.2f}" if valid else "—"
                values[4] = f"{result['desvio_medio_u']:.3f}" if valid else "—"
                values[5] = f"{result['sobreposicao_pct']:.2f}%" if valid else "—"
                values[6] = "Válidos" if valid else "Sem métricas"
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.results_table.setItem(row, col, item)

    def _finish(self):
        final = (self._ultimo_resultado or {}).get("final")
        if final is None or self._finish_emitted:
            return
        self._finish_emitted = True
        self.finish_btn.setEnabled(False)
        self._disconnect()
        vitals = self._pretriagem_screen.get_vitals() if self._pretriagem_screen else {}
        # O contrato é compartilhado com o notebook. Uma etapa não medida não
        # equivale a uma observação normal. O getter legado de vitais usa zero
        # para indicar ausência, convertido aqui antes da inferência.
        features = {
            "arm_ratio": None,
            "arm_weak_side_code": None,
            "facial_asymmetry_score": None,
            "heart_rate": vitals.get("heart_rate") or None,
            "spo2": vitals.get("spo2") or None,
        }
        if self._arm_test_screen is not None:
            features.update(self._arm_test_screen.get_features())
        if self._facial_screen is not None:
            features.update(self._facial_screen.get_features())
        veredito = self.risco_model.predict(features)
        # A tela final recebe uma fotografia da avaliação. Leituras posteriores
        # ou uma nova sessão não alteram silenciosamente o resultado mostrado.
        self._on_finish({
            "veredito": deepcopy(veredito),
            "features": deepcopy(features),
            "joystick": deepcopy(self._ultimo_resultado),
            "model_status": get_model_status(self.risco_model),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })

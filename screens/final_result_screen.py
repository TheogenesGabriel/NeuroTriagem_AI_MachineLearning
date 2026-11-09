"""Resultado persistente da avaliação, separado das telas de aquisição."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)


TONES = {
    "alert": ("#fff4ed", "#e4b18c", "#914313"),
    "attention": ("#fff9e8", "#dfca87", "#795b11"),
    "neutral": ("#edf4ff", "#b7cdea", "#234f88"),
    "unavailable": ("#f0f3f7", "#cbd4df", "#526175"),
}


def _label(text="", style=""):
    label = QLabel(str(text))
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    if style:
        label.setStyleSheet(style)
    return label


class MeasurementCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("measurementCard")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)
        self.title_label = _label(style="font-size: 12px; color: #596c84;")
        self.value_label = _label(style="font-size: 19px; font-weight: 700; color: #243f61;")
        self.value_label.setMinimumHeight(46)
        self.detail_label = _label(style="font-size: 12px; color: #596c84;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addStretch()

    def set_measurement(self, data):
        self.title_label.setText(str(data.get("label", "")))
        self.value_label.setText(str(data.get("value", "—")))
        self.detail_label.setText(str(data.get("detail", "")))
        _, _, color = TONES.get(data.get("tone"), TONES["neutral"])
        self.value_label.setStyleSheet(f"font-size: 19px; font-weight: 700; color: {color};")


class FinalResultScreen(QWidget):
    """Exibe um snapshot pronto; não recalcula nem altera a previsão do modelo."""

    def __init__(self, on_new_assessment, on_home):
        super().__init__()
        self.presentation = None
        self.setObjectName("finalResultScreen")
        self.setStyleSheet("""
            QWidget#finalResultScreen, QWidget#resultContent { background: #f4f6fa; color: #172b4d; }
            QScrollArea { background: transparent; border: none; }
            QFrame#measurementCard, QFrame#joystickSummaryCard, QFrame#detailsPanel {
                background: white; border: 1px solid #dce4ee; border-radius: 10px;
            }
            QPushButton { padding: 10px 18px; border-radius: 7px; font-size: 13px; }
            QPushButton#newAssessmentButton { background: #215fba; color: white; border: 1px solid #215fba; }
            QPushButton#newAssessmentButton:hover { background: #184e9d; }
            QPushButton#homeButton { background: white; color: #284a73; border: 1px solid #ced9e7; }
            QPushButton#homeButton:hover { background: #edf3fb; }
            QToolButton { border: none; padding: 7px 0; text-align: left; color: #275785; font-size: 12px; }
            QTableWidget { background: white; color: #263e5d; border: none; gridline-color: #e9eef5; font-size: 12px; }
            QHeaderView::section { background: #f0f4fa; color: #526881; padding: 5px; border: none; font-size: 11px; }
            QTableWidget::item { padding: 3px; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(12)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("resultContent")
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(_label("NeuroTriagem.AI", "font-size: 13px; font-weight: 700; color: #215fba;"))
        titles.addWidget(_label("Classificação final", "font-size: 27px; font-weight: 700; color: #173453;"))
        header.addLayout(titles, 1)
        self.timestamp_label = _label(style="font-size: 12px; color: #64768d;")
        self.timestamp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.timestamp_label)
        body.addLayout(header)

        self.hero = QFrame()
        self.hero.setObjectName("resultHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_layout.setSpacing(6)
        hero_layout.addWidget(_label("RESULTADO DO PROTÓTIPO", "font-size: 11px; font-weight: 700; color: #52647b;"))
        self.heading_label = _label(style="font-size: 29px; font-weight: 700; color: #173453;")
        self.subtitle_label = _label(style="font-size: 13px; color: #405570;")
        self.disclaimer_label = _label(style="font-size: 12px; color: #647183;")
        hero_layout.addWidget(self.heading_label)
        hero_layout.addWidget(self.subtitle_label)
        hero_layout.addWidget(self.disclaimer_label)
        body.addWidget(self.hero)

        self.notices_label = _label(style=(
            "background: #fff7e5; color: #765410; border: 1px solid #ead19a; "
            "border-radius: 7px; padding: 10px; font-size: 13px;"
        ))
        body.addWidget(self.notices_label)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.measurement_cards = []
        for column in range(4):
            card = MeasurementCard()
            self.measurement_cards.append(card)
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)
        body.addLayout(grid)

        joystick = QFrame()
        joystick.setObjectName("joystickSummaryCard")
        joystick_layout = QVBoxLayout(joystick)
        joystick_layout.setContentsMargins(14, 10, 14, 10)
        joystick_layout.setSpacing(6)
        joystick_title = QHBoxLayout()
        joystick_title.addWidget(_label("Joystick", "font-size: 16px; font-weight: 700; color: #243f61;"))
        self.joystick_summary_label = _label(style="font-size: 12px; color: #596c84;")
        self.joystick_summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        joystick_title.addWidget(self.joystick_summary_label, 1)
        joystick_layout.addLayout(joystick_title)
        joystick_layout.addWidget(_label(
            "Medidas descritivas; não entram na classificação do modelo.",
            "font-size: 12px; color: #596c84;",
        ))
        self.joystick_table = QTableWidget(0, 6)
        self.joystick_table.setHorizontalHeaderLabels(
            ["Figura", "Situação", "Tempo (s)", "Desvio (u)", "Sobreposição", "Dados"]
        )
        self.joystick_table.verticalHeader().hide()
        self.joystick_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.joystick_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.joystick_table.setFocusPolicy(Qt.NoFocus)
        self.joystick_table.setWordWrap(True)
        self.joystick_table.setShowGrid(False)
        self.joystick_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.joystick_table.horizontalHeader().setMinimumSectionSize(30)
        self.joystick_table.verticalHeader().setDefaultSectionSize(27)
        self.joystick_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.joystick_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        joystick_layout.addWidget(self.joystick_table)
        body.addWidget(joystick)

        self.details_toggle = QToolButton()
        self.details_toggle.setCheckable(True)
        self.details_toggle.setText("Detalhes da classificação")
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_toggle.toggled.connect(self._toggle_details)
        body.addWidget(self.details_toggle)
        self.details_panel = QFrame()
        self.details_panel.setObjectName("detailsPanel")
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(14, 12, 14, 12)
        details_layout.setSpacing(8)
        self.model_status_label = _label(style="font-size: 12px; color: #52647b;")
        self.reference_label = _label(style="font-size: 13px; color: #263e5d;")
        self.details_label = _label(style="font-size: 12px; color: #52647b;")
        details_layout.addWidget(self.model_status_label)
        details_layout.addWidget(self.reference_label)
        details_layout.addWidget(self.details_label)
        body.addWidget(self.details_panel)
        body.addStretch()
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        self.home_btn = QPushButton("Voltar ao início")
        self.home_btn.setObjectName("homeButton")
        self.home_btn.clicked.connect(on_home)
        self.new_assessment_btn = QPushButton("Nova avaliação")
        self.new_assessment_btn.setObjectName("newAssessmentButton")
        self.new_assessment_btn.clicked.connect(on_new_assessment)
        footer.addWidget(self.home_btn)
        footer.addWidget(self.new_assessment_btn)
        outer.addLayout(footer)
        self.clear_result()

    def _toggle_details(self, expanded):
        self.details_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.details_panel.setVisible(expanded)

    def set_result(self, presentation_dict):
        """Atualiza todos os campos; listas recebidas não ficam ligadas à tela."""
        self.presentation = deepcopy(presentation_dict)
        data = self.presentation
        self.timestamp_label.setText(str(data.get("timestamp", "")))
        self.heading_label.setText(str(data.get("heading", "Resultado indisponível")))
        self.subtitle_label.setText(str(data.get("subtitle", "")))
        self.disclaimer_label.setText(str(data.get("disclaimer", "")))
        background, border, _ = TONES.get(data.get("tone"), TONES["unavailable"])
        self.hero.setStyleSheet(
            f"QFrame#resultHero {{ background: {background}; border: 1px solid {border}; border-radius: 12px; }}"
        )
        notices = [str(value) for value in data.get("notices", []) if value]
        self.notices_label.setText("\n".join(notices))
        self.notices_label.setVisible(bool(notices))
        cards = data.get("cards", [])
        for index, card in enumerate(self.measurement_cards):
            card.set_measurement(cards[index] if index < len(cards) else {})
        self.joystick_summary_label.setText(str(data.get("joystick_summary", "")))
        rows = data.get("joystick_rows", [])
        self.joystick_table.clearContents()
        self.joystick_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column in range(6):
                text = str(row[column]) if column < len(row) else "—"
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.joystick_table.setItem(row_index, column, item)
        self.joystick_table.resizeRowsToContents()
        self._resize_table_height()
        self.model_status_label.setText(str(data.get("model_status", "")))
        reference = data.get("reference")
        self.reference_label.setText("Regra de referência: " + str(reference) if reference else "")
        self.reference_label.setVisible(bool(reference))
        self.details_label.setText(str(data.get("details", "")))
        self.details_toggle.setChecked(False)
        self._toggle_details(False)
        self.scroll_area.verticalScrollBar().setValue(0)

    def _resize_table_height(self):
        height = self.joystick_table.horizontalHeader().height()
        height += sum(self.joystick_table.rowHeight(index) for index in range(self.joystick_table.rowCount()))
        self.joystick_table.setFixedHeight(max(28, height + 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.joystick_table.resizeRowsToContents()
        self._resize_table_height()

    def clear_result(self):
        self.set_result({
            "heading": "Aguardando avaliação",
            "subtitle": "Conclua as etapas para visualizar a classificação final.",
            "tone": "unavailable",
            "cards": [{"label": name, "value": "—", "detail": "Sem resultado", "tone": "unavailable"}
                      for name in ("Face", "Braço", "Batimentos", "SpO₂")],
            "joystick_summary": "Sem resultado",
        })
        self.presentation = None

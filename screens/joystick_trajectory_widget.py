"""Referência, registro do percurso e posições transmitidas pela BitDogLab."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget


FORMAS = ("QUADRADO", "TRIANGULO", "CIRCULO")
_RAIO = 0.75
_PASSOS = 48
_AZUL = QColor("#2563eb")
_VERDE = QColor("#16836c")


def reference_points(forma: str | None) -> list[tuple[float, float]]:
    """Os 48 alvos de joy_alvo(), mais o inicial para fechar a curva.

    Mantém o sistema do firmware: X positivo à direita e Y positivo para
    cima. Todas as figuras começam no mesmo ponto e sentido que a placa.
    """
    if forma not in FORMAS:
        return []
    if forma == "CIRCULO":
        points = [
            (_RAIO * math.sin(2 * math.pi * i / _PASSOS),
             _RAIO * math.cos(2 * math.pi * i / _PASSOS))
            for i in range(_PASSOS)
        ]
    else:
        vertices = (
            [(-_RAIO, _RAIO), (_RAIO, _RAIO),
             (_RAIO, -_RAIO), (-_RAIO, -_RAIO)]
            if forma == "QUADRADO" else
            [(0.0, _RAIO), (math.sqrt(3) / 2 * _RAIO, -0.5 * _RAIO),
             (-math.sqrt(3) / 2 * _RAIO, -0.5 * _RAIO)]
        )
        per_side = _PASSOS // len(vertices)
        points = []
        for i in range(_PASSOS):
            side, offset = divmod(i, per_side)
            a, b = vertices[side], vertices[(side + 1) % len(vertices)]
            t = offset / per_side
            points.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return points + [points[0]]


class JoystickTrajectoryWidget(QWidget):
    """Desenha a referência e, quando recebidos, posição e próximo alvo reais.

    Não há animação nem interpolação do cursor: cada posição mostrada vem
    de uma atualização serial. A tela proprietária controla o rastro.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._forma: str | None = None
        self._samples: list[tuple[float, float]] = []
        self._live_position: dict | None = None
        self.setMinimumSize(230, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName("Referência do percurso do joystick")

    def sizeHint(self) -> QSize:
        return QSize(430, 240)

    def set_trajectory(self, forma: str | None, samples: list[dict] | None = None):
        self._forma = forma if forma in FORMAS else None
        self._samples = []
        self._live_position = None
        for sample in samples or []:
            try:
                x, y = float(sample["x"]), float(sample["y"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                self._samples.append((x, y))
        self._update_accessible_description()
        self.update()

    def set_live_position(self, position: dict | None):
        """Exibe somente coordenadas válidas da figura selecionada.

        Chamar com None, dados inválidos ou outra figura remove o cursor e
        o alvo. set_trajectory também limpa este overlay, evitando mostrar
        uma posição antiga durante uma troca de etapa ou revisão de dados.
        """
        self._live_position = None
        if (isinstance(position, dict)
                and position.get("forma") == self._forma
                and self._forma in FORMAS
                and position.get("fase") in ("POSICIONAR", "PERCURSO")):
            try:
                coordinates = {
                    name: float(position[name]) for name in ("x", "y", "alvo_x", "alvo_y")
                }
            except (KeyError, TypeError, ValueError, OverflowError):
                coordinates = {}
            if coordinates and all(math.isfinite(value) and -1 <= value <= 1
                                   for value in coordinates.values()):
                self._live_position = {**position, **coordinates}
        self._update_accessible_description()
        self.update()

    def _update_accessible_description(self):
        description = f"{self._forma or 'Aguardando figura'}, sentido horário. "
        if self._live_position:
            p = self._live_position
            description += (f"Posição recebida: X {p['x']:.2f}, Y {p['y']:.2f}. "
                            f"Próximo alvo: X {p['alvo_x']:.2f}, Y {p['alvo_y']:.2f}.")
        else:
            description += ("Percurso registrado após a coleta." if self._samples
                            else "Referência sem posição ao vivo.")
        self.setAccessibleDescription(description)

    def _plot_rect(self) -> QRectF:
        available = QRectF(self.rect()).adjusted(28, 24, -28, -42)
        side = max(1.0, min(available.width(), available.height()))
        center = available.center()
        return QRectF(center.x() - side / 2, center.y() - side / 2, side, side)

    def _map_point(self, point: tuple[float, float]) -> QPointF:
        plot = self._plot_rect()
        return QPointF(
            plot.center().x() + point[0] * plot.width() / 2,
            plot.center().y() - point[1] * plot.height() / 2,
        )

    def _path(self, points: list[tuple[float, float]]) -> QPainterPath:
        path = QPainterPath()
        if points:
            path.moveTo(self._map_point(points[0]))
            for point in points[1:]:
                path.lineTo(self._map_point(point))
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#f8fafc"))
        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)

        plot = self._plot_rect()
        painter.setPen(QPen(QColor("#dbe3ed"), 1))
        painter.drawLine(self._map_point((-1, 0)), self._map_point((1, 0)))
        painter.drawLine(self._map_point((0, -1)), self._map_point((0, 1)))
        painter.setPen(QColor("#64748b"))
        painter.drawText(QRectF(plot.right() + 4, plot.center().y() - 9, 20, 18), Qt.AlignCenter, "X")
        painter.drawText(QRectF(plot.center().x() - 9, plot.top() - 20, 18, 18), Qt.AlignCenter, "Y")

        points = reference_points(self._forma)
        if not points:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot, Qt.AlignCenter, "Aguardando figura")
            painter.end()
            return

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_AZUL, 2.2, Qt.DotLine, Qt.RoundCap))
        painter.drawPath(self._path(points))
        if self._samples:
            painter.save()
            painter.setClipRect(plot)
            painter.setPen(QPen(_VERDE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self._path(self._samples))
            painter.restore()

        # Um ponto cinza marca o início; o quadrado azul identifica o alvo.
        start = self._map_point(points[0])
        painter.setBrush(QColor("#64748b"))
        painter.setPen(QPen(QColor("white"), 1.5))
        painter.drawEllipse(start, 3.5, 3.5)

        if self._live_position is not None:
            self._draw_live_position(painter)
            self._draw_live_legend(painter)
        else:
            self._draw_static_annotations(painter, points, start)
        painter.end()

    def _draw_live_position(self, painter: QPainter):
        position = self._live_position
        target = self._map_point((position["alvo_x"], position["alvo_y"]))
        cursor = self._map_point((position["x"], position["y"]))

        # Quadrado grande e cruz menor continuam distinguíveis quando coincidem.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("white"), 4))
        target_rect = QRectF(target.x() - 8, target.y() - 8, 16, 16)
        painter.drawRect(target_rect)
        painter.setPen(QPen(_AZUL, 2.5))
        painter.drawRect(target_rect)

        painter.setBrush(QColor("white"))
        painter.setPen(QPen(_VERDE, 2.5))
        painter.drawEllipse(cursor, 5, 5)
        painter.drawLine(QPointF(cursor.x() - 8, cursor.y()), QPointF(cursor.x() + 8, cursor.y()))
        painter.drawLine(QPointF(cursor.x(), cursor.y() - 8), QPointF(cursor.x(), cursor.y() + 8))

    def _draw_live_legend(self, painter: QPainter):
        font = painter.font()
        font.setPointSizeF(9)
        painter.setFont(font)
        # A legenda ocupa uma faixa separada, inclusive na largura mínima.
        labels = (("Alvo", _AZUL), ("Posição", _VERDE), ("Início", QColor("#64748b")))
        gap = 15
        widths = [20 + painter.fontMetrics().horizontalAdvance(label) for label, _ in labels]
        x = (self.width() - sum(widths) - gap * (len(labels) - 1)) / 2
        y = self.height() - 19
        for (label, color), width in zip(labels, widths):
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(Qt.NoBrush)
            if label == "Alvo":
                painter.drawRect(QRectF(x, y - 5, 10, 10))
            elif label == "Posição":
                painter.drawEllipse(QPointF(x + 5, y), 3.5, 3.5)
                painter.drawLine(QPointF(x - 1, y), QPointF(x + 11, y))
                painter.drawLine(QPointF(x + 5, y - 6), QPointF(x + 5, y + 6))
            else:
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x + 5, y), 2.5, 2.5)
            painter.setPen(QColor("#475569"))
            painter.drawText(QRectF(x + 17, y - 9, width - 17, 18), Qt.AlignVCenter, label)
            x += width + gap

    def _draw_static_annotations(self, painter: QPainter,
                                 points: list[tuple[float, float]], start: QPointF):
        # O início é rotulado ao lado para não ocupar o espaço do eixo Y.
        painter.setBrush(QColor("white"))
        painter.setPen(QPen(_AZUL, 2))
        painter.drawRect(QRectF(start.x() - 4, start.y() - 4, 8, 8))
        painter.drawText(QRectF(start.x() + 8, start.y() - 21, 44, 18), Qt.AlignLeft, "Início")

        # Uma seta fixa indica a orientação do percurso, sem animar progresso.
        before, tip = self._map_point(points[5]), self._map_point(points[6])
        angle = math.atan2(tip.y() - before.y(), tip.x() - before.x())
        left = QPointF(tip.x() - 9 * math.cos(angle - 0.5), tip.y() - 9 * math.sin(angle - 0.5))
        right = QPointF(tip.x() - 9 * math.cos(angle + 0.5), tip.y() - 9 * math.sin(angle + 0.5))
        painter.setBrush(_AZUL)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([tip, left, right]))

        painter.setPen(QColor("#475569"))
        footer = "Azul: referência  ·  Verde: registro" if self._samples else "Referência  ·  Sentido horário"
        painter.drawText(QRectF(8, self.height() - 30, self.width() - 16, 22), Qt.AlignCenter, footer)

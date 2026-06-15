"""
进度条绘制委托：用 QStyledItemDelegate 纯绘制替代 QProgressBar widget
彻底消除拖拽排序时的 widget 重建闪烁
"""
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionProgressBar, QApplication
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

from ..queue_models import TaskStatus


PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 100
STATUS_ROLE = Qt.ItemDataRole.UserRole + 101


class ProgressDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._margin = 2
        self._bar_height = 18

    def paint(self, painter: QPainter, option, index):
        progress = index.data(PROGRESS_ROLE)
        status = index.data(STATUS_ROLE)

        if progress is None or status is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        bar_rect = QRect(
            rect.left() + self._margin,
            rect.top() + (rect.height() - self._bar_height) // 2,
            rect.width() - self._margin * 2,
            self._bar_height,
        )

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())

        bg_color = QColor("#f0f0f0")
        if status == TaskStatus.COMPLETED.value:
            bar_color = QColor("#22c55e")
            text_color = QColor("#22c55e")
        elif status == TaskStatus.FAILED.value:
            bar_color = QColor("#ef4444")
            text_color = QColor("#ef4444")
        elif status == TaskStatus.CONVERTING.value:
            bar_color = QColor("#4a9eff")
            text_color = QColor("#ffffff")
        else:
            bar_color = QColor("#4a9eff")
            text_color = QColor("#555555")
            if status == TaskStatus.CANCELLED.value:
                bar_color = QColor("#9ca3af")
                text_color = QColor("#9ca3af")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(bar_rect, 3, 3)

        if progress > 0:
            fill_width = int(bar_rect.width() * min(progress / 100.0, 1.0))
            fill_rect = QRect(bar_rect.left(), bar_rect.top(), fill_width, bar_rect.height())
            painter.setBrush(bar_color)
            painter.drawRoundedRect(fill_rect, 3, 3)

        if status == TaskStatus.CONVERTING.value:
            text = f"{int(progress)}%"
            text_rect = bar_rect
        elif status == TaskStatus.COMPLETED:
            text = "完成"
            text_rect = bar_rect
        elif status == TaskStatus.FAILED:
            text = "失败"
            text_rect = bar_rect
        else:
            text = "等待"
            text_rect = bar_rect

        painter.setPen(QPen(text_color))
        font = QFont(option.font)
        font.setPointSizeF(font.pointSizeF() * 0.9)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(self._bar_height + self._margin * 2 + 4)
        return size

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QProgressBar, QAbstractItemView,
    QHeaderView, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QAction, QDrag, QDropEvent, QDragEnterEvent, QDragMoveEvent, QBrush, QColor

from ..queue_models import ConvertQueueTask, TaskStatus


PROGRESS_STYLE_DEFAULT = """
    QProgressBar {
        border: 1px solid #ddd;
        border-radius: 3px;
        text-align: center;
        height: 18px;
        margin: 2px;
        background: white;
    }
    QProgressBar::chunk {
        background: #4a9eff;
        border-radius: 2px;
    }
"""

PROGRESS_STYLE_COMPLETED = """
    QProgressBar {
        border: 1px solid #22c55e;
        border-radius: 3px;
        text-align: center;
        height: 18px;
        margin: 2px;
        background: white;
        color: #22c55e;
    }
    QProgressBar::chunk {
        background: #22c55e;
        border-radius: 2px;
    }
"""

PROGRESS_STYLE_FAILED = """
    QProgressBar {
        border: 1px solid #ef4444;
        border-radius: 3px;
        text-align: center;
        height: 18px;
        margin: 2px;
        background: white;
        color: #ef4444;
    }
    QProgressBar::chunk {
        background: #ef4444;
        border-radius: 2px;
    }
"""

_STATUS_STYLES = {
    TaskStatus.COMPLETED: PROGRESS_STYLE_COMPLETED,
    TaskStatus.FAILED: PROGRESS_STYLE_FAILED,
}


class DragDropTableWidget(QTableWidget):
    task_dropped = pyqtSignal(int, int)
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._drag_row = -1

    def startDrag(self, actions):
        self._drag_row = self.currentRow()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"task-row:{self._drag_row}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasText() and event.mimeData().text().startswith("task-row:"):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            files = []
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p and os.path.exists(p):
                    files.append(p)
            if files:
                self.files_dropped.emit(files)
                event.acceptProposedAction()
                return

        if event.mimeData().hasText():
            txt = event.mimeData().text()
            if txt.startswith("task-row:"):
                target_row = self.rowAt(event.position().toPoint().y())
                if target_row < 0:
                    target_row = self.rowCount()
                if self._drag_row >= 0 and self._drag_row != target_row:
                    self.task_dropped.emit(self._drag_row, target_row)
                event.acceptProposedAction()
                return
        event.ignore()


class TaskTableManager:
    def __init__(self, table: DragDropTableWidget):
        self._table = table
        self._task_id_to_row: dict = {}
        self._row_to_task_id: dict = {}
        self._row_task_ids: dict = {}
        self._setup_table()

    def _setup_table(self):
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "状态", "书名", "作者", "格式转换", "进度", "耗时", "错误信息"
        ])
        header = self._table.horizontalHeader()
        col_widths = [60, 220, 120, 110, 140, 80, 200]
        for i, w in enumerate(col_widths):
            self._table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    @property
    def table(self) -> DragDropTableWidget:
        return self._table

    def get_task_id_at_row(self, row: int) -> Optional[str]:
        return self._row_to_task_id.get(row)

    def get_row_for_task(self, task_id: str) -> Optional[int]:
        return self._task_id_to_row.get(task_id)

    def full_refresh(self, tasks: list):
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)

        self._task_id_to_row.clear()
        self._row_to_task_id.clear()
        self._row_task_ids.clear()
        self._table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            self._task_id_to_row[task.task_id] = row
            self._row_to_task_id[row] = task.task_id
            self._populate_row(row, task, force=True)

        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)

    def reorder_rows(self, source_row: int, target_row: int, tasks: list):
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)

        total = len(tasks)
        source_row = max(0, min(source_row, total - 1))
        target_row = max(0, min(target_row, total))
        if source_row == target_row or target_row == source_row + 1:
            self._table.blockSignals(False)
            self._table.setUpdatesEnabled(True)
            return

        source_widget = None
        source_items = []
        for col in range(self._table.columnCount()):
            item = self._table.takeItem(source_row, col)
            source_items.append(item)
            if col == 4:
                source_widget = self._table.cellWidget(source_row, 4)
                self._table.removeCellWidget(source_row, 4)

        if target_row > source_row:
            target_row -= 1

        self._table.insertRow(target_row)
        for col in range(self._table.columnCount()):
            if source_items[col]:
                self._table.setItem(target_row, col, source_items[col])
        if source_widget:
            self._table.setCellWidget(target_row, 4, source_widget)

        self._table.removeRow(source_row)

        self._task_id_to_row.clear()
        self._row_to_task_id.clear()
        self._row_task_ids.clear()
        for row, task in enumerate(tasks):
            self._task_id_to_row[task.task_id] = row
            self._row_to_task_id[row] = task.task_id
            self._row_task_ids[row] = task.task_id

        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)

    def update_task_row(self, task_id: str, task: ConvertQueueTask):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            return False
        self._populate_row(row, task, force=False)
        return True

    def update_progress_only(self, task_id: str, progress: int, task: ConvertQueueTask):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            return
        progress_widget = self._table.cellWidget(row, 4)
        if isinstance(progress_widget, QProgressBar):
            progress_widget.setValue(progress)
            progress_widget.setFormat(f"{progress}%")
        self._update_status_cell(row, task)

    def _populate_row(self, row: int, task: ConvertQueueTask, force: bool = False):
        existing_tid = self._row_task_ids.get(row)
        same_task = (existing_tid == task.task_id)
        self._row_task_ids[row] = task.task_id

        self._update_status_cell(row, task)
        self._update_text_cells(row, task)
        self._update_progress_widget(row, task, same_task and not force)
        self._update_duration_cell(row, task)
        self._update_error_cell(row, task)

    def _update_status_cell(self, row: int, task: ConvertQueueTask):
        existing = self._table.item(row, 0)
        new_text = f"{task.status.icon} {task.status.display_name}"
        if existing and existing.text() == new_text:
            return
        status_item = QTableWidgetItem(new_text)
        color = QColor(task.status.color)
        status_item.setForeground(QBrush(color))
        f = status_item.font()
        f.setBold(True)
        status_item.setFont(f)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setData(Qt.ItemDataRole.UserRole, task.task_id)
        self._table.setItem(row, 0, status_item)

    def _update_text_cells(self, row: int, task: ConvertQueueTask):
        title_item = self._table.item(row, 1)
        new_title = task.display_name
        if not title_item or title_item.text() != new_title:
            item = QTableWidgetItem(new_title)
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            item.setToolTip(task.input_path)
            self._table.setItem(row, 1, item)

        author_item = self._table.item(row, 2)
        new_author = task.book_author or "-"
        if not author_item or author_item.text() != new_author:
            self._table.setItem(row, 2, QTableWidgetItem(new_author))

        fmt_text = f"{task.source_format.upper()} → {task.output_format.upper()}"
        fmt_item = self._table.item(row, 3)
        if not fmt_item or fmt_item.text() != fmt_text:
            item = QTableWidgetItem(fmt_text)
            item.setForeground(QBrush(QColor("#4a9eff")))
            self._table.setItem(row, 3, item)

    def _update_progress_widget(self, row: int, task: ConvertQueueTask, reuse: bool):
        progress_val = task.progress if task.progress > 0 else (
            100 if task.status == TaskStatus.COMPLETED else 0
        )
        if task.status == TaskStatus.CONVERTING:
            progress_format = f"{task.progress}%"
        elif task.status == TaskStatus.COMPLETED:
            progress_format = "100%"
        else:
            progress_format = "等待"

        target_style = _STATUS_STYLES.get(task.status, PROGRESS_STYLE_DEFAULT)

        if reuse:
            existing = self._table.cellWidget(row, 4)
            if isinstance(existing, QProgressBar):
                existing.setValue(progress_val)
                existing.setFormat(progress_format)
                existing.setStyleSheet(target_style)
                return

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(progress_val)
        progress_bar.setTextVisible(True)
        progress_bar.setFormat(progress_format)
        progress_bar.setStyleSheet(target_style)
        self._table.setCellWidget(row, 4, progress_bar)

    def _update_duration_cell(self, row: int, task: ConvertQueueTask):
        duration_text = task.formatted_duration if task.duration_seconds > 0 else (
            "-" if task.status == TaskStatus.PENDING else "进行中"
        )
        existing = self._table.item(row, 5)
        if existing and existing.text() == duration_text:
            return
        duration_item = QTableWidgetItem(duration_text)
        duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 5, duration_item)

    def _update_error_cell(self, row: int, task: ConvertQueueTask):
        error_text = ""
        if task.status == TaskStatus.FAILED and task.error_message:
            error_text = task.error_message.split("\n")[0][:80]
            if len(task.error_message) > 80:
                error_text += "..."
        elif task.status == TaskStatus.CANCELLED:
            error_text = "用户取消"
        existing = self._table.item(row, 6)
        if existing and existing.text() == error_text:
            return
        error_item = QTableWidgetItem(error_text)
        error_item.setForeground(QBrush(QColor("#ef4444")))
        error_item.setToolTip(task.error_message)
        self._table.setItem(row, 6, error_item)


def show_context_menu(table: DragDropTableWidget, pos, task: ConvertQueueTask,
                      task_id: str, queue_manager, parent_widget):
    menu = QMenu(parent_widget)
    menu.setStyleSheet("QMenu{padding:4px}QAction{padding:6px 24px}")

    if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        retry_action = QAction("🔄 重试任务", parent_widget)
        retry_action.triggered.connect(lambda: queue_manager.retry_task(task_id))
        menu.addAction(retry_action)
        menu.addSeparator()

    if task.status in (TaskStatus.PENDING, TaskStatus.CONVERTING):
        cancel_action = QAction("🚫 取消此任务", parent_widget)
        cancel_action.triggered.connect(lambda: queue_manager.cancel_task(task_id))
        menu.addAction(cancel_action)

    open_dir_action = QAction("📂 打开输出目录", parent_widget)
    open_dir_action.triggered.connect(lambda: _open_output_dir(task))
    if not task.output_path:
        open_dir_action.setEnabled(False)
    menu.addAction(open_dir_action)

    view_error_action = QAction("❌ 查看错误详情", parent_widget)
    view_error_action.triggered.connect(lambda: _view_error(task, parent_widget))
    if task.status != TaskStatus.FAILED or not task.error_message:
        view_error_action.setEnabled(False)
    menu.addAction(view_error_action)

    menu.addSeparator()

    remove_action = QAction("🗑️ 从队列移除", parent_widget)
    remove_action.triggered.connect(lambda: queue_manager.remove_task(task_id))
    menu.addAction(remove_action)

    menu.exec(table.viewport().mapToGlobal(pos))


def _open_output_dir(task: ConvertQueueTask):
    path = task.output_path or task.resolved_output_path
    if not path:
        return
    dir_path = str(Path(path).parent)
    if os.path.exists(dir_path):
        import subprocess
        if os.name == "nt":
            subprocess.Popen(f'explorer "{dir_path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", dir_path])
        else:
            subprocess.Popen(["xdg-open", dir_path])


def _view_error(task: ConvertQueueTask, parent):
    if not task.error_message:
        return
    QMessageBox.warning(
        parent, "错误详情",
        f"书籍: {task.display_name}\n\n错误信息:\n{task.error_message}"
    )

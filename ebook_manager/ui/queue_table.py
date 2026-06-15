import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QAction, QDrag, QDropEvent, QDragEnterEvent, QDragMoveEvent, QBrush, QColor

from ..queue_models import ConvertQueueTask, TaskStatus
from .progress_delegate import ProgressDelegate, PROGRESS_ROLE, STATUS_ROLE


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
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
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
    COL_STATUS = 0
    COL_TITLE = 1
    COL_AUTHOR = 2
    COL_FMT = 3
    COL_PROGRESS = 4
    COL_DURATION = 5
    COL_ERROR = 6

    def __init__(self, table: DragDropTableWidget):
        self._table = table
        self._task_id_to_row: dict = {}
        self._row_to_task_id: dict = {}
        self._progress_delegate = ProgressDelegate()
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
        self._table.setItemDelegateForColumn(self.COL_PROGRESS, self._progress_delegate)
        self._table.verticalHeader().setDefaultSectionSize(28)

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
        self._table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            self._task_id_to_row[task.task_id] = row
            self._row_to_task_id[row] = task.task_id
            self._populate_row(row, task)

        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)
        self._table.viewport().update()

    def reorder_rows(self, source_row: int, target_row: int, tasks: list):
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)

        total = len(tasks)
        source_row = max(0, min(source_row, total - 1))
        target_row = max(0, min(target_row, total - 1))

        if source_row == target_row:
            self._table.blockSignals(False)
            self._table.setUpdatesEnabled(True)
            return

        step = 1 if target_row > source_row else -1
        current = source_row
        while current != target_row:
            next_row = current + step
            self._swap_rows(current, next_row)
            current = next_row

        self._task_id_to_row.clear()
        self._row_to_task_id.clear()
        for row, task in enumerate(tasks):
            self._task_id_to_row[task.task_id] = row
            self._row_to_task_id[row] = task.task_id

        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)
        self._table.viewport().update()

    def _swap_rows(self, row_a: int, row_b: int):
        for col in range(self._table.columnCount()):
            item_a = self._table.takeItem(row_a, col)
            item_b = self._table.takeItem(row_b, col)
            if item_a:
                self._table.setItem(row_b, col, item_a)
            if item_b:
                self._table.setItem(row_a, col, item_b)

    def update_task_row(self, task_id: str, task: ConvertQueueTask):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            return False
        self._populate_row(row, task)
        return True

    def update_progress_only(self, task_id: str, progress: int, task: ConvertQueueTask):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            return
        item = self._table.item(row, self.COL_PROGRESS)
        if item is None:
            item = QTableWidgetItem()
            self._table.setItem(row, self.COL_PROGRESS, item)
        item.setData(PROGRESS_ROLE, progress)
        item.setData(STATUS_ROLE, task.status.value)
        self._update_status_cell(row, task)
        self._table.update(self._table.model().index(row, self.COL_PROGRESS))

    def _populate_row(self, row: int, task: ConvertQueueTask):
        self._update_status_cell(row, task)
        self._update_text_cells(row, task)
        self._update_progress_cell(row, task)
        self._update_duration_cell(row, task)
        self._update_error_cell(row, task)

    def _update_status_cell(self, row: int, task: ConvertQueueTask):
        new_text = f"{task.status.icon} {task.status.display_name}"
        item = self._table.item(row, self.COL_STATUS)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            self._table.setItem(row, self.COL_STATUS, item)
        if item.text() != new_text:
            item.setText(new_text)
            color = QColor(task.status.color)
            item.setForeground(QBrush(color))

    def _update_text_cells(self, row: int, task: ConvertQueueTask):
        new_title = task.display_name
        title_item = self._table.item(row, self.COL_TITLE)
        if title_item is None or title_item.text() != new_title:
            item = QTableWidgetItem(new_title)
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            item.setToolTip(task.input_path)
            self._table.setItem(row, self.COL_TITLE, item)

        new_author = task.book_author or "-"
        author_item = self._table.item(row, self.COL_AUTHOR)
        if author_item is None or author_item.text() != new_author:
            self._table.setItem(row, self.COL_AUTHOR, QTableWidgetItem(new_author))

        fmt_text = f"{task.source_format.upper()} → {task.output_format.upper()}"
        fmt_item = self._table.item(row, self.COL_FMT)
        if fmt_item is None or fmt_item.text() != fmt_text:
            item = QTableWidgetItem(fmt_text)
            item.setForeground(QBrush(QColor("#4a9eff")))
            self._table.setItem(row, self.COL_FMT, item)

    def _update_progress_cell(self, row: int, task: ConvertQueueTask):
        progress_val = task.progress if task.progress > 0 else (
            100 if task.status == TaskStatus.COMPLETED else 0
        )
        item = self._table.item(row, self.COL_PROGRESS)
        if item is None:
            item = QTableWidgetItem()
            self._table.setItem(row, self.COL_PROGRESS, item)
        item.setData(PROGRESS_ROLE, progress_val)
        item.setData(STATUS_ROLE, task.status.value)

    def _update_duration_cell(self, row: int, task: ConvertQueueTask):
        duration_text = task.formatted_duration if task.duration_seconds > 0 else (
            "-" if task.status == TaskStatus.PENDING else "进行中"
        )
        item = self._table.item(row, self.COL_DURATION)
        if item is None or item.text() != duration_text:
            duration_item = QTableWidgetItem(duration_text)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, self.COL_DURATION, duration_item)

    def _update_error_cell(self, row: int, task: ConvertQueueTask):
        error_text = ""
        if task.status == TaskStatus.FAILED and task.error_message:
            error_text = task.error_message.split("\n")[0][:80]
            if len(task.error_message) > 80:
                error_text += "..."
        elif task.status == TaskStatus.CANCELLED:
            error_text = "用户取消"
        item = self._table.item(row, self.COL_ERROR)
        if item is None or item.text() != error_text:
            error_item = QTableWidgetItem(error_text)
            error_item.setForeground(QBrush(QColor("#ef4444")))
            error_item.setToolTip(task.error_message)
            self._table.setItem(row, self.COL_ERROR, error_item)


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

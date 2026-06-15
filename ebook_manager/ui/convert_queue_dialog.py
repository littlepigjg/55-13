import os
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QFileDialog, QGroupBox, QTableWidget,
    QTableWidgetItem, QLabel, QProgressBar, QAbstractItemView,
    QMenu, QHeaderView, QMessageBox, QWidget, QToolBar, QStatusBar,
    QAbstractScrollArea, QSplitter, QTextEdit, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QTimer, QSize
from PyQt6.QtGui import QAction, QIcon, QDrag, QDropEvent, QDragEnterEvent, QDragMoveEvent, QBrush, QColor, QFont

from ..models import BookMeta
from ..queue_models import ConvertQueueTask, TaskStatus, ConvertPreset
from ..queue_manager import QueueManager


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


class ConvertQueueDialog(QDialog):
    def __init__(self, books: list, queue_manager: QueueManager, parent=None):
        super().__init__(parent)
        self._books = books
        self._qm = queue_manager
        self._task_id_to_row: dict = {}
        self._row_to_task_id: dict = {}
        self.setWindowTitle("📚 批量格式转换队列")
        self.setMinimumSize(950, 650)
        self._init_ui()
        self._connect_signals()
        self._load_initial_tasks()
        self._refresh_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top_bar = QHBoxLayout()

        add_btn = QPushButton("➕ 添加书籍")
        add_btn.clicked.connect(self._on_add_books)
        top_bar.addWidget(add_btn)

        add_files_btn = QPushButton("📁 添加文件...")
        add_files_btn.clicked.connect(self._on_add_files)
        top_bar.addWidget(add_files_btn)

        add_dir_btn = QPushButton("📂 添加目录...")
        add_dir_btn.clicked.connect(self._on_add_directory)
        top_bar.addWidget(add_dir_btn)

        top_bar.addStretch()

        clear_btn = QPushButton("🗑️ 清空已完成")
        clear_btn.clicked.connect(self._on_clear_completed)
        clear_btn.setStyleSheet("QPushButton{color:#666}")
        top_bar.addWidget(clear_btn)

        layout.addLayout(top_bar)

        settings_group = QGroupBox("转换设置（应用于新添加的任务）")
        settings_layout = QFormLayout(settings_group)

        self.preset_combo = QComboBox()
        for preset in self._qm.preset_manager.get_all():
            self.preset_combo.addItem(
                f"{preset.name} - {preset.description}" if preset.description else preset.name,
                preset.name
            )
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        settings_layout.addRow("转换预设:", self.preset_combo)

        fmt_row = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(120)
        fmt_row.addWidget(self.format_combo)
        fmt_row.addStretch()
        settings_layout.addRow("目标格式:", fmt_row)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认保存到原文件所在目录")
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton("浏览...")
        output_browse.clicked.connect(self._browse_output)
        output_row.addWidget(output_browse)
        settings_layout.addRow("输出目录:", output_row)

        retry_row = QHBoxLayout()
        self.retry_check = QCheckBox("失败自动重试")
        self.retry_check.setChecked(True)
        retry_row.addWidget(self.retry_check)
        retry_info = QLabel(f"（最大并发: {self._qm.max_concurrent} 个任务）")
        retry_info.setStyleSheet("color:#888")
        retry_row.addWidget(retry_info)
        retry_row.addStretch()
        settings_layout.addRow("", retry_row)

        layout.addWidget(settings_group)

        table_group = QGroupBox("转换队列（拖拽调整顺序 | 右键更多操作）")
        table_layout = QVBoxLayout(table_group)

        self.table = DragDropTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "状态", "书名", "作者", "格式转换", "进度", "耗时", "错误信息"
        ])
        header = self.table.horizontalHeader()
        col_widths = [60, 220, 120, 110, 140, 80, 200]
        for i, w in enumerate(col_widths):
            self.table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.task_dropped.connect(self._on_task_dropped)
        self.table.files_dropped.connect(self._on_files_dropped)
        table_layout.addWidget(self.table)

        layout.addWidget(table_group)

        progress_group = QGroupBox("总体进度")
        progress_layout = QVBoxLayout(progress_group)

        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("总体进度: %p%")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
                height: 22px;
                background: white;
            }
            QProgressBar::chunk {
                background: linear-gradient(90deg, #4a9eff, #6bb3ff);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.overall_progress)

        self.stats_label = QLabel("队列中暂无任务")
        self.stats_label.setStyleSheet("color:#555;padding:2px 0")
        progress_layout.addWidget(self.stats_label)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color:#888;font-size:12px")
        progress_layout.addWidget(self.detail_label)

        layout.addWidget(progress_group)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(100)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        self.log_view.setVisible(False)
        toggle_log = QPushButton("📜 显示/隐藏日志")
        toggle_log.setStyleSheet("QPushButton{color:#666;font-size:12px}")
        toggle_log.clicked.connect(lambda: self.log_view.setVisible(not self.log_view.isVisible()))

        bottom_bar = QHBoxLayout()
        bottom_bar.addWidget(toggle_log)
        bottom_bar.addStretch()

        cancel_all_btn = QPushButton("全部取消")
        cancel_all_btn.setStyleSheet("QPushButton{color:#993333}")
        cancel_all_btn.clicked.connect(self._on_cancel_all)
        bottom_bar.addWidget(cancel_all_btn)

        close_btn = QPushButton("关闭窗口")
        close_btn.clicked.connect(self.close)
        bottom_bar.addWidget(close_btn)

        layout.addWidget(self.log_view)
        layout.addLayout(bottom_bar)

        self._on_preset_changed(0)

        if not self._books:
            self._append_log("💡 提示: 可将电子书文件拖入窗口添加到队列")

    def _connect_signals(self):
        self._qm.task_added.connect(self._on_task_added)
        self._qm.task_removed.connect(self._on_task_removed)
        self._qm.task_status_changed.connect(self._on_task_status_changed)
        self._qm.task_progress_changed.connect(self._on_task_progress_changed)
        self._qm.tasks_changed.connect(self._refresh_stats)
        self._qm.overall_progress_changed.connect(self._on_overall_progress)
        self._qm.log_message.connect(self._append_log)

    def _load_initial_tasks(self):
        if not self._books:
            return
        preset_name = self.preset_combo.currentData() or "默认"
        output_dir = self.output_edit.text().strip() or None
        output_format = self.format_combo.currentData() or "epub"
        max_retries = 1 if self.retry_check.isChecked() else 0

        tasks = []
        for book in self._books:
            if not isinstance(book, BookMeta):
                continue
            source_fmt = book.file_format.lower()
            targets = self._get_supported_targets(source_fmt)
            if output_format.lower() not in targets and targets:
                task_fmt = next(iter(targets))
            else:
                task_fmt = output_format.lower()

            preset = self._qm.preset_manager.get(preset_name)
            extra_args = list(preset.extra_args) if preset else []

            task = ConvertQueueTask(
                input_path=book.file_path,
                output_format=task_fmt,
                output_dir=output_dir,
                book_title=book.title,
                book_author=book.author,
                source_format=source_fmt,
                file_size=book.file_size,
                preset_name=preset_name,
                extra_args=extra_args,
                max_retries=max_retries,
            )
            tasks.append(task)

        if tasks:
            self._qm.add_tasks(tasks)

    def _on_preset_changed(self, index: int):
        preset_name = self.preset_combo.currentData()
        preset = self._qm.preset_manager.get(preset_name)
        if not preset:
            return
        self.format_combo.clear()
        for book in self._books:
            if isinstance(book, BookMeta):
                targets = self._get_supported_targets(book.file_format.lower())
                for fmt in sorted(targets):
                    if self.format_combo.findText(fmt.upper()) < 0:
                        self.format_combo.addItem(fmt.upper(), fmt)
        if self.format_combo.count() == 0:
            for fmt in ["epub", "mobi", "pdf", "azw3", "txt"]:
                self.format_combo.addItem(fmt.upper(), fmt)
        idx = self.format_combo.findData(preset.output_format)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)

    def _get_supported_targets(self, source_fmt: str) -> set:
        from ..converter import SUPPORTED_CONVERSIONS
        return set(SUPPORTED_CONVERSIONS.get(source_fmt.lower(), set()))

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.output_edit.setText(d)

    def _on_add_books(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择电子书文件", "",
            "电子书 (*.epub *.mobi *.pdf *.azw3 *.txt);;所有文件 (*)"
        )
        if files:
            self._add_files_to_queue(files)

    def _on_add_files(self):
        self._on_add_books()

    def _on_add_directory(self):
        d = QFileDialog.getExistingDirectory(self, "选择电子书目录")
        if d:
            from ..scanner import BookshelfScanner
            scanner = BookshelfScanner()
            files = scanner.scan_directory(d)
            if files:
                self._add_files_to_queue(files)

    def _on_files_dropped(self, files: list):
        all_files = []
        for f in files:
            if os.path.isdir(f):
                from ..scanner import BookshelfScanner
                scanner = BookshelfScanner()
                all_files.extend(scanner.scan_directory(f))
            else:
                all_files.append(f)
        if all_files:
            self._add_files_to_queue(all_files)

    def _add_files_to_queue(self, files: list):
        preset_name = self.preset_combo.currentData() or "默认"
        preset = self._qm.preset_manager.get(preset_name)
        output_dir = self.output_edit.text().strip() or None
        output_format = self.format_combo.currentData() or (preset.output_format if preset else "epub")
        max_retries = 1 if self.retry_check.isChecked() else 0

        from ..metadata_parser import MetadataParser
        parser = MetadataParser()
        tasks = []
        for f in files:
            try:
                book = parser.parse(f)
            except Exception:
                book = BookMeta(
                    file_path=f,
                    file_format=Path(f).suffix.lstrip("."),
                    title=Path(f).stem,
                )
            source_fmt = book.file_format.lower()
            targets = self._get_supported_targets(source_fmt)
            task_fmt = output_format
            if task_fmt.lower() not in targets and targets:
                task_fmt = next(iter(targets))

            extra_args = list(preset.extra_args) if preset else []
            task = ConvertQueueTask(
                input_path=book.file_path,
                output_format=task_fmt.lower(),
                output_dir=output_dir,
                book_title=book.title,
                book_author=book.author,
                source_format=source_fmt,
                file_size=book.file_size,
                preset_name=preset_name,
                extra_args=extra_args,
                max_retries=max_retries,
            )
            tasks.append(task)

        if tasks:
            self._qm.add_tasks(tasks)
            self._append_log(f"✅ 添加了 {len(tasks)} 个任务到队列")

    def _on_clear_completed(self):
        count = len([t for t in self._qm.get_tasks()
                     if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)])
        if count == 0:
            return
        reply = QMessageBox.question(
            self, "确认", f"确定要清空 {count} 个已结束的任务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._qm.clear_completed()

    def _on_cancel_all(self):
        pending_count = len([t for t in self._qm.get_tasks()
                             if t.status in (TaskStatus.PENDING, TaskStatus.CONVERTING)])
        if pending_count == 0:
            return
        reply = QMessageBox.question(
            self, "确认", f"确定要取消 {pending_count} 个进行中的任务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._qm.cancel_all()

    def _on_task_dropped(self, source_row: int, target_row: int):
        if source_row < 0 or source_row >= self.table.rowCount():
            return
        task_id = self._row_to_task_id.get(source_row)
        if not task_id:
            return
        self._qm.move_task(task_id, target_row)
        QTimer.singleShot(0, self._refresh_table)

    def _show_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        task_id = self._row_to_task_id.get(row)
        task = self._qm.get_task(task_id) if task_id else None
        if not task:
            return

        menu = QMenu(self)
        menu.setStyleSheet("QMenu{padding:4px}QAction{padding:6px 24px}")

        if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            retry_action = QAction(f"🔄 重试任务", self)
            retry_action.triggered.connect(lambda: self._qm.retry_task(task_id))
            menu.addAction(retry_action)
            menu.addSeparator()

        if task.status in (TaskStatus.PENDING, TaskStatus.CONVERTING):
            cancel_action = QAction("🚫 取消此任务", self)
            cancel_action.triggered.connect(lambda: self._qm.cancel_task(task_id))
            menu.addAction(cancel_action)

        open_dir_action = QAction("📂 打开输出目录", self)
        open_dir_action.triggered.connect(lambda: self._open_output_dir(task))
        if not task.output_path:
            open_dir_action.setEnabled(False)
        menu.addAction(open_dir_action)

        view_error_action = QAction("❌ 查看错误详情", self)
        view_error_action.triggered.connect(lambda: self._view_error(task))
        if task.status != TaskStatus.FAILED or not task.error_message:
            view_error_action.setEnabled(False)
        menu.addAction(view_error_action)

        menu.addSeparator()

        remove_action = QAction("🗑️ 从队列移除", self)
        remove_action.triggered.connect(lambda: self._qm.remove_task(task_id))
        menu.addAction(remove_action)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_output_dir(self, task: ConvertQueueTask):
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

    def _view_error(self, task: ConvertQueueTask):
        if not task.error_message:
            return
        QMessageBox.warning(
            self, "错误详情",
            f"书籍: {task.display_name}\n\n错误信息:\n{task.error_message}"
        )

    def _on_task_added(self, task_id: str):
        self._refresh_table()

    def _on_task_removed(self, task_id: str):
        self._refresh_table()

    def _on_task_status_changed(self, task_id: str, status: str):
        self._update_task_row(task_id)

    def _on_task_progress_changed(self, task_id: str, progress: int):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            return
        progress_widget = self.table.cellWidget(row, 4)
        if isinstance(progress_widget, QProgressBar):
            progress_widget.setValue(progress)
        task = self._qm.get_task(task_id)
        if task and task.status == TaskStatus.CONVERTING:
            self._update_status_cell(row, task)

    def _on_overall_progress(self, pct: int, total: int, completed: int,
                              converting: int, detail: str):
        self.overall_progress.setValue(pct)
        if detail:
            self.detail_label.setText(detail)

    def _refresh_stats(self):
        tasks = self._qm.get_tasks()
        total = len(tasks)
        if total == 0:
            self.stats_label.setText("队列中暂无任务")
            return
        pending = sum(1 for t in tasks if t.status == TaskStatus.PENDING)
        converting = sum(1 for t in tasks if t.status == TaskStatus.CONVERTING)
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        cancelled = sum(1 for t in tasks if t.status == TaskStatus.CANCELLED)
        self.stats_label.setText(
            f"共 {total} 个任务 | "
            f"⏳ 排队: {pending} | "
            f"⚙️ 转换中: {converting} | "
            f"✅ 完成: {completed} | "
            f"❌ 失败: {failed}"
            + (f" | 🚫 取消: {cancelled}" if cancelled > 0 else "")
        )

    def _refresh_table(self):
        tasks = self._qm.get_tasks()
        self.table.blockSignals(True)
        self.table.setRowCount(len(tasks))
        self._task_id_to_row.clear()
        self._row_to_task_id.clear()

        for row, task in enumerate(tasks):
            self._task_id_to_row[task.task_id] = row
            self._row_to_task_id[row] = task.task_id
            self._populate_row(row, task)

        self.table.blockSignals(False)
        self._refresh_stats()

    def _update_task_row(self, task_id: str):
        row = self._task_id_to_row.get(task_id)
        if row is None or row < 0:
            self._refresh_table()
            return
        task = self._qm.get_task(task_id)
        if not task:
            self._refresh_table()
            return
        self._populate_row(row, task)

    def _populate_row(self, row: int, task: ConvertQueueTask):
        self._update_status_cell(row, task)

        title_item = QTableWidgetItem(task.display_name)
        title_item.setData(Qt.ItemDataRole.UserRole, task.task_id)
        title_item.setToolTip(task.input_path)
        self.table.setItem(row, 1, title_item)

        author_item = QTableWidgetItem(task.book_author or "-")
        self.table.setItem(row, 2, author_item)

        fmt_text = f"{task.source_format.upper()} → {task.output_format.upper()}"
        fmt_item = QTableWidgetItem(fmt_text)
        fmt_item.setForeground(QBrush(QColor("#4a9eff")))
        self.table.setItem(row, 3, fmt_item)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(task.progress if task.progress > 0 else (
            100 if task.status == TaskStatus.COMPLETED else 0
        ))
        progress_bar.setTextVisible(True)
        progress_bar.setFormat(f"{task.progress}%" if task.status == TaskStatus.CONVERTING else (
            "100%" if task.status == TaskStatus.COMPLETED else "等待"
        ))
        progress_bar.setStyleSheet("""
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
        """)
        if task.status == TaskStatus.COMPLETED:
            progress_bar.setStyleSheet("""
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
            """)
        elif task.status == TaskStatus.FAILED:
            progress_bar.setStyleSheet("""
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
            """)
        self.table.setCellWidget(row, 4, progress_bar)

        duration_text = task.formatted_duration if task.duration_seconds > 0 else (
            "-" if task.status == TaskStatus.PENDING else "进行中"
        )
        duration_item = QTableWidgetItem(duration_text)
        duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 5, duration_item)

        error_text = ""
        if task.status == TaskStatus.FAILED and task.error_message:
            error_text = task.error_message.split("\n")[0][:80]
            if len(task.error_message) > 80:
                error_text += "..."
        elif task.status == TaskStatus.CANCELLED:
            error_text = "用户取消"
        error_item = QTableWidgetItem(error_text)
        error_item.setForeground(QBrush(QColor("#ef4444")))
        error_item.setToolTip(task.error_message)
        self.table.setItem(row, 6, error_item)

    def _update_status_cell(self, row: int, task: ConvertQueueTask):
        status_item = QTableWidgetItem(f"{task.status.icon} {task.status.display_name}")
        color = QColor(task.status.color)
        status_item.setForeground(QBrush(color))
        f = status_item.font()
        f.setBold(True)
        status_item.setFont(f)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setData(Qt.ItemDataRole.UserRole, task.task_id)
        self.table.setItem(row, 0, status_item)

    def _append_log(self, msg: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{ts}] {msg}")
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        self._qm.save_queue()
        super().closeEvent(event)

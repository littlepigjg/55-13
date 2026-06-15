import os
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QGroupBox, QLabel, QProgressBar, QMessageBox, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer

from ..models import BookMeta
from ..queue_models import ConvertQueueTask, TaskStatus
from ..queue_manager import QueueManager
from .queue_table import DragDropTableWidget, TaskTableManager, show_context_menu
from .queue_settings import QueueSettingsPanel


class ConvertQueueDialog(QDialog):
    def __init__(self, books: list, queue_manager: QueueManager, parent=None):
        super().__init__(parent)
        self._books = books
        self._qm = queue_manager
        self.setWindowTitle("📚 批量格式转换队列")
        self.setMinimumSize(950, 650)
        self._init_ui()
        self._connect_signals()
        self._load_initial_tasks()
        self._table_mgr.full_refresh(self._qm.get_tasks())

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

        self.settings = QueueSettingsPanel(self._qm)
        self.settings.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.settings.sync_preset_requested.connect(self._on_sync_preset)
        layout.addWidget(self.settings)

        table_group = QGroupBox("转换队列（拖拽调整顺序 | 右键更多操作）")
        table_layout = QVBoxLayout(table_group)
        self._drag_table = DragDropTableWidget()
        self._table_mgr = TaskTableManager(self._drag_table)
        self._drag_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._drag_table.customContextMenuRequested.connect(self._show_context_menu)
        self._drag_table.task_dropped.connect(self._on_task_dropped)
        self._drag_table.files_dropped.connect(self._on_files_dropped)
        table_layout.addWidget(self._drag_table)
        layout.addWidget(table_group)

        progress_group = QGroupBox("总体进度")
        progress_layout = QVBoxLayout(progress_group)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("总体进度: %p%")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd; border-radius: 4px;
                text-align: center; height: 22px; background: white;
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
                background: #1e1e1e; color: #d4d4d4;
                font-family: Consolas, monospace; font-size: 11px;
                border: 1px solid #333; border-radius: 4px;
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

        self.settings.populate_format_combo(self._books)
        self.settings.update_preset_format()

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
        self.settings.sync_preset_requested.connect(self._on_sync_preset)
        self.settings.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

    def _load_initial_tasks(self):
        if not self._books:
            return
        preset_name = self.settings.get_preset_name()
        output_dir = self.settings.get_output_dir() or None
        output_format = self.settings.get_output_format()
        max_retries = 1 if self.settings.is_retry_enabled() else 0
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
        preset_name = self.settings.get_preset_name()
        preset = self._qm.preset_manager.get(preset_name)
        if not preset:
            return
        self.settings.populate_format_combo(self._books)
        self.settings.update_preset_format()

    def _on_sync_preset(self):
        preset_name = self.settings.get_preset_name()
        output_dir = self.settings.get_output_dir()
        output_format = self.settings.get_output_format()
        count = self._qm.apply_preset_to_all(
            preset_name, output_dir, output_format, sync_output_dir=True
        )
        if count > 0:
            dir_info = f"，输出目录: {output_dir if output_dir else '默认'}"
            self._append_log(
                f"🔄 已将预设「{preset_name}」同步到 {count} 个未完成任务"
                f"（格式: {output_format.upper()}{dir_info}）"
            )
            self._table_mgr.full_refresh(self._qm.get_tasks())
        else:
            self._append_log("ℹ️ 没有需要同步的未完成任务")

    def _get_supported_targets(self, source_fmt: str) -> set:
        from ..converter import SUPPORTED_CONVERSIONS
        return set(SUPPORTED_CONVERSIONS.get(source_fmt.lower(), set()))

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
        preset_name = self.settings.get_preset_name()
        preset = self._qm.preset_manager.get(preset_name)
        output_dir = self.settings.get_output_dir() or None
        output_format = self.settings.get_output_format() or (preset.output_format if preset else "epub")
        max_retries = 1 if self.settings.is_retry_enabled() else 0

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
        if source_row < 0 or source_row >= self._drag_table.rowCount():
            return
        task_id = self._table_mgr.get_task_id_at_row(source_row)
        if not task_id:
            return
        self._qm.move_task(task_id, target_row)
        self._table_mgr.reorder_rows(source_row, target_row, self._qm.get_tasks())

    def _show_context_menu(self, pos):
        row = self._drag_table.rowAt(pos.y())
        if row < 0:
            return
        task_id = self._table_mgr.get_task_id_at_row(row)
        task = self._qm.get_task(task_id) if task_id else None
        if not task:
            return
        show_context_menu(self._drag_table, pos, task, task_id, self._qm, self)

    def _on_task_added(self, task_id: str):
        self._table_mgr.full_refresh(self._qm.get_tasks())

    def _on_task_removed(self, task_id: str):
        self._table_mgr.full_refresh(self._qm.get_tasks())

    def _on_task_status_changed(self, task_id: str, status: str):
        task = self._qm.get_task(task_id)
        if not task:
            return
        if not self._table_mgr.update_task_row(task_id, task):
            self._table_mgr.full_refresh(self._qm.get_tasks())

    def _on_task_progress_changed(self, task_id: str, progress: int):
        task = self._qm.get_task(task_id)
        if task and task.status == TaskStatus.CONVERTING:
            self._table_mgr.update_progress_only(task_id, progress, task)

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

    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{ts}] {msg}")
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        self._qm.save_queue()
        super().closeEvent(event)

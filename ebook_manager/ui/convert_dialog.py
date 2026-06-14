import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QFileDialog, QGroupBox, QListWidget,
    QLabel, QDialogButtonBox, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ..models import BookMeta
from ..converter import FormatConverter, ConversionTask


class ConvertDialog(QDialog):
    def __init__(self, books: list, converter: FormatConverter, parent=None):
        super().__init__(parent)
        self._books = books
        self._converter = converter
        self._tasks: list = []
        self.setWindowTitle("批量格式转换")
        self.setMinimumSize(550, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(f"共选择 {len(self._books)} 本书进行转换")
        info.setStyleSheet("font-weight:bold;font-size:13px")
        layout.addWidget(info)

        if not self._converter.is_calibre_available:
            warn = QLabel("⚠️ 未检测到 Calibre (ebook-convert)，格式转换功能将不可用。\n请安装 Calibre 并确保 ebook-convert 在系统 PATH 中。")
            warn.setStyleSheet("color:#cc0000;padding:8px;background:#fff0f0;border-radius:4px")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        settings_group = QGroupBox("转换设置")
        settings_layout = QFormLayout(settings_group)

        self.format_combo = QComboBox()
        available_formats = set()
        for book in self._books:
            targets = self._converter.get_supported_targets(book.file_format)
            available_formats.update(targets)
        for fmt in sorted(available_formats):
            self.format_combo.addItem(fmt.upper(), fmt)
        settings_layout.addRow("目标格式:", self.format_combo)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认保存到原文件所在目录")
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton("浏览...")
        output_browse.clicked.connect(self._browse_output)
        output_row.addWidget(output_browse)
        settings_layout.addRow("输出目录:", output_row)

        layout.addWidget(settings_group)

        list_group = QGroupBox("待转换文件")
        list_layout = QVBoxLayout(list_group)
        self.file_list = QListWidget()
        for book in self._books:
            self.file_list.addItem(
                f"[{book.file_format.upper()}] {book.title} - {book.author}"
            )
        list_layout.addWidget(self.file_list)
        layout.addWidget(list_group)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.convert_btn = QPushButton("🔄 开始转换")
        self.convert_btn.setStyleSheet(
            "QPushButton{background:#4a9eff;color:white;border:none;border-radius:4px;padding:8px 20px;font-weight:bold}"
            "QPushButton:hover{background:#3d8be0}"
        )
        self.convert_btn.setEnabled(self._converter.is_calibre_available and bool(available_formats))
        self.convert_btn.clicked.connect(self._start_convert)
        btn_row.addStretch()
        btn_row.addWidget(self.convert_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.output_edit.setText(d)

    def _start_convert(self):
        target_format = self.format_combo.currentData()
        if not target_format:
            return

        output_dir = self.output_edit.text().strip() or None
        self._tasks = []
        for book in self._books:
            task = ConversionTask(book.file_path, target_format, output_dir)
            self._tasks.append(task)

        self.convert_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self._tasks))

        self._convert_thread = ConvertThread(self._converter, self._tasks)
        self._convert_thread.progress.connect(self._on_progress)
        self._convert_thread.finished_signal.connect(self._on_finished)
        self._convert_thread.start()

    def _on_progress(self, current: int, total: int, path: str):
        self.progress.setValue(current)
        name = os.path.basename(path)
        self.status_label.setText(f"正在转换: {name}")

    def _on_finished(self, tasks: list):
        self.progress.setVisible(False)
        self.convert_btn.setEnabled(True)
        success = sum(1 for t in tasks if t.status == "completed")
        failed = sum(1 for t in tasks if t.status == "error")
        self.status_label.setText(f"转换完成: 成功 {success}, 失败 {failed}")
        if failed > 0:
            errors = "\n".join(
                f"• {os.path.basename(t.input_path)}: {t.error}"
                for t in tasks
                if t.status == "error"
            )
            QMessageBox.warning(self, "部分转换失败", errors)


class ConvertThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, converter: FormatConverter, tasks: list):
        super().__init__()
        self._converter = converter
        self._tasks = tasks

    def run(self):
        total = len(self._tasks)
        for i, task in enumerate(self._tasks):
            self.progress.emit(i + 1, total, task.input_path)
            self._converter.convert(task)
        self.finished_signal.emit(self._tasks)

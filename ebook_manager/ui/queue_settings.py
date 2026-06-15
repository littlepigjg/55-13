from PyQt6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QLineEdit, QPushButton,
    QHBoxLayout, QLabel, QCheckBox
)
from PyQt6.QtCore import pyqtSignal

from ..queue_models import ConvertPreset
from ..queue_manager import QueueManager


class QueueSettingsPanel(QGroupBox):
    sync_preset_requested = pyqtSignal()
    format_changed = pyqtSignal(str)

    def __init__(self, queue_manager: QueueManager, parent=None):
        super().__init__("转换设置（应用于新添加的任务）", parent)
        self._qm = queue_manager
        self._init_ui()

    def _init_ui(self):
        layout = QFormLayout(self)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        for preset in self._qm.preset_manager.get_all():
            self.preset_combo.addItem(
                f"{preset.name} - {preset.description}" if preset.description else preset.name,
                preset.name
            )
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self.preset_combo, 1)

        self.sync_btn = QPushButton("🔄 同步到全部")
        self.sync_btn.setToolTip("将当前预设的格式和参数同步到队列中所有未完成的任务")
        self.sync_btn.setStyleSheet(
            "QPushButton{background:#ff9800;color:white;border:none;border-radius:4px;padding:5px 12px;font-weight:bold}"
            "QPushButton:hover{background:#e68a00}"
        )
        self.sync_btn.clicked.connect(self.sync_preset_requested.emit)
        preset_row.addWidget(self.sync_btn)
        layout.addRow("转换预设:", preset_row)

        fmt_row = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(120)
        self.format_combo.currentIndexChanged.connect(
            lambda: self.format_changed.emit(self.format_combo.currentData() or "")
        )
        fmt_row.addWidget(self.format_combo)
        fmt_row.addStretch()
        layout.addRow("目标格式:", fmt_row)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认保存到原文件所在目录")
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton("浏览...")
        output_browse.clicked.connect(self._browse_output)
        output_row.addWidget(output_browse)
        layout.addRow("输出目录:", output_row)

        retry_row = QHBoxLayout()
        self.retry_check = QCheckBox("失败自动重试")
        self.retry_check.setChecked(True)
        retry_row.addWidget(self.retry_check)
        retry_info = QLabel(f"（最大并发: {self._qm.max_concurrent} 个任务）")
        retry_info.setStyleSheet("color:#888")
        retry_row.addWidget(retry_info)
        retry_row.addStretch()
        layout.addRow("", retry_row)

    def _on_preset_changed(self, index: int):
        pass

    def _browse_output(self):
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.output_edit.setText(d)

    def get_preset_name(self) -> str:
        return self.preset_combo.currentData() or "默认"

    def get_output_format(self) -> str:
        return self.format_combo.currentData() or "epub"

    def get_output_dir(self) -> str:
        return self.output_edit.text().strip()

    def is_retry_enabled(self) -> bool:
        return self.retry_check.isChecked()

    def populate_format_combo(self, books: list):
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        from ..converter import SUPPORTED_CONVERSIONS
        available = set()
        for book in books:
            fmt = getattr(book, 'file_format', '').lower()
            targets = SUPPORTED_CONVERSIONS.get(fmt, set())
            available.update(targets)
        if not available:
            available = {"epub", "mobi", "pdf", "azw3", "txt"}
        for fmt in sorted(available):
            self.format_combo.addItem(fmt.upper(), fmt)
        self.format_combo.blockSignals(False)

    def select_format(self, fmt: str):
        idx = self.format_combo.findData(fmt)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)

    def update_preset_format(self):
        preset_name = self.get_preset_name()
        preset = self._qm.preset_manager.get(preset_name)
        if preset:
            self.select_format(preset.output_format)

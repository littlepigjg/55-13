from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLineEdit, QCheckBox, QLabel, QProgressBar, QGroupBox
)
from PyQt6.QtCore import pyqtSignal, Qt


class ScannerPanel(QWidget):
    scan_requested = pyqtSignal(list, bool)
    scan_progress = pyqtSignal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        dir_group = QGroupBox("书架扫描")
        dir_layout = QVBoxLayout(dir_group)

        row1 = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择书籍所在目录...")
        self.path_edit.setReadOnly(True)
        row1.addWidget(self.path_edit, 1)

        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse)
        row1.addWidget(self.browse_btn)

        self.add_btn = QPushButton("+ 添加目录")
        self.add_btn.clicked.connect(self._add_directory)
        row1.addWidget(self.add_btn)
        dir_layout.addLayout(row1)

        self.dir_list_widget = QWidget()
        self.dir_list_layout = QVBoxLayout(self.dir_list_widget)
        self.dir_list_layout.setContentsMargins(0, 0, 0, 0)
        self.dir_list_layout.setSpacing(2)
        self._dir_paths = []
        dir_layout.addWidget(self.dir_list_widget)

        row2 = QHBoxLayout()
        self.recursive_cb = QCheckBox("递归扫描子目录")
        self.recursive_cb.setChecked(True)
        row2.addWidget(self.recursive_cb)

        row2.addStretch()

        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.setStyleSheet(
            "QPushButton{background:#4a9eff;color:white;border:none;border-radius:4px;padding:6px 16px;font-weight:bold}"
            "QPushButton:hover{background:#3d8be0}"
        )
        self.scan_btn.clicked.connect(self._start_scan)
        row2.addWidget(self.scan_btn)
        dir_layout.addLayout(row2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        dir_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        dir_layout.addWidget(self.status_label)

        layout.addWidget(dir_group)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择书籍目录")
        if d:
            self.path_edit.setText(d)
            self._add_dir_path(d)

    def _add_directory(self):
        d = QFileDialog.getExistingDirectory(self, "添加书籍目录")
        if d:
            self._add_dir_path(d)

    def _add_dir_path(self, path: str):
        if path not in self._dir_paths:
            self._dir_paths.append(path)
            row = QHBoxLayout()
            label = QLabel(path)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            remove_btn = QPushButton("✕")
            remove_btn.setFixedSize(24, 24)
            remove_btn.setStyleSheet("QPushButton{border:none;color:#cc0000;font-weight:bold}")
            remove_btn.clicked.connect(lambda checked, p=path: self._remove_dir(p))
            row.addWidget(remove_btn)
            self.dir_list_layout.addLayout(row)

    def _remove_dir(self, path: str):
        if path in self._dir_paths:
            self._dir_paths.remove(path)

    def _start_scan(self):
        if not self._dir_paths:
            return
        self.scan_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("正在扫描...")
        recursive = self.recursive_cb.isChecked()
        self.scan_requested.emit(self._dir_paths[:], recursive)

    def on_scan_complete(self, count: int):
        self.scan_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"扫描完成，共找到 {count} 本电子书")

    def on_scan_progress(self, current: int, total: int, path: str):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"正在扫描: {path}")

    def get_directories(self) -> list:
        return self._dir_paths[:]

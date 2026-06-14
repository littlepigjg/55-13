from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QGroupBox, QLabel, QListWidget,
    QDialog, QDialogButtonBox, QMessageBox, QCheckBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar
)
from PyQt6.QtCore import pyqtSignal, Qt

from ..models import BookMeta


class MetadataEditPanel(QWidget):
    save_requested = pyqtSignal(list, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: list = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        info_label = QLabel("选择书籍后在此编辑元数据")
        info_label.setStyleSheet("font-weight:bold;font-size:13px;color:#555")
        layout.addWidget(info_label)

        form_group = QGroupBox("元数据编辑")
        form_layout = QFormLayout(form_group)

        self.title_edit = QLineEdit()
        form_layout.addRow("书名:", self.title_edit)

        self.author_edit = QLineEdit()
        form_layout.addRow("作者:", self.author_edit)

        self.publisher_edit = QLineEdit()
        form_layout.addRow("出版社:", self.publisher_edit)

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("如: 2023-01")
        form_layout.addRow("出版日期:", self.date_edit)

        self.isbn_edit = QLineEdit()
        form_layout.addRow("ISBN:", self.isbn_edit)

        self.lang_edit = QLineEdit()
        self.lang_edit.setPlaceholderText("如: zh, en")
        form_layout.addRow("语言:", self.lang_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(100)
        form_layout.addRow("简介:", self.desc_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("用逗号分隔标签")
        form_layout.addRow("标签:", self.tags_edit)

        layout.addWidget(form_group)

        batch_group = QGroupBox("批量操作")
        batch_layout = QVBoxLayout(batch_group)

        self.batch_cb = QCheckBox("批量模式（非空字段将覆盖所有选中书籍）")
        batch_layout.addWidget(self.batch_cb)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("💾 保存修改")
        self.save_btn.setStyleSheet(
            "QPushButton{background:#4a9eff;color:white;border:none;border-radius:4px;padding:8px 16px;font-weight:bold}"
            "QPushButton:hover{background:#3d8be0}"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        batch_layout.addLayout(btn_row)

        layout.addWidget(batch_group)
        layout.addStretch()

    def set_books(self, books: list):
        self._books = books
        if not books:
            self._clear_fields()
            return
        if len(books) == 1:
            b = books[0]
            self.title_edit.setText(b.title)
            self.author_edit.setText(b.author)
            self.publisher_edit.setText(b.publisher)
            self.date_edit.setText(b.publish_date)
            self.isbn_edit.setText(b.isbn)
            self.lang_edit.setText(b.language)
            self.desc_edit.setText(b.description)
            self.tags_edit.setText(", ".join(b.tags))
        else:
            self._clear_fields()
            self.title_edit.setPlaceholderText(f"共 {len(books)} 本书选中")

    def _clear_fields(self):
        for w in [
            self.title_edit, self.author_edit, self.publisher_edit,
            self.date_edit, self.isbn_edit, self.lang_edit, self.tags_edit,
        ]:
            w.clear()
            w.setPlaceholderText("")
        self.desc_edit.clear()

    def _on_save(self):
        changes = {}
        if self.title_edit.text():
            changes["title"] = self.title_edit.text()
        if self.author_edit.text():
            changes["author"] = self.author_edit.text()
        if self.publisher_edit.text():
            changes["publisher"] = self.publisher_edit.text()
        if self.date_edit.text():
            changes["publish_date"] = self.date_edit.text()
        if self.isbn_edit.text():
            changes["isbn"] = self.isbn_edit.text()
        if self.lang_edit.text():
            changes["language"] = self.lang_edit.text()
        if self.desc_edit.toPlainText():
            changes["description"] = self.desc_edit.toPlainText()
        if self.tags_edit.text():
            changes["tags"] = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]

        if not changes:
            QMessageBox.information(self, "提示", "没有修改内容")
            return

        if not self.batch_cb.isChecked() and len(self._books) > 1:
            reply = QMessageBox.question(
                self,
                "确认",
                f"将对 {len(self._books)} 本书应用修改，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.save_requested.emit(self._books, changes)

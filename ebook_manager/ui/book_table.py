from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QAbstractItemView, QPushButton, QLineEdit,
    QComboBox, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt

from ..models import BookMeta


class BookTableWidget(QWidget):
    selection_changed = pyqtSignal(list)
    edit_requested = pyqtSignal(list)
    convert_requested = pyqtSignal(list)
    search_meta_requested = pyqtSignal(list)

    COLUMNS = [
        ("选择", 40),
        ("书名", 200),
        ("作者", 150),
        ("出版社", 150),
        ("出版日期", 100),
        ("ISBN", 130),
        ("语言", 60),
        ("格式", 60),
        ("大小", 80),
        ("路径", 250),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: list = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        toolbar.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        toolbar.addWidget(self.deselect_all_btn)

        toolbar.addStretch()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索书名/作者...")
        self.search_edit.setFixedWidth(250)
        self.search_edit.textChanged.connect(self._filter_table)
        toolbar.addWidget(self.search_edit)

        self.format_filter = QComboBox()
        self.format_filter.addItem("全部格式")
        self.format_filter.addItem("EPUB")
        self.format_filter.addItem("MOBI")
        self.format_filter.addItem("PDF")
        self.format_filter.currentTextChanged.connect(self._filter_table)
        toolbar.addWidget(self.format_filter)

        self.count_label = QLabel("")
        toolbar.addWidget(self.count_label)
        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)

        header = self.table.horizontalHeader()
        for i, (_, width) in enumerate(self.COLUMNS):
            header.setMinimumSectionSize(30)
            if i == 0:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(i, width)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, width)

        header.setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

    def load_books(self, books: list):
        self._books = books
        self._populate_table(books)

    def _populate_table(self, books: list):
        self.table.blockSignals(True)
        self.table.setRowCount(len(books))
        for row, book in enumerate(books):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, check_item)

            self.table.setItem(row, 1, QTableWidgetItem(book.title))
            self.table.setItem(row, 2, QTableWidgetItem(book.author))
            self.table.setItem(row, 3, QTableWidgetItem(book.publisher))
            self.table.setItem(row, 4, QTableWidgetItem(book.publish_date))
            self.table.setItem(row, 5, QTableWidgetItem(book.isbn))
            self.table.setItem(row, 6, QTableWidgetItem(book.language))
            self.table.setItem(row, 7, QTableWidgetItem(book.file_format.upper()))

            size_item = QTableWidgetItem(BookMeta.format_size(book.file_size))
            size_item.setData(Qt.ItemDataRole.UserRole, book.file_size)
            self.table.setItem(row, 8, size_item)

            self.table.setItem(row, 9, QTableWidgetItem(book.file_path))
        self.table.blockSignals(False)
        self.count_label.setText(f"共 {len(books)} 本")

    def get_selected_books(self) -> list:
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                idx = item.data(Qt.ItemDataRole.UserRole)
                if 0 <= idx < len(self._books):
                    selected.append(self._books[idx])
        return selected

    def refresh_row(self, row_idx: int, book: BookMeta):
        if 0 <= row_idx < len(self._books):
            self._books[row_idx] = book
            self.table.blockSignals(True)
            self.table.item(row_idx, 1).setText(book.title)
            self.table.item(row_idx, 2).setText(book.author)
            self.table.item(row_idx, 3).setText(book.publisher)
            self.table.item(row_idx, 4).setText(book.publish_date)
            self.table.item(row_idx, 5).setText(book.isbn)
            self.table.item(row_idx, 6).setText(book.language)
            self.table.blockSignals(False)

    def _select_all(self):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._notify_selection()

    def _deselect_all(self):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._notify_selection()

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self._notify_selection()

    def _notify_selection(self):
        self.selection_changed.emit(self.get_selected_books())

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        edit_action = menu.addAction("✏️ 编辑元数据")
        search_action = menu.addAction("🔍 在线搜索元数据")
        convert_action = menu.addAction("🔄 转换格式")
        menu.addSeparator()
        open_action = menu.addAction("📂 打开文件位置")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        selected = self.get_selected_books()
        if not selected:
            return
        if action == edit_action:
            self.edit_requested.emit(selected)
        elif action == search_action:
            self.search_meta_requested.emit(selected)
        elif action == convert_action:
            self.convert_requested.emit(selected)
        elif action == open_action:
            import os
            import subprocess
            path = selected[0].file_path
            if os.path.exists(path):
                subprocess.Popen(f'explorer /select,"{path}"')

    def _filter_table(self):
        keyword = self.search_edit.text().lower()
        fmt = self.format_filter.currentText()
        filtered = []
        for book in self._books:
            if fmt != "全部格式" and book.file_format.upper() != fmt:
                continue
            if keyword:
                searchable = f"{book.title} {book.author} {book.isbn} {book.publisher}".lower()
                if keyword not in searchable:
                    continue
            filtered.append(book)
        self._populate_table(filtered)

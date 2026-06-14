from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QDialogButtonBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import QThread, pyqtSignal

from ..network.manager import NetworkSourceManager


class _SearchThread(QThread):
    done = pyqtSignal(list)

    def __init__(self, mgr, query):
        super().__init__()
        self._mgr = mgr
        self._query = query

    def run(self):
        try:
            results = self._mgr.search(self._query)
            self.done.emit(results)
        except Exception:
            self.done.emit([])


class _ISBNSearchThread(QThread):
    done = pyqtSignal(object)

    def __init__(self, mgr, query):
        super().__init__()
        self._mgr = mgr
        self._query = query

    def run(self):
        try:
            result = self._mgr.search_by_isbn(self._query)
            self.done.emit(result)
        except Exception:
            self.done.emit(None)


class OnlineSearchDialog(QDialog):
    def __init__(self, books: list, source_manager: NetworkSourceManager, parent=None):
        super().__init__(parent)
        self._books = books
        self._source_manager = source_manager
        self._results = []
        self._selected_data = None
        self.setWindowTitle("在线搜索元数据")
        self.setMinimumSize(700, 500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入书名或ISBN搜索...")
        if self._books:
            self.search_edit.setText(self._books[0].title)
        search_row.addWidget(self.search_edit, 1)

        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_btn)

        self.isbn_search_btn = QPushButton("ISBN搜索")
        self.isbn_search_btn.clicked.connect(self._do_isbn_search)
        search_row.addWidget(self.isbn_search_btn)
        layout.addLayout(search_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(
            ["书名", "作者", "出版社", "出版日期", "ISBN", "来源"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.currentCellChanged.connect(self._on_row_selected)
        layout.addWidget(self.result_table)

        self.preview_label = QLabel("选择搜索结果以预览")
        self.preview_label.setWordWrap(True)
        self.preview_label.setMaximumHeight(80)
        layout.addWidget(self.preview_label)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _do_search(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.search_btn.setEnabled(False)

        self._thread = _SearchThread(self._source_manager, query)
        self._thread.done.connect(self._on_search_done)
        self._thread.start()

    def _do_isbn_search(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.search_btn.setEnabled(False)

        self._thread = _ISBNSearchThread(self._source_manager, query)
        self._thread.done.connect(self._on_isbn_search_done)
        self._thread.start()

    def _on_search_done(self, results: list):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)
        self._results = results
        self._populate_table(results)

    def _on_isbn_search_done(self, result):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)
        if result:
            self._results = [result]
            self._populate_table([result])
        else:
            self._results = []
            self.result_table.setRowCount(0)

    def _populate_table(self, items: list):
        self.result_table.setRowCount(len(items))
        for i, r in enumerate(items):
            self.result_table.setItem(i, 0, QTableWidgetItem(r.get("title", "")))
            self.result_table.setItem(i, 1, QTableWidgetItem(r.get("author", "")))
            self.result_table.setItem(i, 2, QTableWidgetItem(r.get("publisher", "")))
            self.result_table.setItem(i, 3, QTableWidgetItem(r.get("publish_date", "")))
            self.result_table.setItem(i, 4, QTableWidgetItem(r.get("isbn", "")))
            self.result_table.setItem(i, 5, QTableWidgetItem(r.get("source", "")))

    def _on_row_selected(self, row, col, prev_row, prev_col):
        if 0 <= row < len(self._results):
            data = self._results[row]
            self._selected_data = data
            preview = (
                f"📖 {data.get('title', '')}\n"
                f"✍️ {data.get('author', '')}\n"
                f"🏢 {data.get('publisher', '')}\n"
                f"📅 {data.get('publish_date', '')}"
            )
            self.preview_label.setText(preview)
        else:
            self._selected_data = None

    def get_selected_data(self):
        return self._selected_data

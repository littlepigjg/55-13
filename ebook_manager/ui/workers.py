from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..models import BookMeta
from ..scanner import BookshelfScanner
from ..metadata_parser import MetadataParser


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, directories: list, recursive: bool):
        super().__init__()
        self._directories = directories
        self._recursive = recursive

    def run(self):
        scanner = BookshelfScanner()
        scanner.set_progress_callback(
            lambda c, t, p: self.progress.emit(c, t, p)
        )
        files = scanner.scan_directories(self._directories, self._recursive)
        self.finished_signal.emit(files)


class ParseWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, files: list):
        super().__init__()
        self._files = files

    def run(self):
        parser = MetadataParser()
        books = []
        total = len(self._files)
        for i, f in enumerate(self._files):
            self.progress.emit(i + 1, total, f)
            try:
                book = parser.parse(f)
                books.append(book)
            except Exception:
                books.append(
                    BookMeta(
                        file_path=f,
                        file_format=Path(f).suffix.lstrip("."),
                        title=Path(f).stem,
                    )
                )
        self.finished_signal.emit(books)

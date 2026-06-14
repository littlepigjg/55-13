import os
from pathlib import Path
from typing import List

SUPPORTED_EXTENSIONS = {".epub", ".mobi", ".pdf"}


class BookshelfScanner:
    def __init__(self):
        self._progress_callback = None

    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def _notify_progress(self, current: int, total: int, file_path: str):
        if self._progress_callback:
            self._progress_callback(current, total, file_path)

    def scan_directory(self, directory: str, recursive: bool = True) -> List[str]:
        directory = Path(directory)
        if not directory.is_dir():
            return []
        return self._collect_files(directory, recursive)

    def scan_directories(self, directories: List[str], recursive: bool = True) -> List[str]:
        all_files = []
        for d in directories:
            all_files.extend(self.scan_directory(d, recursive))
        return all_files

    def _collect_files(self, directory: Path, recursive: bool) -> List[str]:
        result = []
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            return result

        total = len(entries)
        for i, entry in enumerate(entries):
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                result.append(str(entry.resolve()))
                self._notify_progress(i + 1, total, str(entry))
            elif entry.is_dir() and recursive:
                result.extend(self._collect_files(entry, recursive))

        return result

    @staticmethod
    def is_supported_file(file_path: str) -> bool:
        return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS

    @staticmethod
    def get_file_format(file_path: str) -> str:
        return Path(file_path).suffix.lower().lstrip(".")

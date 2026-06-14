import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Callable

SUPPORTED_CONVERSIONS = {
    "epub": {"mobi", "pdf", "azw3", "txt"},
    "mobi": {"epub", "pdf", "azw3", "txt"},
    "pdf": {"epub", "mobi", "txt"},
    "azw3": {"epub", "mobi", "pdf", "txt"},
}

EBOOK_CONVERT = "ebook-convert"


class ConversionTask:
    def __init__(self, input_path: str, output_format: str, output_dir: Optional[str] = None):
        self.input_path = input_path
        self.output_format = output_format.lower()
        self.output_dir = output_dir
        self.status = "pending"
        self.error = ""

    @property
    def output_path(self) -> str:
        inp = Path(self.input_path)
        out_dir = self.output_dir or str(inp.parent)
        return str(Path(out_dir) / f"{inp.stem}.{self.output_format}")


class FormatConverter:
    def __init__(self):
        self._calibre_available = self._check_calibre()
        self._progress_callback: Optional[Callable] = None

    def _check_calibre(self) -> bool:
        try:
            result = subprocess.run(
                [EBOOK_CONVERT, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @property
    def is_calibre_available(self) -> bool:
        return self._calibre_available

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    def get_supported_targets(self, source_format: str) -> set:
        return SUPPORTED_CONVERSIONS.get(source_format.lower(), set())

    def convert(self, task: ConversionTask) -> bool:
        if not self._calibre_available:
            task.status = "error"
            task.error = "Calibre (ebook-convert) 未安装或不在 PATH 中"
            return False

        if not os.path.exists(task.input_path):
            task.status = "error"
            task.error = f"输入文件不存在: {task.input_path}"
            return False

        source_fmt = Path(task.input_path).suffix.lower().lstrip(".")
        if task.output_format not in self.get_supported_targets(source_fmt):
            task.status = "error"
            task.error = f"不支持 {source_fmt} -> {task.output_format} 转换"
            return False

        try:
            task.status = "converting"
            cmd = [EBOOK_CONVERT, task.input_path, task.output_path]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0 and os.path.exists(task.output_path):
                task.status = "completed"
                return True
            else:
                task.status = "error"
                task.error = result.stderr[:500] if result.stderr else "转换失败"
                return False
        except subprocess.TimeoutExpired:
            task.status = "error"
            task.error = "转换超时"
            return False
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            return False

    def batch_convert(self, tasks: List[ConversionTask]) -> List[ConversionTask]:
        total = len(tasks)
        for i, task in enumerate(tasks):
            if self._progress_callback:
                self._progress_callback(i + 1, total, task.input_path)
            self.convert(task)
        return tasks

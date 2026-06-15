import uuid
import json
import time
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path


class TaskStatus(str, Enum):
    PENDING = "pending"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def display_name(self) -> str:
        return {
            TaskStatus.PENDING: "排队中",
            TaskStatus.CONVERTING: "转换中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.FAILED: "失败",
            TaskStatus.CANCELLED: "已取消",
        }[self]

    @property
    def icon(self) -> str:
        return {
            TaskStatus.PENDING: "⏳",
            TaskStatus.CONVERTING: "⚙️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.CANCELLED: "🚫",
        }[self]

    @property
    def color(self) -> str:
        return {
            TaskStatus.PENDING: "#888888",
            TaskStatus.CONVERTING: "#4a9eff",
            TaskStatus.COMPLETED: "#22c55e",
            TaskStatus.FAILED: "#ef4444",
            TaskStatus.CANCELLED: "#9ca3af",
        }[self]


@dataclass
class ConvertPreset:
    name: str
    description: str = ""
    output_format: str = "epub"
    extra_args: List[str] = field(default_factory=list)
    custom_options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "output_format": self.output_format,
            "extra_args": self.extra_args,
            "custom_options": self.custom_options,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConvertPreset":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            output_format=d.get("output_format", "epub"),
            extra_args=d.get("extra_args", []),
            custom_options=d.get("custom_options", {}),
        )

    @classmethod
    def get_default_presets(cls) -> List["ConvertPreset"]:
        return [
            cls(
                name="默认",
                description="使用 Calibre 默认转换参数",
                output_format="epub",
                extra_args=[],
                custom_options={},
            ),
            cls(
                name="Kindle优化",
                description="去除字体嵌入，优化目录结构，适合 Kindle 设备",
                output_format="mobi",
                extra_args=[
                    "--no-inline-toc",
                    "--remove-fonts-from-res",
                    "--prefer-author-sort",
                ],
                custom_options={"remove_fonts": True, "optimize_kindle": True},
            ),
            cls(
                name="打印版PDF",
                description="高分辨率图片，适合打印输出",
                output_format="pdf",
                extra_args=[
                    "--pdf-page-size", "A4",
                    "--pdf-default-font-size", "12",
                    "--pdf-mono-font-size", "10",
                    "--pdf-serif-family", "SimSun",
                    "--pdf-sans-family", "Microsoft YaHei",
                    "--pdf-embed-all-fonts",
                ],
                custom_options={"high_quality": True, "print_optimized": True},
            ),
            cls(
                name="移动设备优化",
                description="小屏幕阅读优化，压缩图片体积",
                output_format="azw3",
                extra_args=[
                    "--no-inline-toc",
                    "--mobi-keep-original-images",
                    "--chapter-mark", "none",
                ],
                custom_options={"mobile_optimized": True},
            ),
            cls(
                name="纯文本提取",
                description="去除所有格式，提取纯文本内容",
                output_format="txt",
                extra_args=[
                    "--txt-output-encoding", "utf8",
                    "--txt-page-breaks-between-chapters",
                ],
                custom_options={"plain_text": True},
            ),
        ]


@dataclass
class ConvertQueueTask:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    input_path: str = ""
    output_format: str = "epub"
    output_dir: Optional[str] = None
    book_title: str = ""
    book_author: str = ""
    source_format: str = ""
    file_size: int = 0
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 1
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: float = 0.0
    preset_name: str = "默认"
    extra_args: List[str] = field(default_factory=list)
    output_path: str = ""

    @property
    def output_filename(self) -> str:
        inp = Path(self.input_path)
        return f"{inp.stem}.{self.output_format.lower()}"

    @property
    def resolved_output_path(self) -> str:
        if self.output_path:
            return self.output_path
        inp = Path(self.input_path)
        out_dir = self.output_dir or str(inp.parent)
        return str(Path(out_dir) / self.output_filename)

    @property
    def display_name(self) -> str:
        if self.book_title:
            return f"{self.book_title} - {self.book_author}" if self.book_author else self.book_title
        return Path(self.input_path).name

    @property
    def formatted_duration(self) -> str:
        if self.duration_seconds < 60:
            return f"{self.duration_seconds:.1f}秒"
        mins = int(self.duration_seconds // 60)
        secs = int(self.duration_seconds % 60)
        return f"{mins}分{secs}秒"

    @property
    def formatted_size(self) -> str:
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def mark_started(self):
        self.status = TaskStatus.CONVERTING
        self.started_at = time.time()
        self.progress = 0

    def mark_completed(self, output_path: str = ""):
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.progress = 100
        if self.started_at:
            self.duration_seconds = self.completed_at - self.started_at
        if output_path:
            self.output_path = output_path

    def mark_failed(self, error: str):
        self.status = TaskStatus.FAILED
        self.completed_at = time.time()
        self.error_message = error
        if self.started_at:
            self.duration_seconds = self.completed_at - self.started_at

    def mark_cancelled(self):
        self.status = TaskStatus.CANCELLED
        self.completed_at = time.time()
        if self.started_at:
            self.duration_seconds = self.completed_at - self.started_at

    def reset_for_retry(self):
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.error_message = ""
        self.started_at = None
        self.completed_at = None
        self.duration_seconds = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "input_path": self.input_path,
            "output_format": self.output_format,
            "output_dir": self.output_dir,
            "book_title": self.book_title,
            "book_author": self.book_author,
            "source_format": self.source_format,
            "file_size": self.file_size,
            "status": self.status.value,
            "progress": self.progress,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "preset_name": self.preset_name,
            "extra_args": self.extra_args,
            "output_path": self.output_path,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConvertQueueTask":
        task = cls(
            task_id=d.get("task_id", uuid.uuid4().hex),
            input_path=d.get("input_path", ""),
            output_format=d.get("output_format", "epub"),
            output_dir=d.get("output_dir"),
            book_title=d.get("book_title", ""),
            book_author=d.get("book_author", ""),
            source_format=d.get("source_format", ""),
            file_size=d.get("file_size", 0),
            progress=d.get("progress", 0),
            error_message=d.get("error_message", ""),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", 1),
            created_at=d.get("created_at", time.time()),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            duration_seconds=d.get("duration_seconds", 0.0),
            preset_name=d.get("preset_name", "默认"),
            extra_args=d.get("extra_args", []),
            output_path=d.get("output_path", ""),
        )
        status_val = d.get("status", TaskStatus.PENDING.value)
        if status_val == TaskStatus.CONVERTING.value:
            task.status = TaskStatus.PENDING
        else:
            try:
                task.status = TaskStatus(status_val)
            except ValueError:
                task.status = TaskStatus.PENDING
        return task


class PresetManager:
    def __init__(self, config_dir: Optional[str] = None):
        self._presets: Dict[str, ConvertPreset] = {}
        self._config_path: Optional[Path] = None
        if config_dir:
            self._config_path = Path(config_dir) / "convert_presets.json"
        self._load_defaults()
        self._load_from_disk()

    def _load_defaults(self):
        for preset in ConvertPreset.get_default_presets():
            self._presets[preset.name] = preset

    def _load_from_disk(self):
        if not self._config_path or not self._config_path.exists():
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("presets", []):
                preset = ConvertPreset.from_dict(item)
                if preset.name and preset.name not in self._presets:
                    self._presets[preset.name] = preset
        except Exception:
            pass

    def save_to_disk(self):
        if not self._config_path:
            return
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "presets": [p.to_dict() for p in self._presets.values()],
                "saved_at": time.time(),
            }
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_all(self) -> List[ConvertPreset]:
        return list(self._presets.values())

    def get_names(self) -> List[str]:
        return list(self._presets.keys())

    def get(self, name: str) -> Optional[ConvertPreset]:
        return self._presets.get(name)

    def add(self, preset: ConvertPreset) -> bool:
        if preset.name in self._presets:
            return False
        self._presets[preset.name] = preset
        self.save_to_disk()
        return True

    def update(self, preset: ConvertPreset):
        self._presets[preset.name] = preset
        self.save_to_disk()

    def delete(self, name: str) -> bool:
        defaults = {p.name for p in ConvertPreset.get_default_presets()}
        if name in defaults:
            return False
        if name in self._presets:
            del self._presets[name]
            self.save_to_disk()
            return True
        return False

    def apply_preset_to_task(self, task: ConvertQueueTask, preset_name: str) -> bool:
        preset = self.get(preset_name)
        if not preset:
            return False
        task.preset_name = preset_name
        task.output_format = preset.output_format
        task.extra_args = list(preset.extra_args)
        return True

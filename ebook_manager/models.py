from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class BookMeta:
    title: str = ""
    author: str = ""
    publisher: str = ""
    publish_date: str = ""
    isbn: str = ""
    language: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    cover_path: Optional[str] = None
    file_path: str = ""
    file_format: str = ""
    file_size: int = 0

    def to_dict(self):
        return {
            "title": self.title,
            "author": self.author,
            "publisher": self.publisher,
            "publish_date": self.publish_date,
            "isbn": self.isbn,
            "language": self.language,
            "description": self.description,
            "tags": self.tags,
            "cover_path": self.cover_path,
            "file_path": self.file_path,
            "file_format": self.file_format,
            "file_size": self.file_size,
        }

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            title=d.get("title", ""),
            author=d.get("author", ""),
            publisher=d.get("publisher", ""),
            publish_date=d.get("publish_date", ""),
            isbn=d.get("isbn", ""),
            language=d.get("language", ""),
            description=d.get("description", ""),
            tags=d.get("tags", []),
            cover_path=d.get("cover_path"),
            file_path=d.get("file_path", ""),
            file_format=d.get("file_format", ""),
            file_size=d.get("file_size", 0),
        )

    @staticmethod
    def format_size(size_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

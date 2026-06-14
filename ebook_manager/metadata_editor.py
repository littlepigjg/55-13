import os
import zipfile
import xml.etree.ElementTree as ET
import tempfile
from pathlib import Path
from typing import List, Optional, Dict

from .models import BookMeta


class MetadataEditor:
    def apply_batch(self, books: List[BookMeta], changes: Dict[str, str]) -> List[BookMeta]:
        for book in books:
            for field, value in changes.items():
                if value and hasattr(book, field):
                    setattr(book, field, value)
        return books

    def apply_to_single(self, book: BookMeta, changes: Dict[str, str]) -> BookMeta:
        for field, value in changes.items():
            if value and hasattr(book, field):
                setattr(book, field, value)
        return book

    def merge_from_source(
        self, book: BookMeta, source_data: Dict[str, str], overwrite: bool = False
    ) -> BookMeta:
        for field, value in source_data.items():
            if value and hasattr(book, field):
                current = getattr(book, field)
                if overwrite or not current:
                    setattr(book, field, value)
        return book

    def save_epub_metadata(self, book: BookMeta) -> bool:
        if book.file_format != "epub":
            return False
        try:
            file_path = book.file_path
            entries = []
            opf_idx = -1
            mimetype_idx = -1

            with zipfile.ZipFile(file_path, "r") as zf:
                opf_path = self._find_opf_path(zf)
                if not opf_path:
                    return False
                for idx, info in enumerate(zf.infolist()):
                    data = zf.read(info.filename)
                    entries.append((info, data))
                    if info.filename == opf_path:
                        opf_idx = idx
                    if info.filename == "mimetype":
                        mimetype_idx = idx

            if opf_idx < 0:
                return False

            normalized = []
            for info, data in entries:
                new_info = self._copy_zipinfo(info)
                normalized.append((new_info, data))

            if opf_idx >= 0:
                opf_content = normalized[opf_idx][1].decode("utf-8")
                modified_opf = self._update_opf_content(opf_content, book).encode("utf-8")
                info = normalized[opf_idx][0]
                info.compress_type = zipfile.ZIP_DEFLATED
                normalized[opf_idx] = (info, modified_opf)

            ordered = []
            if mimetype_idx >= 0:
                mt_info, mt_data = normalized[mimetype_idx]
                mt_info.compress_type = zipfile.ZIP_STORED
                ordered.append((mt_info, mt_data))
            for idx, item in enumerate(normalized):
                if idx == mimetype_idx:
                    continue
                ordered.append(item)

            fd, tmp_path = tempfile.mkstemp(suffix=".epub", dir=str(Path(file_path).parent))
            try:
                os.close(fd)
                with zipfile.ZipFile(tmp_path, "w") as zf_out:
                    for info, data in ordered:
                        zf_out.writestr(info, data)

                backup_path = file_path + ".bak"
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.replace(file_path, backup_path)
                os.replace(tmp_path, file_path)
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise

            return True
        except Exception:
            return False

    @staticmethod
    def _copy_zipinfo(src: zipfile.ZipInfo) -> zipfile.ZipInfo:
        dst = zipfile.ZipInfo(src.filename, src.date_time)
        dst.compress_type = src.compress_type
        dst.comment = src.comment
        dst.extra = src.extra
        dst.create_system = src.create_system
        dst.create_version = src.create_version
        dst.extract_version = src.extract_version
        dst.reserved = src.reserved
        dst.flag_bits = src.flag_bits
        dst.volume = src.volume
        dst.internal_attr = src.internal_attr
        dst.external_attr = src.external_attr
        return dst

    def _find_opf_path(self, zf: zipfile.ZipFile) -> Optional[str]:
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8")
            root = ET.fromstring(container)
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = root.find(".//c:rootfile", ns)
            if rootfile is not None:
                return rootfile.get("full-path")
        except Exception:
            pass
        return None

    def _update_opf_content(self, opf_content: str, book: BookMeta) -> str:
        ns = "http://purl.org/dc/elements/1.1/"
        root = ET.fromstring(opf_content)

        metadata = root.find("{http://www.idpf.org/2007/opf}metadata")
        if metadata is None:
            return opf_content

        field_map = {
            "title": f"{{{ns}}}title",
            "creator": f"{{{ns}}}creator",
            "publisher": f"{{{ns}}}publisher",
            "date": f"{{{ns}}}date",
            "language": f"{{{ns}}}language",
            "description": f"{{{ns}}}description",
        }

        value_map = {
            "title": book.title,
            "creator": book.author,
            "publisher": book.publisher,
            "date": book.publish_date,
            "language": book.language,
            "description": book.description,
        }

        for attr, tag in field_map.items():
            value = value_map.get(attr, "")
            if not value:
                continue
            existing = metadata.find(tag)
            if existing is not None:
                existing.text = value
            else:
                elem = ET.Element(tag)
                elem.text = value
                metadata.append(elem)

        if book.isbn:
            isbn_tag = f"{{{ns}}}identifier"
            existing_isbn = None
            for elem in metadata.findall(isbn_tag):
                if elem.text and "isbn" in elem.text.lower():
                    existing_isbn = elem
                    break
            if existing_isbn is not None:
                existing_isbn.text = f"ISBN:{book.isbn}"
            else:
                elem = ET.Element(isbn_tag)
                elem.text = f"ISBN:{book.isbn}"
                metadata.append(elem)

        ET.register_namespace("", "http://www.idpf.org/2007/opf")
        ET.register_namespace("dc", ns)
        ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

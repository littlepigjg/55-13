import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from .models import BookMeta

EPUB_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
EPUB_METADATA_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf",
}


class MetadataParser:
    def parse(self, file_path: str) -> BookMeta:
        ext = Path(file_path).suffix.lower()
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        if ext == ".epub":
            meta = self._parse_epub(file_path)
        elif ext == ".mobi":
            meta = self._parse_mobi(file_path)
        elif ext == ".pdf":
            meta = self._parse_pdf(file_path)
        else:
            meta = BookMeta()

        meta.file_path = file_path
        meta.file_format = ext.lstrip(".")
        meta.file_size = file_size
        if not meta.title:
            meta.title = Path(file_path).stem
        return meta

    def _parse_epub(self, file_path: str) -> BookMeta:
        meta = BookMeta()
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                opf_path = self._find_opf_path(zf)
                if not opf_path:
                    return meta
                opf_content = zf.read(opf_path).decode("utf-8", errors="ignore")
                root = ET.fromstring(opf_content)
                self._extract_epub_metadata(root, meta)
                cover_path = self._find_epub_cover(zf, root, opf_path)
                if cover_path:
                    meta.cover_path = cover_path
        except Exception:
            pass
        return meta

    def _find_opf_path(self, zf: zipfile.ZipFile) -> Optional[str]:
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8")
            root = ET.fromstring(container)
            rootfile = root.find(".//c:rootfile", EPUB_CONTAINER_NS)
            if rootfile is not None:
                return rootfile.get("full-path")
        except Exception:
            pass
        return None

    def _extract_epub_metadata(self, root: ET.Element, meta: BookMeta):
        for elem in root.iter():
            tag = elem.tag
            if isinstance(tag, str):
                if tag.endswith("}title") or tag == "title":
                    if not meta.title:
                        meta.title = (elem.text or "").strip()
                elif tag.endswith("}creator") or tag == "creator":
                    if not meta.author:
                        meta.author = (elem.text or "").strip()
                elif tag.endswith("}publisher") or tag == "publisher":
                    if not meta.publisher:
                        meta.publisher = (elem.text or "").strip()
                elif tag.endswith("}date") or tag == "date":
                    if not meta.publish_date:
                        meta.publish_date = (elem.text or "").strip()
                elif tag.endswith("}language") or tag == "language":
                    if not meta.language:
                        meta.language = (elem.text or "").strip()
                elif tag.endswith("}identifier") or tag == "identifier":
                    text = (elem.text or "").strip()
                    if "isbn" in text.lower() and not meta.isbn:
                        meta.isbn = text
                elif tag.endswith("}description") or tag == "description":
                    if not meta.description:
                        meta.description = (elem.text or "").strip()
                elif tag.endswith("}subject") or tag == "subject":
                    if elem.text and elem.text.strip() not in meta.tags:
                        meta.tags.append(elem.text.strip())

    def _find_epub_cover(self, zf, root, opf_path: str) -> Optional[str]:
        try:
            manifest = root.find(".//{http://www.idpf.org/2007/opf}manifest")
            if manifest is not None:
                for item in manifest:
                    props = item.get("properties", "")
                    href = item.get("href", "")
                    if "cover-image" in props:
                        return href
            metadata = root.find(".//{http://www.idpf.org/2007/opf}metadata")
            if metadata is not None:
                for meta_elem in metadata:
                    if meta_elem.get("name") == "cover":
                        cover_id = meta_elem.get("content")
                        if manifest is not None and cover_id:
                            for item in manifest:
                                if item.get("id") == cover_id:
                                    return item.get("href")
        except Exception:
            pass
        return None

    def _parse_mobi(self, file_path: str) -> BookMeta:
        meta = BookMeta()
        try:
            with open(file_path, "rb") as f:
                header = f.read(132)
                if len(header) < 132:
                    return meta
                mobi_start = int.from_bytes(header[60:64], "big")
                f.seek(mobi_start)
                mobi_header = f.read(200)
                if len(mobi_header) < 24:
                    return meta
                title_len = int.from_bytes(mobi_header[20:24], "big")
                encoding = int.from_bytes(mobi_header[12:16], "big")
                codec = "utf-8" if encoding == 65001 else "cp1252"
                f.seek(0)
                palm_name = f.read(32).split(b"\x00")[0]
                try:
                    meta.title = palm_name.decode(codec).strip()
                except Exception:
                    meta.title = palm_name.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass
        return meta

    def _parse_pdf(self, file_path: str) -> BookMeta:
        meta = BookMeta()
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)
            info = reader.metadata
            if info:
                meta.title = self._clean_pdf_field(info.title)
                meta.author = self._clean_pdf_field(info.author)
                meta.publisher = self._clean_pdf_field(
                    info.get("/Publisher", info.get("/Producer", ""))
                )
                meta.publish_date = self._clean_pdf_field(info.get("/CreationDate", ""))
                meta.language = self._clean_pdf_field(info.get("/Language", ""))
                meta.description = self._clean_pdf_field(
                    info.get("/Subject", info.get("/Keywords", ""))
                )
                isbn_val = self._clean_pdf_field(info.get("/ISBN", ""))
                if isbn_val:
                    meta.isbn = isbn_val
        except ImportError:
            try:
                meta.title = Path(file_path).stem
            except Exception:
                pass
        except Exception:
            pass
        return meta

    @staticmethod
    def _clean_pdf_field(value) -> str:
        if not value:
            return ""
        s = str(value)
        if s.startswith("/"):
            s = s[1:]
        for prefix in ["D:", "d:"]:
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        return s.strip()

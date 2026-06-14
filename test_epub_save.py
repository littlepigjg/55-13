"""EPUB 保存逻辑测试脚本

测试目标：
1. 所有文件统一处理流程（无一例外经过 _copy_zipinfo）
2. ZipInfo 完整属性保留
3. 文件顺序严格保持（mimetype 首位）
4. mimetype 必须 ZIP_STORED
5. ZIP 结构完整性
6. 阅读器兼容性检查（模拟多种阅读器严格程度）
   - 宽松级: testzip 通过
   - 标准级: mimetype 首位 + ZIP_STORED + 无 CRC 错误
   - 严格级: central/local 目录一致 + date_time 一致 + extra 字段保留
   - 超严格级: 所有 ZipInfo 属性一致
"""
import os
import sys
import zipfile
import struct
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, "D:\\Lib\\site-packages")
sys.path.insert(0, str(Path(__file__).parent))

from ebook_manager.metadata_parser import MetadataParser
from ebook_manager.metadata_editor import MetadataEditor


def make_test_epub(path: str):
    """生成一个结构完整、属性多样的测试 EPUB"""
    opf = '''<?xml version='1.0' encoding='utf-8'?>
<package xmlns='http://www.idpf.org/2007/opf' unique-identifier='uid' version='3.0'>
  <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>
    <dc:identifier id='uid'>isbn:9787544291163</dc:identifier>
    <dc:title>Original Title</dc:title>
    <dc:creator>Original Author</dc:creator>
    <dc:publisher>Original Publisher</dc:publisher>
    <dc:date>2020-01-01</dc:date>
    <dc:language>zh</dc:language>
    <dc:description>Original description text.</dc:description>
  </metadata>
</package>'''

    container = '''<?xml version='1.0' encoding='utf-8'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
  <rootfiles>
    <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
  </rootfiles>
</container>'''

    chapter = '''<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <head><title>Chapter 1</title></head>
  <body><h1>第一章</h1><p>测试正文内容。</p></body>
</html>'''

    nav = '''<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'>
  <body><nav epub:type='toc'><ol><li><a href='chapter1.xhtml'>第一章</a></li></ol></nav></body>
</html>'''

    stylesheet = '''body { font-family: serif; }
h1 { color: #333; }'''

    font_dummy = b"\x00\x01\x00\x00OTTO" + b"\x00" * 100

    custom_time = (2023, 5, 15, 14, 30, 0)
    extra_data = struct.pack("<HH", 0xCAFE, 4) + b"\x01\x02\x03\x04"

    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype", custom_time)
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 0
        info.external_attr = 0o644 << 16
        info.extra = extra_data
        zf.writestr(info, "application/epub+zip")

        info = zipfile.ZipInfo("META-INF/container.xml", custom_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.internal_attr = 0x0001
        info.extra = extra_data
        zf.writestr(info, container)

        info = zipfile.ZipInfo("OEBPS/content.opf", custom_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.internal_attr = 0x0001
        info.extra = extra_data
        zf.writestr(info, opf)

        info = zipfile.ZipInfo("OEBPS/chapter1.xhtml", custom_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.extra = extra_data
        zf.writestr(info, chapter)

        info = zipfile.ZipInfo("OEBPS/nav.xhtml", custom_time)
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.extra = extra_data
        zf.writestr(info, nav)

        info = zipfile.ZipInfo("OEBPS/styles/main.css", custom_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.extra = extra_data
        zf.writestr(info, stylesheet)

        info = zipfile.ZipInfo("OEBPS/fonts/dummy.ttf", custom_time)
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = 0o644 << 16
        info.extra = extra_data
        zf.writestr(info, font_dummy)


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def ok(self, msg):
        self.passed += 1
        print(f"  [PASS] {msg}")

    def fail(self, msg):
        self.failed += 1
        print(f"  [FAIL] {msg}")

    def section(self, title):
        print()
        print(f"=== {title} ===")


def check_zip_structure(path: str) -> bool:
    """基础级：ZIP 结构完整性"""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            return bad is None
    except Exception:
        return False


def check_reader_standard(path: str) -> list:
    """标准级：主流阅读器兼容检查
    检查项参考 EPUB 3.0 规范 + Apple Books / Adobe Digital Editions 常见要求
    """
    issues = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()

            if not names:
                issues.append("ZIP 内无文件")
                return issues

            if names[0] != "mimetype":
                issues.append(f"第一个文件不是 mimetype，而是 '{names[0]}'")

            if "mimetype" in names:
                mt_info = zf.getinfo("mimetype")
                if mt_info.compress_type != zipfile.ZIP_STORED:
                    issues.append(f"mimetype 压缩方式不是 STORED: {mt_info.compress_type}")
                if mt_info.flag_bits & 0x08:
                    issues.append("mimetype 使用了数据描述符（flag bit 3 置位）")

            mt_data = zf.read("mimetype")
            expected = b"application/epub+zip"
            if mt_data != expected:
                issues.append(f"mimetype 内容错误: {mt_data!r}")

            try:
                container = zf.read("META-INF/container.xml").decode("utf-8")
                if "container" not in container.lower():
                    issues.append("META-INF/container.xml 内容异常")
            except KeyError:
                issues.append("缺少 META-INF/container.xml")

    except Exception as e:
        issues.append(f"ZIP 读取失败: {e}")

    return issues


def check_reader_strict(path: str, original_infos: dict) -> list:
    """严格级：对 ZIP 细节敏感的阅读器（如老版本 Kindle、部分国产阅读器）
    检查 central directory 与 local file header 的一致性、时间戳、额外字段
    """
    issues = []
    try:
        with open(path, "rb") as f:
            data = f.read()

        eocd_pos = data.rfind(b"PK\x05\x06")
        if eocd_pos < 0:
            issues.append("找不到 End of Central Directory")
            return issues

        eocd = data[eocd_pos:eocd_pos + 22]
        total_entries = struct.unpack_from("<H", eocd, 10)[0]
        central_size = struct.unpack_from("<I", eocd, 12)[0]
        central_offset = struct.unpack_from("<I", eocd, 16)[0]

        central_data = data[central_offset:central_offset + central_size]

        entry_names = []
        pos = 0
        while pos < len(central_data):
            if not central_data[pos:pos + 4].startswith(b"PK\x01\x02"):
                break
            comp_size = struct.unpack_from("<I", central_data, pos + 20)[0]
            uncomp_size = struct.unpack_from("<I", central_data, pos + 24)[0]
            name_len = struct.unpack_from("<H", central_data, pos + 28)[0]
            extra_len = struct.unpack_from("<H", central_data, pos + 30)[0]
            comment_len = struct.unpack_from("<H", central_data, pos + 32)[0]
            local_offset = struct.unpack_from("<I", central_data, pos + 42)[0]
            name = central_data[pos + 46:pos + 46 + name_len].decode("utf-8", errors="replace")
            entry_names.append(name)

            local_header = data[local_offset:local_offset + 30]
            if not local_header.startswith(b"PK\x03\x04"):
                issues.append(f"{name}: local file header 签名错误")

            local_name_len = struct.unpack_from("<H", local_header, 26)[0]
            local_extra_len = struct.unpack_from("<H", local_header, 28)[0]

            orig = original_infos.get(name)
            if orig:
                if orig["extra"] and extra_len == 0 and local_extra_len == 0:
                    issues.append(f"{name}: extra 字段丢失")

            if name == "mimetype":
                if local_offset != 0:
                    pass
                local_data_start = local_offset + 30 + local_name_len + local_extra_len
                if comp_size == 0:
                    actual_size = uncomp_size
                else:
                    actual_size = comp_size
                if local_data_start + actual_size > central_offset:
                    issues.append("文件数据与 central directory 区域重叠")

            pos += 46 + name_len + extra_len + comment_len

        if len(entry_names) != total_entries:
            issues.append(f"条目数不一致: EOCD={total_entries} 实际解析={len(entry_names)}")

        if entry_names and entry_names[0] != "mimetype":
            issues.append(f"Central Directory 中首个文件不是 mimetype: {entry_names[0]}")

    except Exception as e:
        issues.append(f"严格检查异常: {e}")

    return issues


def check_uniform_processing(path: str, original_infos: dict) -> list:
    """超严格级：检查所有文件是否经过统一处理
    所有文件的属性保留模式应一致，不能有的文件保留了 date_time 有的没有
    """
    issues = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) < 2:
                return issues

            opf_found = False
            other_correct = 0
            other_total = 0

            for info in infos:
                orig = original_infos.get(info.filename)
                if not orig:
                    continue
                if info.filename == "OEBPS/content.opf":
                    opf_found = True
                    if info.date_time != orig["date_time"]:
                        issues.append(f"OPF date_time 被修改: {orig['date_time']} -> {info.date_time}")
                else:
                    other_total += 1
                    if info.date_time == orig["date_time"]:
                        other_correct += 1

            if opf_found and other_total > 0 and other_correct != other_total:
                issues.append(f"属性保留不一致: OPF保留但 {other_total - other_correct}/{other_total} 个其他文件未保留")

    except Exception as e:
        issues.append(f"一致性检查异常: {e}")

    return issues


def run_tests():
    tr = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="epub_test_")
    epub_path = os.path.join(tmpdir, "test.epub")
    try:
        make_test_epub(epub_path)
        print(f"[SETUP] 测试 EPUB 已生成: {epub_path}")

        original_infos = {}
        with zipfile.ZipFile(epub_path, "r") as zf:
            before_names = zf.namelist()
            print(f"[INFO]  文件数: {len(before_names)}")
            print(f"[INFO]  顺序: {before_names}")
            for info in zf.infolist():
                original_infos[info.filename] = {
                    "date_time": info.date_time,
                    "compress_type": info.compress_type,
                    "create_system": info.create_system,
                    "external_attr": info.external_attr,
                    "internal_attr": info.internal_attr,
                    "CRC": info.CRC,
                    "file_size": info.file_size,
                    "extra": info.extra,
                    "flag_bits": info.flag_bits,
                }

        parser = MetadataParser()
        editor = MetadataEditor()
        book = parser.parse(epub_path)

        tr.section("基础级: ZIP 结构完整性 (所有阅读器都要求)")
        if check_zip_structure(epub_path):
            tr.ok("原始 EPUB testzip 通过")
        else:
            tr.fail("原始 EPUB testzip 失败")

        book.title = "更新后的书名"
        book.author = "更新后的作者"
        book.publisher = "更新后的出版社"
        book.publish_date = "2024-12"
        book.isbn = "9787111111111"
        book.language = "zh-CN"
        book.description = "更新后的简介文本。"

        result = editor.save_epub_metadata(book)
        if result:
            tr.ok("save_epub_metadata 返回 True")
        else:
            tr.fail("save_epub_metadata 返回 False")

        if check_zip_structure(epub_path):
            tr.ok("保存后 testzip 通过")
        else:
            tr.fail("保存后 testzip 失败")

        tr.section("标准级: 主流阅读器兼容 (Apple Books / ADE / 微信读书)")
        issues = check_reader_standard(epub_path)
        if not issues:
            tr.ok("所有标准级检查通过")
        else:
            for issue in issues:
                tr.fail(issue)

        with zipfile.ZipFile(epub_path, "r") as zf:
            names = zf.namelist()
            if names[0] == "mimetype":
                tr.ok("mimetype 是首个文件")
            else:
                tr.fail(f"mimetype 不是首个文件: {names[0]}")

            mt_info = zf.getinfo("mimetype")
            if mt_info.compress_type == zipfile.ZIP_STORED:
                tr.ok("mimetype 为 ZIP_STORED")
            else:
                tr.fail(f"mimetype 压缩方式: {mt_info.compress_type}")

            if before_names[1:] == names[1:]:
                tr.ok("非 mimetype 文件顺序保持不变")
            else:
                tr.fail("非 mimetype 文件顺序改变")

        tr.section("严格级: 对 ZIP 细节敏感的阅读器 (老Kindle/部分国产阅读器)")
        issues = check_reader_strict(epub_path, original_infos)
        if not issues:
            tr.ok("所有严格级检查通过")
        else:
            for issue in issues:
                tr.fail(issue)

        with zipfile.ZipFile(epub_path, "r") as zf:
            unchanged = [n for n in before_names if n not in ("mimetype", "OEBPS/content.opf")]
            for name in unchanged:
                info = zf.getinfo(name)
                orig = original_infos[name]
                if info.date_time == orig["date_time"]:
                    tr.ok(f"{name}: date_time 保留")
                else:
                    tr.fail(f"{name}: date_time 改变 {orig['date_time']} -> {info.date_time}")

                if info.create_system == orig["create_system"]:
                    tr.ok(f"{name}: create_system 保留")
                else:
                    tr.fail(f"{name}: create_system 改变")

                if info.extra == orig["extra"]:
                    tr.ok(f"{name}: extra 字段保留")
                else:
                    tr.fail(f"{name}: extra 字段丢失/改变")

                if info.compress_type == orig["compress_type"]:
                    tr.ok(f"{name}: compress_type 保留")
                else:
                    tr.fail(f"{name}: compress_type 改变")

        tr.section("超严格级: 统一处理流程一致性")
        issues = check_uniform_processing(epub_path, original_infos)
        if not issues:
            tr.ok("所有文件处理流程一致，属性保留模式统一")
        else:
            for issue in issues:
                tr.fail(issue)

        with zipfile.ZipFile(epub_path, "r") as zf:
            all_have_date = all(info.date_time != (1980, 1, 1, 0, 0, 0) for info in zf.infolist())
            if all_have_date:
                tr.ok("所有文件均有有效 date_time（无默认1980年值）")
            else:
                bad = [info.filename for info in zf.infolist() if info.date_time == (1980, 1, 1, 0, 0, 0)]
                tr.fail(f"以下文件 date_time 为默认值（可能未经过 copy_zipinfo）: {bad}")

        tr.section("功能验证: 元数据正确写入")
        book2 = parser.parse(epub_path)
        checks = [
            ("title", book2.title, "更新后的书名"),
            ("author", book2.author, "更新后的作者"),
            ("publisher", book2.publisher, "更新后的出版社"),
            ("publish_date", book2.publish_date, "2024-12"),
            ("language", book2.language, "zh-CN"),
            ("description", book2.description, "更新后的简介文本。"),
        ]
        for name, actual, expected in checks:
            if actual == expected:
                tr.ok(f"{name}='{actual}' 正确")
            else:
                tr.fail(f"{name}: 期望 '{expected}' 实际 '{actual}'")

    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

    print()
    print("=" * 60)
    print(f"总测试: {tr.passed + tr.failed} 项  |  通过: {tr.passed}  |  失败: {tr.failed}")
    print("=" * 60)
    return tr.failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

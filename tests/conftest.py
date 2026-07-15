from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest


_CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''

_OPF = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:test:normal</dc:identifier>
    <dc:title>Fixture Book</dc:title>
    <dc:creator>Test Author</dc:creator>
  </metadata>
  <manifest>
    <item id="second" href="text/second.xhtml" media-type="application/xhtml+xml"/>
    <item id="first" href="text/first.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="images/cover.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="second"/><itemref idref="first"/></spine>
</package>'''


def _write_epub(path: Path, entries: dict[str, bytes], *, compress_type: int = zipfile.ZIP_DEFLATED) -> Path:
    """Write the smallest valid EPUB shape, with the required mimetype first."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in entries.items():
            archive.writestr(name, content, compress_type=compress_type)
    return path


@pytest.fixture
def normal_epub(tmp_path: Path) -> Path:
    return _write_epub(
        tmp_path / "normal.epub",
        {
            "META-INF/container.xml": _CONTAINER_XML.encode(),
            "OPS/book.opf": _OPF.encode(),
            "OPS/text/second.xhtml": "<html><body><h1>Second first</h1><p>English sentence. 한국어 문장입니다.</p></body></html>".encode(),
            "OPS/text/first.xhtml": b"<html><body><h1>First second</h1><p>Another chapter follows.</p></body></html>",
            "OPS/images/cover.png": b"not-a-real-image",
        },
    )


@pytest.fixture
def corrupt_epub(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.epub"
    path.write_bytes(b"PK\x03\x04this is not a complete ZIP archive")
    return path


@pytest.fixture
def traversal_epub(tmp_path: Path) -> Path:
    return _write_epub(
        tmp_path / "traversal.epub",
        {
            "META-INF/container.xml": _CONTAINER_XML.encode(),
            "OPS/book.opf": _OPF.encode(),
            "../outside.xhtml": b"<p>Never parse this.</p>",
        },
    )


@pytest.fixture
def compressed_epub(tmp_path: Path) -> Path:
    return _write_epub(
        tmp_path / "compressed.epub",
        {
            "META-INF/container.xml": _CONTAINER_XML.encode(),
            "OPS/book.opf": _OPF.encode(),
            "OPS/padding.bin": b"0" * 250_000,
        },
    )


@pytest.fixture
def encrypted_epub(tmp_path: Path) -> Path:
    """Mark a harmless ZIP entry encrypted in both ZIP headers without decrypting it."""
    path = _write_epub(
        tmp_path / "encrypted.epub",
        {"META-INF/container.xml": _CONTAINER_XML.encode(), "OPS/book.opf": _OPF.encode()},
    )
    data = bytearray(path.read_bytes())
    central = data.index(b"PK\x01\x02")
    flags = struct.unpack_from("<H", data, central + 8)[0]
    struct.pack_into("<H", data, central + 8, flags | 1)
    local_offset = struct.unpack_from("<I", data, central + 42)[0]
    local_flags = struct.unpack_from("<H", data, local_offset + 6)[0]
    struct.pack_into("<H", data, local_offset + 6, local_flags | 1)
    path.write_bytes(data)
    return path


@pytest.fixture
def hidden_html(tmp_path: Path) -> Path:
    path = tmp_path / "hidden.html"
    path.write_text(
        """<html><head><title>Visible title</title><style>.x { color: red; }</style></head>
        <body><h1>Visible heading</h1><p>Visible English sentence. 한국어 문장입니다.</p>
        <p hidden>Hidden attribute text.</p><p aria-hidden="true">ARIA hidden text.</p>
        <div style="display: none"><p>Display hidden text.</p></div>
        <p style="visibility: hidden">Visibility hidden text.</p><script>script text</script></body></html>""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text("First paragraph.\n\n둘째 문장입니다. English follows.", encoding="utf-8")
    return path


@pytest.fixture
def input_directory(tmp_path: Path) -> Path:
    root = tmp_path / "book-directory"
    (root / "nested").mkdir(parents=True)
    (root / "z.html").write_text("<p>Z chapter.</p>", encoding="utf-8")
    (root / "nested" / "a.txt").write_text("A chapter.", encoding="utf-8")
    (root / "ignore.bin").write_bytes(b"not text")
    return root

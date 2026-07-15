from __future__ import annotations

import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from ebook_risk_analyzer import epub_parser
from ebook_risk_analyzer.epub_parser import parse_epub


def test_parse_epub_reads_metadata_spine_order_and_manifest_resources(normal_epub: Path) -> None:
    before = normal_epub.read_bytes()

    book = parse_epub(normal_epub)

    assert book.metadata == {
        "identifier": "urn:test:normal",
        "title": "Fixture Book",
        "creator": "Test Author",
    }
    assert [chapter.file for chapter in book.chapters] == [
        "OPS/text/second.xhtml",
        "OPS/text/first.xhtml",
    ]
    assert [chapter.title for chapter in book.chapters] == ["Second first", "First second"]
    assert [resource.path for resource in book.resources] == [
        "OPS/text/second.xhtml",
        "OPS/text/first.xhtml",
        "OPS/images/cover.png",
    ]
    assert [resource.referenced for resource in book.resources] == [True, True, False]
    assert book.resources[-1].media_type == "image/png"
    assert book.resources[-1].sha256 == hashlib.sha256(b"not-a-real-image").hexdigest()
    assert book.source_path == normal_epub
    assert book.sha256 == hashlib.sha256(before).hexdigest()
    assert normal_epub.read_bytes() == before


def test_parse_epub_preserves_bilingual_sentence_locations(normal_epub: Path) -> None:
    book = parse_epub(normal_epub)
    sentences = book.chapters[0].paragraphs[0].sentences

    assert [sentence.text for sentence in sentences] == ["English sentence.", "한국어 문장입니다."]
    assert [sentence.location.file for sentence in sentences] == ["OPS/text/second.xhtml"] * 2
    assert [sentence.location.chapter for sentence in sentences] == ["Second first"] * 2
    assert [sentence.location.paragraph for sentence in sentences] == [0, 0]
    assert [sentence.location.sentence for sentence in sentences] == [0, 1]


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("corrupt_epub", "valid EPUB ZIP archive"),
        ("traversal_epub", "unsafe archive path"),
        ("encrypted_epub", "encrypted entry"),
        ("compressed_epub", "suspicious compression ratio"),
    ],
)
def test_parse_epub_rejects_unsafe_or_invalid_containers(request: pytest.FixtureRequest, fixture_name: str, message: str) -> None:
    path = request.getfixturevalue(fixture_name)
    before = path.read_bytes()

    with pytest.raises(ValueError, match=message):
        parse_epub(path)

    assert path.read_bytes() == before


def test_parse_epub_is_deterministic(normal_epub: Path) -> None:
    first = parse_epub(normal_epub)
    second = parse_epub(normal_epub)

    assert second == first
def test_parse_epub_grounds_cover_css_svg_and_picture_resources(tmp_path: Path) -> None:
    epub = tmp_path / "resource-references.epub"
    container = """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
    <rootfile full-path="OPS/book.opf"/></rootfiles></container>"""
    opf = """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata>
    <meta name="cover" content="legacy-cover"/></metadata><manifest>
    <item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="legacy-cover" href="images/legacy-cover.png" media-type="image/png"/>
    <item id="property-cover" href="images/property-cover.png" media-type="image/png" properties="cover-image"/>
    <item id="css" href="styles/book.css" media-type="text/css"/>
    <item id="picture" href="images/picture.webp" media-type="image/webp"/>
    <item id="svg" href="images/svg.png" media-type="image/png"/>
    <item id="object" href="images/object.png" media-type="image/png"/>
    <item id="css-image" href="images/css.png" media-type="image/png"/>
    <item id="unused" href="images/unused.png" media-type="image/png"/></manifest>
    <spine><itemref idref="chapter"/></spine></package>"""
    chapter = """<html><body><picture><source srcset="../images/picture.webp 1x"/></picture>
    <svg><image href="../images/svg.png"/></svg><object data="../images/object.png"></object></body></html>"""
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/text/chapter.xhtml", chapter)
        archive.writestr("OPS/styles/book.css", ".hero { background: url('../images/css.png'); }")
        for image in ("legacy-cover.png", "property-cover.png", "picture.webp", "svg.png", "object.png", "css.png", "unused.png"):
            archive.writestr(f"OPS/images/{image}", image.encode())

    resources = {resource.path: resource for resource in parse_epub(epub).resources}

    assert {path for path, resource in resources.items() if resource.referenced} >= {
        "OPS/images/legacy-cover.png",
        "OPS/images/property-cover.png",
        "OPS/images/picture.webp",
        "OPS/images/svg.png",
        "OPS/images/object.png",
        "OPS/images/css.png",
    }
    assert resources["OPS/images/unused.png"].referenced is False
    assert resources["OPS/images/picture.webp"].alt_text is None

def test_parse_epub_rejects_declared_member_limit_before_zipfile_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "too-many-members.epub"
    with zipfile.ZipFile(epub, "w") as archive:
        for index in range(4):
            archive.writestr(f"{index}.txt", b"")

    monkeypatch.setattr(epub_parser, "_MAX_ARCHIVE_MEMBERS", 3)

    def unexpected_zipfile(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile construction must not occur")

    monkeypatch.setattr(epub_parser.zipfile, "ZipFile", unexpected_zipfile)
    with pytest.raises(ValueError, match="too many archive members"):
        parse_epub(epub)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (b"PK\x05\x06", "malformed or truncated end-of-central-directory"),
        (
            struct.pack("<4sLQL", b"PK\x06\x07", 0, 0, 1)
            + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0, 0, 0, 0, 0),
            "truncated ZIP64 end-of-central-directory",
        ),
    ],
)
def test_parse_epub_rejects_malformed_zip_metadata_before_zipfile_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: bytes,
    message: str,
) -> None:
    epub = tmp_path / "malformed.epub"
    epub.write_bytes(contents)

    def unexpected_zipfile(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile construction must not occur")

    monkeypatch.setattr(epub_parser.zipfile, "ZipFile", unexpected_zipfile)
    with pytest.raises(ValueError, match=message):
        parse_epub(epub)


def test_parse_epub_accepts_zip64_end_of_central_directory(normal_epub: Path) -> None:
    original = normal_epub.read_bytes()
    eocd_offset = original.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    _, disk, central_disk, entries_disk, entries, central_size, central_offset, comment_size = struct.unpack(
        "<4s4H2LH", original[eocd_offset : eocd_offset + 22]
    )
    assert comment_size == 0
    zip64_eocd = struct.pack(
        "<4sQ2H2L4Q",
        b"PK\x06\x06",
        44,
        45,
        45,
        disk,
        central_disk,
        entries_disk,
        entries,
        central_size,
        central_offset,
    )
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, eocd_offset, 1)
    eocd = struct.pack(
        "<4s4H2LH", b"PK\x05\x06", disk, central_disk, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    normal_epub.write_bytes(original[:eocd_offset] + zip64_eocd + locator + eocd)

    try:
        assert parse_epub(normal_epub).metadata["title"] == "Fixture Book"
    finally:
        normal_epub.write_bytes(original)
def _central_directory_fields(contents: bytes) -> tuple[int, int, int, int]:
    eocd_offset = contents.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    _, _, _, _, member_count, central_size, central_offset, comment_size = struct.unpack(
        "<4s4H2LH", contents[eocd_offset : eocd_offset + 22]
    )
    assert comment_size == 0
    return eocd_offset, member_count, central_size, central_offset


def test_parse_epub_rejects_forged_low_member_count_before_zipfile_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "forged-count.epub"
    with zipfile.ZipFile(epub, "w") as archive:
        for index in range(4):
            archive.writestr(f"{index}.txt", b"")
    contents = bytearray(epub.read_bytes())
    eocd_offset, _, _, _ = _central_directory_fields(contents)
    struct.pack_into("<H", contents, eocd_offset + 10, 0)
    epub.write_bytes(contents)
    monkeypatch.setattr(epub_parser, "_MAX_ARCHIVE_MEMBERS", 3)
    monkeypatch.setattr(
        epub_parser.zipfile, "ZipFile", lambda *args, **kwargs: pytest.fail("ZipFile must not be constructed")
    )

    with pytest.raises(ValueError, match="too many archive members"):
        parse_epub(epub)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("oversized", "central directory is too large"),
        ("mismatched-size", "malformed central-directory header"),
        ("malformed-header", "malformed central-directory header"),
        ("malformed-length", "malformed central-directory header length"),
    ],
)
def test_parse_epub_rejects_invalid_central_directory_before_zipfile_construction(
    normal_epub: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    contents = bytearray(normal_epub.read_bytes())
    eocd_offset, _, central_size, central_offset = _central_directory_fields(contents)
    if mutation == "oversized":
        monkeypatch.setattr(epub_parser, "_MAX_CENTRAL_DIRECTORY_SIZE", central_size - 1)
    elif mutation == "mismatched-size":
        struct.pack_into("<L", contents, eocd_offset + 12, central_size - 1)
    elif mutation == "malformed-header":
        contents[central_offset : central_offset + 4] = b"BAD!"
    else:
        struct.pack_into("<H", contents, central_offset + 28, 0xFFFF)
    normal_epub.write_bytes(contents)
    monkeypatch.setattr(
        epub_parser.zipfile, "ZipFile", lambda *args, **kwargs: pytest.fail("ZipFile must not be constructed")
    )

    with pytest.raises(ValueError, match=message):
        parse_epub(normal_epub)


def _write_inventory_epub(
    path: Path, *, manifest_items: int = 1, spine_items: int = 1, resources: int = 1
) -> None:
    manifest = [
        '<item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>'
    ]
    manifest.extend(
        f'<item id="resource-{index}" href="resources/{index}.bin" media-type="application/octet-stream"/>'
        for index in range(1, manifest_items)
    )
    spine = "".join('<itemref idref="chapter"/>' for _ in range(spine_items))
    opf = f"""<package xmlns="http://www.idpf.org/2007/opf"><metadata/>
    <manifest>{''.join(manifest)}</manifest><spine>{spine}</spine></package>"""
    container = """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/text/chapter.xhtml", "<html><body>Chapter.</body></html>")
        for index in range(1, resources):
            archive.writestr(f"OPS/resources/{index}.bin", b"resource")


@pytest.mark.parametrize(
    ("constant", "value", "kwargs", "message"),
    [
        ("_MAX_ARCHIVE_MEMBERS", 3, {}, "too many archive members"),
        ("_MAX_MANIFEST_ITEMS", 1, {"manifest_items": 2}, "too many manifest items"),
        ("_MAX_SPINE_ITEMS", 1, {"spine_items": 2}, "too many spine items"),
        ("_MAX_PACKAGED_RESOURCES", 1, {"resources": 2}, "too many packaged resources"),
    ],
)
def test_parse_epub_rejects_inventory_limits_without_mutating_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    value: int,
    kwargs: dict[str, int],
    message: str,
) -> None:
    epub = tmp_path / f"{constant}.epub"
    _write_inventory_epub(epub, **kwargs)
    before = epub.read_bytes()
    monkeypatch.setattr(epub_parser, constant, value)

    with pytest.raises(ValueError, match=message):
        parse_epub(epub)

    assert epub.read_bytes() == before

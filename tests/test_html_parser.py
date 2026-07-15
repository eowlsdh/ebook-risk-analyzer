from __future__ import annotations

import hashlib
from pathlib import Path

import zipfile
import pytest

from ebook_risk_analyzer.html_parser import parse_directory, parse_html, parse_text
import ebook_risk_analyzer.html_parser as html_parser
from ebook_risk_analyzer.epub_parser import parse_epub
from ebook_risk_analyzer.analyzer import parse_source


def test_parse_html_removes_hidden_and_non_reader_content(hidden_html: Path) -> None:
    before = hidden_html.read_bytes()

    book = parse_html(hidden_html)

    assert book.metadata == {"title": "Visible title"}
    chapter = book.chapters[0]
    assert chapter.title == "Visible title"
    assert chapter.file == "hidden.html"
    assert chapter.headings == ["Visible heading"]
    assert [paragraph.text for paragraph in chapter.paragraphs] == ["Visible English sentence. 한국어 문장입니다."]
    extracted = " ".join(paragraph.text for paragraph in chapter.paragraphs)
    for hidden_text in ("Hidden attribute", "ARIA hidden", "Display hidden", "Visibility hidden", "script text"):
        assert hidden_text not in extracted
    assert book.sha256 == hashlib.sha256(before).hexdigest()
    assert hidden_html.read_bytes() == before


def test_parse_html_assigns_bilingual_sentence_locations(hidden_html: Path) -> None:
    sentences = parse_html(hidden_html).chapters[0].paragraphs[0].sentences

    assert [sentence.text for sentence in sentences] == ["Visible English sentence.", "한국어 문장입니다."]
    assert [(sentence.location.file, sentence.location.chapter, sentence.location.paragraph, sentence.location.sentence) for sentence in sentences] == [
        ("hidden.html", "Visible title", 0, 0),
        ("hidden.html", "Visible title", 0, 1),
    ]


def test_parse_text_preserves_paragraph_and_sentence_locations(text_file: Path) -> None:
    before = text_file.read_bytes()

    book = parse_text(text_file)

    assert book.metadata == {"title": "notes"}
    assert [paragraph.text for paragraph in book.chapters[0].paragraphs] == ["First paragraph.", "둘째 문장입니다. English follows."]
    locations = [
        (sentence.text, sentence.location.file, sentence.location.chapter, sentence.location.paragraph, sentence.location.sentence)
        for paragraph in book.chapters[0].paragraphs
        for sentence in paragraph.sentences
    ]
    assert locations == [
        ("First paragraph.", "notes.txt", "notes", 0, 0),
        ("둘째 문장입니다.", "notes.txt", "notes", 1, 0),
        ("English follows.", "notes.txt", "notes", 1, 1),
    ]
    assert text_file.read_bytes() == before


def test_parse_directory_uses_sorted_relative_paths_and_is_deterministic(input_directory: Path) -> None:
    before = {path.relative_to(input_directory).as_posix(): path.read_bytes() for path in input_directory.rglob("*") if path.is_file()}

    first = parse_directory(input_directory)
    second = parse_directory(input_directory)

    assert [chapter.file for chapter in first.chapters] == ["nested/a.txt", "z.html"]
    assert first.chapters[0].paragraphs[0].sentences[0].location.file == "nested/a.txt"
    assert first == second
    assert {path.relative_to(input_directory).as_posix(): path.read_bytes() for path in input_directory.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("parser", [parse_html, parse_text, parse_directory])
def test_parsers_reject_wrong_input_kind(tmp_path: Path, parser: object) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ValueError, match="not .*readable|contains no"):
        parser(missing)  # type: ignore[operator]
def test_parse_html_extracts_metadata_and_local_resources(tmp_path: Path) -> None:
    image = tmp_path / "cover.png"
    stylesheet = tmp_path / "book.css"
    image.write_bytes(b"image")
    stylesheet.write_text("body { color: black; }", encoding="utf-8")
    document = tmp_path / "book.html"
    document.write_text(
        """<!doctype html><html lang="ko"><head><title>책 제목</title>
        <meta name="author" content="Writer"><meta name="generator" content="Tool">
        <meta name="description" content="Summary"><link rel="stylesheet" href="book.css">
        </head><body><img src="cover.png" alt="표지 그림"><img src="https://example.test/remote.png"></body></html>""",
        encoding="utf-8",
    )

    book = parse_html(document)

    assert book.metadata == {"title": "책 제목", "language": "ko", "author": "Writer", "generator": "Tool", "description": "Summary"}
    assert [(resource.path, resource.media_type, resource.referenced, resource.alt_text) for resource in book.resources] == [
        (str(stylesheet.resolve()), "text/css", True, None),
        (str(image.resolve()), "image/png", True, "표지 그림"),
    ]

def test_parse_source_rejects_oversized_referenced_resource_before_hashing(tmp_path: Path) -> None:
    image = tmp_path / "large.png"
    image.write_bytes(b"0123456789" * 10)
    document = tmp_path / "book.html"
    document.write_text('<img src="large.png">', encoding="utf-8")

    with pytest.raises(ValueError, match="Referenced resource exceeds max-file-size"):
        parse_source(document, max_file_size=50)


def test_parse_directory_rejects_resources_over_aggregate_budget(tmp_path: Path) -> None:
    (tmp_path / "one.png").write_bytes(b"12345")
    (tmp_path / "two.css").write_bytes(b"12345")
    (tmp_path / "book.html").write_text(
        '<img src="one.png"><link rel="stylesheet" href="two.css">', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Referenced resources exceed 9 total bytes"):
        parse_directory(tmp_path, max_file_size=10, max_total_size=9)


def test_parse_directory_aggregates_sorted_local_resources(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "used.png").write_bytes(b"used")
    (tmp_path / "assets" / "unused.jpg").write_bytes(b"unused")
    (tmp_path / "assets" / "site.css").write_text("", encoding="utf-8")
    (tmp_path / "chapter.html").write_text(
        '<link rel="stylesheet" href="assets/site.css"><img src="assets/used.png" alt="diagram">',
        encoding="utf-8",
    )

    book = parse_directory(tmp_path)

    assert [(resource.path, resource.referenced, resource.alt_text) for resource in book.resources] == [
        ("assets/site.css", True, None),
        ("assets/unused.jpg", False, None),
        ("assets/used.png", True, "diagram"),
    ]

def test_parse_directory_recognizes_extended_local_resource_references(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    names = {
        "css-url.png",
        "inline-style.png",
        "picture-source.png",
        "picture-small.png",
        "picture-large.png",
        "svg-href.png",
        "svg-xlink.png",
        "object.svg",
        "embed.png",
        "unused.png",
    }
    for name in names:
        (assets / name).write_bytes(name.encode("utf-8"))
    (tmp_path / "chapter.html").write_text(
        """<style>.cover { background-image: url("assets/css-url.png"); }</style>
        <div style="background: url(assets/inline-style.png)"></div>
        <picture><source src="assets/picture-source.png"
        srcset="assets/picture-small.png 1x, assets/picture-large.png 2x"></picture>
        <svg><image href="assets/svg-href.png" xlink:href="assets/svg-xlink.png"/></svg>
        <object data="assets/object.svg"></object><embed src="assets/embed.png">""",
        encoding="utf-8",
    )

    resources = {resource.path: resource for resource in parse_directory(tmp_path).resources}

    assert {name for name, resource in resources.items() if resource.referenced} == {
        f"assets/{name}" for name in names - {"unused.png"}
    }
    assert (resources["assets/unused.png"].referenced, resources["assets/unused.png"].alt_text) == (False, None)


def test_parse_directory_rejects_excess_resource_files_before_resource_hashing(tmp_path: Path,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    for index in range(3):
        (tmp_path / f"resource-{index}.png").write_bytes(b"resource")
    (tmp_path / "chapter.html").write_text("<p>Text.</p>", encoding="utf-8")

    def fail_resource(*args: object) -> object:
        raise AssertionError("resource hashing should not begin")

    monkeypatch.setattr(html_parser, "_resource", fail_resource)
    with pytest.raises(ValueError, match="more than 2 resource files"):
        parse_directory(tmp_path, max_resource_files=2)


def test_parse_epub_grounds_image_reference_and_alt_text(tmp_path: Path) -> None:
    epub = tmp_path / "grounded.epub"
    container = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>"""
    opf = """<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Grounded</dc:title></metadata>
    <manifest><item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="used" href="images/used.png" media-type="image/png"/><item id="unused" href="images/unused.png" media-type="image/png"/></manifest>
    <spine><itemref idref="chapter"/></spine></package>"""
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/text/chapter.xhtml", '<p>Text.</p><img src="../images/used.png" alt="Chart">')
        archive.writestr("OPS/images/used.png", b"used")
        archive.writestr("OPS/images/unused.png", b"unused")

    resources = {resource.path: resource for resource in parse_epub(epub).resources}

    assert (resources["OPS/images/used.png"].referenced, resources["OPS/images/used.png"].alt_text) == (True, "Chart")
    assert (resources["OPS/images/unused.png"].referenced, resources["OPS/images/unused.png"].alt_text) == (False, None)
def test_parse_directory_rejects_source_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-book.txt"
    outside.write_text("private external content", encoding="utf-8")
    source = tmp_path / "book"
    source.mkdir()
    linked = source / "linked.txt"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform")
    with pytest.raises(ValueError, match="unsafe linked source file"):
        parse_directory(source)

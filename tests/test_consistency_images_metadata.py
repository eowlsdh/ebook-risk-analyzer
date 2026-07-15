from pathlib import Path

import pytest
from ebook_risk_analyzer.detectors.consistency import detect_consistency
from ebook_risk_analyzer.detectors.images import detect_images
from ebook_risk_analyzer.detectors.metadata import detect_metadata
from ebook_risk_analyzer.models import Book, Chapter, Paragraph, Resource, Sentence, SentenceLocation
from ebook_risk_analyzer.html_parser import parse_directory


def _chapter(texts: list[str]) -> Chapter:
    chapter = Chapter(title="Chapter 1", file="chapter-1.xhtml")
    chapter.paragraphs = [
        Paragraph(text, index, [Sentence(text, SentenceLocation(chapter.file, chapter.title, index, 0))])
        for index, text in enumerate(texts)
    ]
    return chapter


def _book(*, metadata=None, texts=None, resources=None) -> Book:
    return Book(metadata or {}, [_chapter(texts or ["Reader-facing text."])], resources or [], Path("book.epub"), "book-hash")


def _assert_review_findings(findings):
    assert findings
    for finding in findings:
        assert finding.file is not None and finding.chapter is not None
        assert finding.paragraph is not None and finding.sentence is not None
        assert finding.excerpt and finding.reason and finding.review_action
        wording = f"{finding.reason} {finding.review_action}".casefold()
        assert not any(term in wording for term in ("ai-generated", "written by ai", "certainty", "probability"))


def test_consistency_reports_numeric_and_name_variants_as_candidates():
    book = _book(texts=[
        "The report describes 12 years old participants and 25 years old participants, with 25% and 40% completing the survey.",
        "Ada Lovelace presented the first method.",
        "Augusta Lovelace revised the later method.",
    ])

    findings = detect_consistency(book)
    codes = {finding.code for finding in findings}

    assert {"multiple_ages", "multiple_percentages", "multiple_numbers", "name_variant"} <= codes
    _assert_review_findings(findings)


def test_images_report_duplicate_and_inventory_review_signals(tmp_path):
    image_one = tmp_path / "image-1.png"
    image_two = tmp_path / "image-2.png"
    image_one.write_bytes(b"same-local-image")
    image_two.write_bytes(b"same-local-image")
    resources = [
        Resource(str(image_one), "image/png", size=16, sha256="same-hash", referenced=False, alt_text=""),
        Resource(str(image_two), "image/png", size=16, sha256="same-hash", referenced=True, alt_text="caption"),
        Resource("assets/photo.png", "image/png", size=0, sha256="", referenced=True, alt_text=None),
    ]

    findings = detect_images(_book(resources=resources))
    codes = {finding.code for finding in findings}

    assert {"duplicate_image", "unused_image", "missing_alt_text", "missing_size", "missing_hash", "generic_filename_weak", "missing_image_license_context"} <= codes
    _assert_review_findings(findings)


def test_metadata_reports_required_field_omissions_with_stable_locations():
    book = _book(metadata={"title": "", "creator": "", "language": "en"})

    first = detect_metadata(book)
    second = detect_metadata(book)

    assert first == second
    assert {finding.code for finding in first} == {"missing_title", "missing_creator", "missing_identifier"}
    _assert_review_findings(first)
def test_no_image_inventory_finding_has_grounded_excerpt():
    findings = detect_images(_book(resources=[]))

    assert len(findings) == 1
    assert findings[0].code == "no_images_inventory"
    assert findings[0].excerpt == "Image inventory: no image resources recorded for source file chapter-1.xhtml."


def test_parse_directory_resource_count_boundary_is_checked_before_hashing(tmp_path, monkeypatch):
    (tmp_path / "chapter.html").write_text("<p>Text.</p>", encoding="utf-8")
    for index in range(2):
        (tmp_path / f"resource-{index}.png").write_bytes(b"resource")

    hashed: list[str] = []

    def record_resource(path, name, referenced, alt_text):
        hashed.append(name)
        return Resource(name, "image/png", 8, "hash", referenced, alt_text)

    monkeypatch.setattr("ebook_risk_analyzer.html_parser._resource", record_resource)
    parse_directory(tmp_path, max_resource_files=2)
    assert hashed == ["resource-0.png", "resource-1.png"]

    (tmp_path / "resource-2.png").write_bytes(b"resource")
    hashed.clear()
    with pytest.raises(ValueError, match="more than 2 resource files"):
        parse_directory(tmp_path, max_resource_files=2)
    assert not hashed

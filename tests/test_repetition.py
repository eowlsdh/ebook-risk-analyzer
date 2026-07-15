from pathlib import Path
import pytest

from ebook_risk_analyzer import text_normalizer
from ebook_risk_analyzer.detectors import repetition, structure, style_patterns

from ebook_risk_analyzer.detectors.repetition import detect_repetition
from ebook_risk_analyzer.models import Book, Chapter, Finding, Paragraph, Sentence, SentenceLocation


def _chapter(title: str, file: str, paragraphs: list[str]) -> Chapter:
    chapter = Chapter(title=title, file=file)
    chapter.paragraphs = [
        Paragraph(
            text=text,
            index=index,
            sentences=[Sentence(text, SentenceLocation(file, title, index, 0))],
        )
        for index, text in enumerate(paragraphs)
    ]
    return chapter


def _book(*chapters: Chapter) -> Book:
    return Book({}, list(chapters), [], Path("book.epub"), "book-hash")


def _assert_review_findings(findings):
    assert findings
    for finding in findings:
        assert finding.file and finding.chapter
        assert finding.paragraph is not None and finding.sentence is not None
        assert finding.excerpt and finding.reason and finding.review_action
        assert "ai-generated" not in f"{finding.reason} {finding.review_action}".casefold()


def test_reports_exact_sentence_and_paragraph_repetition_with_locations():
    repeated = "The harbor lights guided every traveler safely home tonight."
    book = _book(_chapter("One", "one.xhtml", [repeated]), _chapter("Two", "two.xhtml", [repeated]))

    findings = detect_repetition(book)
    codes = {finding.code for finding in findings}

    assert {"exact_sentence", "exact_paragraph"} <= codes
    assert any(finding.file == "two.xhtml" and finding.paragraph == 0 for finding in findings)
    _assert_review_findings(findings)


def test_reports_similar_wording_and_repeated_ngram_deterministically():
    first = "Quiet rivers carry silver moonlight through the sleeping valley every night."
    similar = "Quiet rivers carry silver moonlight across the sleeping valley each night."
    ngram_peer = "Travelers watched quiet rivers carry silver moonlight beside the old bridge."
    book = _book(_chapter("One", "one.xhtml", [first]), _chapter("Two", "two.xhtml", [similar, ngram_peer]))
    config = {"repetition": {"minimum_tokens": 5, "similarity_threshold": 0.7, "ngram_range": (4, 4)}}

    first_run = detect_repetition(book, config)
    second_run = detect_repetition(book, config)

    assert first_run == second_run
    codes = {finding.code for finding in first_run}
    assert "similar_sentence" in codes
    assert "similar_paragraph" in codes
    assert "ngram_4" in codes
    _assert_review_findings(first_run)
def test_repetition_caps_bound_similarity_and_ngram_work():
    sentences = [
        "Quiet rivers carry silver moonlight through the sleeping valley tonight.",
        "Quiet rivers carry silver moonlight across the sleeping valley tonight.",
        "Quiet rivers carry silver moonlight beyond the sleeping valley tonight.",
    ]
    book = _book(_chapter("One", "one.xhtml", sentences))
    findings = detect_repetition(
        book,
        {
            "repetition": {
                "minimum_tokens": 5,
                "similarity_threshold": 0.7,
                "ngram_range": (4, 4),
                "max_sentence_pairs": 0,
                "max_ngram_occurrences": 0,
            }
        },
    )

    assert not {finding.code for finding in findings} & {
        "similar_sentence",
        "similar_paragraph",
        "ngram_4",
    }
    assert {finding.code for finding in findings} == {
        "similarity_comparison_cap_reached",
        "ngram_occurrence_cap_reached",
    }
    _assert_review_findings(findings)


def test_detector_models_are_imported_directly():
    assert repetition.Book is Book
    assert style_patterns.Book is Book
    assert structure.Book is Book
    assert repetition.Finding is Finding
    assert style_patterns.Finding is Finding
    assert structure.Finding is Finding


def test_read_text_safely_enforces_the_configured_byte_limit(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("short", encoding="utf-8")

    assert text_normalizer.read_text_safely(source, 5) == "short"
    with pytest.raises(ValueError, match="exceeds the allowed size"):
        text_normalizer.read_text_safely(source, 4)

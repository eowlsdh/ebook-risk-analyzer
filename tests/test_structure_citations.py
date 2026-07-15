from pathlib import Path

from ebook_risk_analyzer.detectors.citations import detect_citations
from ebook_risk_analyzer.detectors.structure import detect_structure
from ebook_risk_analyzer.models import Book, Chapter, Paragraph, Sentence, SentenceLocation


def _chapter(title: str, file: str, texts: list[str], *, toc_title: str = "", headings: list[str] | None = None) -> Chapter:
    chapter = Chapter(title=title, file=file, toc_title=toc_title, headings=headings or [])
    chapter.paragraphs = [
        Paragraph(text, index, [Sentence(text, SentenceLocation(file, title, index, 0))])
        for index, text in enumerate(texts)
    ]
    return chapter


def _book(*chapters: Chapter) -> Book:
    return Book({}, list(chapters), [], Path("book.epub"), "book-hash")


def _assert_review_findings(findings):
    assert findings
    for finding in findings:
        assert finding.file and finding.chapter
        assert finding.paragraph is not None and finding.sentence is not None
        assert finding.excerpt is not None and finding.reason and finding.review_action
        wording = f"{finding.reason} {finding.review_action}".casefold()
        assert "ai-generated" not in wording
        assert "certainty" not in wording


def test_structure_reports_chapter_number_toc_and_editorial_remnant_candidates():
    opening = "Every journey begins with a lantern beside the river."
    closing = "The lantern fades as the chapter comes to a close."
    one = _chapter("Chapter 1", "one.xhtml", [opening, "TODO: insert image credit before publication.", closing], toc_title="First Chapter", headings=["Section 1"])
    three = _chapter("Chapter 3", "three.xhtml", [opening, "The middle passage develops the argument.", closing], toc_title="First Chapter", headings=["Section 2"])

    findings = detect_structure(_book(one, three), {"structure": {"vocabulary_diversity_min": 0.0}})
    codes = {finding.code for finding in findings}

    assert {"chapter_number_gap", "toc_title_issue", "editorial_remnant", "repeated_chapter_start", "repeated_chapter_end", "repeated_heading_structure"} <= codes
    _assert_review_findings(findings)


def test_citations_report_malformed_and_placeholder_references_without_network_access():
    book = _book(_chapter("Sources", "sources.xhtml", [
        "The draft cites doi:10.bad/.",
        "The link https://example.com/TODO should be supplied later.",
        "The link https:// should be supplied later.",
        "Citation needed.",
        "A survey reports 73% of readers preferred print editions.",
    ]))

    first = detect_citations(book)
    second = detect_citations(book)

    assert first == second
    codes = {finding.code for finding in first}
    assert {"malformed_doi", "placeholder_url", "empty_url", "source_needed_marker", "uncited_statistic_candidate"} <= codes
    _assert_review_findings(first)

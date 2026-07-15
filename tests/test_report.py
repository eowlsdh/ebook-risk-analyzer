import csv
import importlib.resources
import json
import re
from pathlib import Path

from ebook_risk_analyzer.models import AnalysisReport, Book, Chapter, Finding, Paragraph, Resource
from ebook_risk_analyzer.report_generator import generate_reports
from ebook_risk_analyzer.scoring import CATEGORY_KEYS
import ebook_risk_analyzer.analyzer as analyzer


def make_report() -> AnalysisReport:
    finding = Finding(
        "high", "repetition", "chapter.html", "<Chapter & One>", 2, 3,
        "<script>alert('x')</script>", "Repeated passage needs review.",
        "Compare against the manuscript.", "exact_repetition", 4.0, "stable-id",
    )
    book = Book(
        {"title": "<Unsafe & title>", "creator": "Review Author", "language": "en"},
        [Chapter("Chapter One", "chapter.html", [Paragraph("Visible paragraph.", 0)])],
        [Resource("images/a.png", "image/png", 12, "abc", True, "cover")],
        Path("book.html"), "digest",
    )
    return AnalysisReport(book, {"overall_score": 40.0, "risk_level": "추가 자료 확인 필요"}, {key: 0.0 for key in CATEGORY_KEYS}, [finding])


def test_generate_reports_writes_five_complete_offline_artifacts(tmp_path):
    paths = generate_reports(make_report(), tmp_path)

    assert set(paths) == {"report.json", "report.html", "findings.csv", "extracted_text.txt", "metadata.json"}
    assert all(path.is_file() for path in paths.values())
    record = json.loads(paths["report.json"].read_text(encoding="utf-8"))
    assert set(record) == {"book", "summary", "category_scores", "findings"}
    assert set(record["findings"][0]) == {"id", "severity", "category", "code", "file", "chapter", "paragraph", "sentence", "location", "excerpt", "reason", "review_action", "weight"}
    assert set(record["findings"][0]["location"]) == {"file", "chapter", "paragraph", "sentence"}
    assert set(record["category_scores"]) == set(CATEGORY_KEYS)
    assert set(record["book"]) == {"title", "author", "publisher", "language", "source_file", "sha256", "metadata", "chapter_count", "resource_count"}
    assert record["book"]["author"] == "Review Author"
    assert record["book"]["chapter_count"] == 1
    assert record["book"]["resource_count"] == 1
    assert {"overall_score", "risk_level", "risk_score", "chapter_count", "word_count", "finding_count"} <= set(record["summary"])
    assert record["summary"]["finding_count"] == len(record["findings"])

    with paths["findings.csv"].open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows == [{"id": "stable-id", "severity": "high", "category": "repetition", "code": "exact_repetition", "file": "chapter.html", "chapter": "<Chapter & One>", "paragraph": "2", "sentence": "3", "excerpt": "<script>alert('x')</script>", "reason": "Repeated passage needs review.", "review_action": "Compare against the manuscript.", "weight": "4.0"}]
    assert "Visible paragraph." in paths["extracted_text.txt"].read_text(encoding="utf-8")
    assert json.loads(paths["metadata.json"].read_text(encoding="utf-8"))["resources"][0]["path"] == "images/a.png"
def test_generated_korean_report_excludes_english_detector_prose(tmp_path):
    report = make_report()
    analyzer._localize_findings(report.findings, "ko")

    record = json.loads(generate_reports(report, tmp_path)["report.json"].read_text(encoding="utf-8"))
    finding = record["findings"][0]

    assert "반복 표현 검토 신호" in finding["reason"]
    assert "Repeated passage needs review." not in finding["reason"]
    assert "Compare against the manuscript." not in finding["review_action"]



def test_html_report_is_escaped_standalone_and_has_local_review_ui(tmp_path):
    path = generate_reports(make_report(), tmp_path)["report.html"]
    document = path.read_text(encoding="utf-8")

    assert "<script>alert('x')</script>" not in document
    assert "<\\/script>" in document
    assert "&lt;Unsafe &amp; title&gt;" in document
    assert "https://" not in document and "http://" not in document and "cdn" not in document.casefold()
    for ui_hook in ("category-filter", "severity-filter", "text-filter", "download-json", "report-data"):
        assert ui_hook in document
    prohibited = ("ai-generated", "ai authored", "probability", "ai가 작성")
    assert not any(phrase in document.casefold() for phrase in prohibited)
    payload = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', document, re.DOTALL)
    assert payload is not None
    rendered = json.loads(payload.group(1))
    assert rendered["book"]["chapter_count"] == 1
    assert rendered["book"]["resource_count"] == 1
    assert "book.chapter_count ?? 0" in document
    assert "book.resource_count ?? 0" in document


def test_report_assets_are_available_through_package_resources():
    package = importlib.resources.files("ebook_risk_analyzer")

    template = package.joinpath("templates", "report.html")
    stylesheet = package.joinpath("static", "report.css")
    script = package.joinpath("static", "report.js")

    assert template.is_file()
    assert stylesheet.is_file()
    assert script.is_file()
    assert "{{DATA}}" in template.read_text(encoding="utf-8")
    assert "book.chapter_count ?? 0" in script.read_text(encoding="utf-8")
    assert "book.resource_count ?? 0" in script.read_text(encoding="utf-8")

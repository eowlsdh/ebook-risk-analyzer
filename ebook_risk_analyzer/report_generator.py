"""Deterministic, offline report writers for ebook review signals."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .models import AnalysisReport, Book, Finding

_TEMPLATE_PATH = Path(__file__).with_name("templates") / "report.html"
_CSS_PATH = Path(__file__).with_name("static") / "report.css"
_JS_PATH = Path(__file__).with_name("static") / "report.js"


def _value(value: Any) -> Any:
    """Convert model values to deterministic JSON-compatible values."""
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    return value


def finding_record(finding: Finding) -> dict[str, Any]:
    """Return the stable public representation of one review signal."""
    return {
        "id": finding.id,
        "severity": finding.severity,
        "category": finding.category,
        "code": finding.code,
        "file": finding.file,
        "chapter": finding.chapter,
        "paragraph": finding.paragraph,
        "sentence": finding.sentence,
        "location": {
            "file": finding.file,
            "chapter": finding.chapter,
            "paragraph": finding.paragraph,
            "sentence": finding.sentence,
        },
        "excerpt": finding.excerpt,
        "reason": finding.reason,
        "review_action": finding.review_action,
        "weight": finding.weight,
    }


def report_record(report: AnalysisReport) -> dict[str, Any]:
    """Build the required report.json object with exactly its public top-level keys."""
    findings = [finding_record(finding) for finding in report.findings]
    metadata = report.book.metadata
    summary = _value(report.summary)
    summary.setdefault("risk_score", summary.get("overall_score", 0))
    summary.setdefault("chapter_count", len(report.book.chapters))
    summary.setdefault(
        "word_count",
        sum(len(paragraph.text.split()) for chapter in report.book.chapters for paragraph in chapter.paragraphs),
    )
    summary.setdefault("finding_count", len(findings))
    return {
        "book": {
            "title": metadata.get("title", ""),
            "author": metadata.get("author") or metadata.get("creator", ""),
            "publisher": metadata.get("publisher", ""),
            "language": metadata.get("language", ""),
            "source_file": str(report.book.source_path),
            "sha256": report.book.sha256,
            "metadata": dict(sorted(metadata.items())),
            "chapter_count": len(report.book.chapters),
            "resource_count": len(report.book.resources),
        },
        "summary": summary,
        "category_scores": dict(sorted(report.category_scores.items())),
        "findings": findings,
    }


def _metadata_record(book: Book) -> dict[str, Any]:
    """Return parse metadata without embedding chapter text in metadata.json."""
    return {
        "metadata": dict(sorted(book.metadata.items())),
        "source_path": str(book.source_path),
        "sha256": book.sha256,
        "chapters": [
            {"title": chapter.title, "file": chapter.file, "toc_title": chapter.toc_title,
             "headings": chapter.headings, "paragraph_count": len(chapter.paragraphs)}
            for chapter in book.chapters
        ],
        "resources": [_value(resource) for resource in book.resources],
    }


def _extracted_text(book: Book) -> str:
    """Render reading-order text with source headings for auditing."""
    chunks: list[str] = []
    for number, chapter in enumerate(book.chapters, 1):
        title = chapter.title or chapter.toc_title or chapter.file
        chunks.append(f"# {number}. {title} ({chapter.file})")
        chunks.extend(paragraph.text for paragraph in chapter.paragraphs if paragraph.text)
        chunks.append("")
    return "\n\n".join(chunks).rstrip() + "\n"


def _csv_rows(findings: list[Finding]) -> list[dict[str, Any]]:
    """Create flat CSV rows in detector order."""
    return [{
        "id": finding.id, "severity": finding.severity, "category": finding.category,
        "code": finding.code, "file": finding.file, "chapter": finding.chapter,
        "paragraph": finding.paragraph, "sentence": finding.sentence,
        "excerpt": finding.excerpt, "reason": finding.reason,
        "review_action": finding.review_action, "weight": finding.weight,
    } for finding in findings]


def _html_data(record: dict[str, Any]) -> dict[str, Any]:
    """Add presentation summaries to an already-public report record."""
    data = dict(record)
    findings = data.get("findings", [])
    data["severity_counts"] = dict(sorted(Counter(finding.get("severity", "") for finding in findings).items()))
    data["category_counts"] = dict(sorted(Counter(finding.get("category", "") for finding in findings).items()))
    data["chapter_counts"] = dict(sorted(
        Counter(finding.get("chapter") or finding.get("location", {}).get("chapter")
                or finding.get("file") or finding.get("location", {}).get("file", "")
                for finding in findings).items()
    ))
    return data


def render_report_html(record: dict[str, Any]) -> str:
    """Render a standalone report from an already-sanitized public record."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    css = _CSS_PATH.read_text(encoding="utf-8")
    script = _JS_PATH.read_text(encoding="utf-8")
    payload = json.dumps(_html_data(record), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).replace("</", "<\\/")
    title = html.escape(str(record.get("book", {}).get("title") or "ebook-risk-report"))
    return (template.replace("{{TITLE}}", title).replace("{{CSS}}", css)
            .replace("{{DATA}}", payload).replace("{{JS}}", script))


def generate_reports(report: AnalysisReport, output_dir: str | Path, format: str = "all") -> dict[str, Path]:
    """Write all required offline audit artifacts and return their paths.

    ``format`` is accepted for CLI compatibility; the canonical audit bundle always
    includes its five required files so it can be reviewed without rerunning analysis.
    """
    if format not in {"json", "html", "all"}:
        raise ValueError("format must be 'json', 'html', or 'all'")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    record = report_record(report)
    paths = {
        "report.json": destination / "report.json",
        "report.html": destination / "report.html",
        "findings.csv": destination / "findings.csv",
        "extracted_text.txt": destination / "extracted_text.txt",
        "metadata.json": destination / "metadata.json",
    }
    paths["report.json"].write_text(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                                indent=2) + "\n", encoding="utf-8")
    paths["metadata.json"].write_text(json.dumps(_metadata_record(report.book), ensure_ascii=False,
                                                  sort_keys=True, indent=2) + "\n", encoding="utf-8")
    paths["extracted_text.txt"].write_text(_extracted_text(report.book), encoding="utf-8")
    fieldnames = ["id", "severity", "category", "code", "file", "chapter", "paragraph",
                  "sentence", "excerpt", "reason", "review_action", "weight"]
    with paths["findings.csv"].open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_csv_rows(report.findings))
    paths["report.html"].write_text(render_report_html(record), encoding="utf-8")
    return paths


def write_reports(report: AnalysisReport, output_dir: str | Path, format: str = "all") -> dict[str, Path]:
    """Compatibility alias for :func:`generate_reports`."""
    return generate_reports(report, output_dir, format)

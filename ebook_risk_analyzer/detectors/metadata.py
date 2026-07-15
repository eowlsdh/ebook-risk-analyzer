"""Offline metadata review signals / señales de revisión de metadatos."""

from __future__ import annotations

from collections.abc import Mapping

from ebook_risk_analyzer.models import Book, Finding

_REQUIRED = ("title", "creator", "language", "identifier")
_GENERATOR_KEYS = ("generator", "created_by", "application", "software")


def _location(book: Book) -> tuple[str, str]:
    if book.chapters:
        return book.chapters[0].file, book.chapters[0].title
    return str(book.source_path), ""


def _finding(book: Book, code: str, reason: str, excerpt: str, severity: str = "medium") -> Finding:
    file, chapter = _location(book)
    return Finding(severity=severity, category="metadata", file=file, chapter=chapter, paragraph=0, sentence=0,
        excerpt=excerpt, reason=reason, review_action="Review the EPUB package metadata and align it with the publication’s displayed information.",
        code=code, weight=0.5)


def _normal(value: str) -> str:
    return " ".join(value.casefold().split())

def _metadata_values(book: Book) -> dict[str, list[str]]:
    """Normalize metadata aliases while retaining distinct supplied values."""
    aliases = {
        "author": "creator",
        "creator": "creator",
        "dc.creator": "creator",
        "dc:creator": "creator",
        "title": "title",
        "dc.title": "title",
        "dc:title": "title",
    }
    values: dict[str, list[str]] = {}
    for key, value in book.metadata.items():
        normalized = str(value).strip()
        if not normalized:
            continue
        name = aliases.get(str(key).casefold(), str(key).casefold())
        values.setdefault(name, []).append(normalized)
    return values



def detect_metadata(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Identify metadata review candidates without making authorship or factual claims.

    Identifica candidatos para revisar metadatos sin afirmar errores factuales ni autoría por IA.
    """
    del config
    metadata = _metadata_values(book)
    findings: list[Finding] = []
    for key in _REQUIRED:
        if not metadata.get(key):
            findings.append(_finding(book, f"missing_{key}", f"Required-looking metadata field “{key}” is absent or empty; review EPUB package completeness.",
                f"Metadata field “{key}”: absent or empty."))
    for key in _GENERATOR_KEYS:
        value = next(iter(metadata.get(key, [])), "")
        if value:
            findings.append(_finding(book, "generator_metadata", f"Generator metadata ({key}: {value[:120]}) is present; review whether it is intended for publication.",
                f"Metadata field “{key}”: {value[:120]}", "low"))

    title_values = metadata.get("title", [])
    title = title_values[0] if title_values else ""
    if title:
        toc_titles = {chapter.toc_title for chapter in book.chapters if chapter.toc_title}
        chapter_titles = {chapter.title for chapter in book.chapters if chapter.title}
        displayed = toc_titles or chapter_titles
        # A title mismatch is only meaningful when a title-like document label exists.
        for candidate in displayed:
            if _normal(candidate) != _normal(title) and _normal(title) in _normal(candidate):
                findings.append(_finding(book, "title_display_variant",
                    f"Package title “{title}” differs from displayed title “{candidate}”; review whether the difference is intentional.",
                    f"Metadata field “title”: {title[:120]}", "low"))
                break
    if len({_normal(value) for value in title_values}) > 1:
        findings.append(_finding(book, "title_metadata_variant",
            "Title metadata uses multiple title forms; review whether they intentionally describe the same publication.",
            f"Metadata field “title”: {title_values[0][:120]}"))
    creators = metadata.get("creator", [])
    if len({_normal(value) for value in creators}) > 1:
        findings.append(_finding(book, "author_metadata_variant",
            "Creator metadata uses multiple author-name forms; review whether they intentionally identify the same contributor.",
            f"Metadata field “creator”: {creators[0][:120]}"))
    return findings


def detect(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Compatibility entry point for metadata signals."""
    return detect_metadata(book, config)

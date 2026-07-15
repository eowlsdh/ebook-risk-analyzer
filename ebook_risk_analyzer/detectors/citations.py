"""Offline citation review signals / señales de revisión de citas."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ebook_risk_analyzer.models import Book, Finding, Sentence

_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
_DOI_REFERENCE = re.compile(r"\b(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)([^\s<>\])}]+)", re.I)
_URL = re.compile(r"https?://[^\s<>\])}]*", re.I)
_CITATION = re.compile(r"(?:\[[0-9,;\s]+\]|\([A-Z][A-Za-z-]+,?\s+(?:19|20)\d{2}[a-z]?\))")
_SOURCE_NEEDED = re.compile(r"\b(?:citation needed|citation required|source needed|source required|fuente necesaria|se necesita (?:una )?fuente|requiere (?:una )?fuente)\b", re.I)
_STATISTIC = re.compile(r"\b(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*%|\b(?:one|\d+)\s+in\s+\d+\b|\b\d+\s+(?:million|billion|mil(?:lones)?|millones)\b", re.I)
_PLACEHOLDER_URL = re.compile(r"\b(?:todo|tbd|placeholder|insert|xxx)\b", re.I)
_PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "invalid", "localhost"}


def _trim_terminal_punctuation(value: str) -> str:
    return value.rstrip(".,;:!?")


def _url_details(text: str) -> tuple[bool, bool, bool]:
    """Return whether URLs are present, syntactically empty, or obvious placeholders."""
    present = empty = placeholder = False
    for match in _URL.finditer(text):
        value = _trim_terminal_punctuation(match.group())
        tail = value.split("://", 1)[1]
        if not tail or tail.startswith(("/", "?", "#")):
            empty = True
            continue
        present = True
        host = tail.split("/", 1)[0].split("@")[-1].split(":", 1)[0].casefold()
        if host in _PLACEHOLDER_HOSTS or _PLACEHOLDER_URL.search(value):
            placeholder = True
    return present, empty, placeholder


def _doi_details(text: str) -> tuple[bool, bool]:
    """Return whether DOI text is valid or explicitly marked but malformed."""
    valid = bool(_DOI.search(text))
    malformed = False
    for match in _DOI_REFERENCE.finditer(text):
        candidate = _trim_terminal_punctuation(match.group(1))
        if _DOI.fullmatch(candidate):
            valid = True
        else:
            malformed = True
    return valid, malformed


def _finding(sentence: Sentence, code: str, reason: str, severity: str = "medium") -> Finding:
    location = sentence.location
    return Finding(severity=severity, category="citations", file=location.file, chapter=location.chapter,
        paragraph=location.paragraph, sentence=location.sentence, excerpt=sentence.text[:300], reason=reason,
        review_action="Review the surrounding claim and add, correct, or document an appropriate source where needed.",
        code=code, weight=0.5)


def detect_citations(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Identify citation-related review candidates without accessing the network.

    Identifica candidatos de revisión de citas sin verificar enlaces ni afirmar que una fuente sea inválida.
    """
    del config
    findings: list[Finding] = []
    for chapter in book.chapters:
        for paragraph in chapter.paragraphs:
            for sentence in paragraph.sentences:
                text = sentence.text
                if _SOURCE_NEEDED.search(text):
                    findings.append(_finding(sentence, "source_needed_marker",
                        "The text includes a source-needed marker; review whether a citation should be supplied."))
                has_doi, malformed_doi = _doi_details(text)
                has_url, empty_url, placeholder_url = _url_details(text)
                has_citation = bool(_CITATION.search(text))
                if malformed_doi:
                    findings.append(_finding(sentence, "malformed_doi",
                        "A DOI is explicitly marked but does not match the expected DOI format; review the reference text."))
                if has_doi:
                    findings.append(_finding(sentence, "doi_present",
                        "A DOI appears in running text; review its formatting and whether its reference details are complete.", "low"))
                if empty_url:
                    findings.append(_finding(sentence, "empty_url",
                        "A URL scheme has no host value; review whether a complete source link should be supplied."))
                if placeholder_url:
                    findings.append(_finding(sentence, "placeholder_url",
                        "A URL contains placeholder text or a documentation-only host; review the intended source link."))
                if has_url:
                    findings.append(_finding(sentence, "url_present",
                        "A URL appears in running text; review its presentation and supporting reference context.", "low"))
                if has_citation:
                    findings.append(_finding(sentence, "citation_present",
                        "An inline citation-like pattern appears; review its consistency with the book’s citation style.", "low"))
                if _STATISTIC.search(text) and not (has_doi or has_url or has_citation):
                    findings.append(_finding(sentence, "uncited_statistic_candidate",
                        "A quantitative claim has no nearby inline citation pattern; review whether context or a source should accompany it."))
    return findings


def detect(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Compatibility entry point for citation signals."""
    return detect_citations(book, config)

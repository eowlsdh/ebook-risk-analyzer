"""Typed data model for human-review risk signals in ebooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SentenceLocation:
    """Location of a sentence in an input publication."""

    file: str
    chapter: str
    paragraph: int
    sentence: int


@dataclass
class Sentence:
    """Extracted sentence and its source location."""

    text: str
    location: SentenceLocation


@dataclass
class Paragraph:
    """Extracted paragraph with its zero-based index and sentences."""

    text: str
    index: int
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class Chapter:
    """A reading-order document from a publication."""

    title: str
    file: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    toc_title: str = ""


@dataclass
class Resource:
    """A packaged resource available for human-review checks."""

    path: str
    media_type: str
    size: int = 0
    sha256: str = ""
    referenced: bool = False
    alt_text: str | None = None


@dataclass
class Book:
    """Parsed publication input and the content available for analysis."""

    metadata: dict[str, str]
    chapters: list[Chapter]
    resources: list[Resource]
    source_path: Path
    sha256: str


@dataclass
class Finding:
    """A human-review signal emitted by a detector."""

    severity: str
    category: str
    file: str
    chapter: str
    paragraph: int
    sentence: int
    excerpt: str
    reason: str
    review_action: str
    code: str = ""
    weight: float = 0.0
    id: str = ""


@dataclass
class AnalysisReport:
    """Aggregate detector output for a parsed book."""

    book: Book
    summary: dict[str, object]
    category_scores: dict[str, float]
    findings: list[Finding] = field(default_factory=list)

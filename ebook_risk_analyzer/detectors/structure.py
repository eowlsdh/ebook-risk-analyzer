"""Structural and editorial-remnant detectors for EPUB chapter organization."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from ..models import Book, Finding

_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_NUMBER = re.compile(r"^(?:chapter|chapitre|capítulo|第)\s*([\divxlcdm]+)", re.I)
_REMNANT = re.compile(r"\b(?:todo|tbd|xxx|lorem ipsum|insert (?:text|image)|draft(?:ing)? note)\b|(?:待补充|占位符|草稿)", re.I)
_CONNECTORS = {"however", "therefore", "moreover", "furthermore", "additionally", "meanwhile", "nevertheless", "然而", "因此", "此外", "同时", "不过"}


def _cfg(config: Mapping[str, Any], name: str, default: Any) -> Any:
    section = config.get("structure", {})
    return section.get(name, config.get(name, default)) if isinstance(section, Mapping) else config.get(name, default)


def _loc(item: Any, chapter: Any) -> tuple[str, str, int, int]:
    loc = getattr(item, "location", None)
    return (getattr(loc, "file", getattr(chapter, "file", "")), getattr(loc, "chapter", getattr(chapter, "title", "")), getattr(loc, "paragraph", getattr(item, "index", 0)), getattr(loc, "sentence", 0))


def _finding(item: Any, chapter: Any, code: str, reason: str, weight: float = 1.0) -> Finding:
    file, title, paragraph, sentence = _loc(item, chapter)
    return Finding("medium", "structure", file, title, paragraph, sentence, getattr(item, "text", getattr(chapter, "title", ""))[:300], reason,
                   "Check the book structure and revise the source or navigation metadata as needed.", code, weight)


def _first_last(chapter: Any) -> tuple[Any | None, Any | None]:
    sentences = [s for p in getattr(chapter, "paragraphs", []) for s in getattr(p, "sentences", []) if getattr(s, "text", "").strip()]
    return (sentences[0], sentences[-1]) if sentences else (None, None)


def detect_structure(book: Book, config: Mapping[str, Any] | None = None) -> list[Finding]:
    """Detect repeated chapter patterns, editorial remnants, numbering, and TOC concerns."""
    config = config or {}
    if not _cfg(config, "enabled", True):
        return []
    chapters = list(getattr(book, "chapters", []))
    findings: list[Finding] = []
    starts: Counter[str] = Counter()
    ends: Counter[str] = Counter()
    heading_shapes: Counter[tuple[str, ...]] = Counter()
    chapter_data: list[tuple[Any, Any | None, Any | None]] = []
    for chapter in chapters:
        first, last = _first_last(chapter)
        chapter_data.append((chapter, first, last))
        if first:
            starts[" ".join(_WORD.findall(getattr(first, "text", "").casefold())[:8])] += 1
        if last:
            ends[" ".join(_WORD.findall(getattr(last, "text", "").casefold())[-8:])] += 1
        headings = tuple(re.sub(r"\d+", "#", str(h)).casefold() for h in getattr(chapter, "headings", []))
        if headings:
            heading_shapes[headings] += 1
        for paragraph in getattr(chapter, "paragraphs", []):
            text = getattr(paragraph, "text", "")
            if _REMNANT.search(text):
                item = next(iter(getattr(paragraph, "sentences", [])), paragraph)
                findings.append(_finding(item, chapter, "editorial_remnant", "Possible editorial placeholder or drafting note."))
    for chapter, first, last in chapter_data:
        if first and starts[" ".join(_WORD.findall(getattr(first, "text", "").casefold())[:8])] > 1:
            findings.append(_finding(first, chapter, "repeated_chapter_start", "Opening phrase is repeated across chapters."))
        if last and ends[" ".join(_WORD.findall(getattr(last, "text", "").casefold())[-8:])] > 1:
            findings.append(_finding(last, chapter, "repeated_chapter_end", "Closing phrase is repeated across chapters."))
        shape = tuple(re.sub(r"\d+", "#", str(h)).casefold() for h in getattr(chapter, "headings", []))
        if shape and heading_shapes[shape] > 1:
            findings.append(_finding(first or chapter, chapter, "repeated_heading_structure", "Heading structure is repeated across chapters."))
    expected = 1
    toc_titles = set()
    for chapter in chapters:
        title = str(getattr(chapter, "title", ""))
        match = _NUMBER.match(title)
        if match and match.group(1).isdigit() and int(match.group(1)) != expected:
            findings.append(_finding(chapter, chapter, "chapter_number_gap", f"Chapter numbering expected {expected}, found {match.group(1)}."))
        if match:
            expected += 1
        toc = str(getattr(chapter, "toc_title", ""))
        if toc:
            key = toc.casefold().strip()
            if key in toc_titles or key != title.casefold().strip():
                findings.append(_finding(chapter, chapter, "toc_title_issue", "TOC title is duplicate or differs from the chapter title."))
            toc_titles.add(key)
    all_words: list[str] = []
    connector_count = 0
    for chapter, first, _ in chapter_data:
        text = " ".join(getattr(p, "text", "") for p in getattr(chapter, "paragraphs", []))
        words = _WORD.findall(text.casefold())
        all_words.extend(words)
        connector_count += sum(word in _CONNECTORS for word in words)
    if all_words:
        diversity = len(set(all_words)) / len(all_words)
        if diversity < float(_cfg(config, "vocabulary_diversity_min", 0.35)):
            findings.append(_finding(chapters[0], chapters[0], "low_vocabulary_diversity", f"Book vocabulary diversity is {diversity:.0%}.", 1 - diversity))
        ratio = connector_count / len(all_words)
        if ratio >= float(_cfg(config, "connector_ratio_threshold", 0.03)):
            findings.append(_finding(chapters[0], chapters[0], "connector_density", f"Connector words account for {ratio:.1%} of words.", ratio))
    return findings

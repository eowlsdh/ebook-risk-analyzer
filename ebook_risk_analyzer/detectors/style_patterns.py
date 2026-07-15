"""Style-distribution signals that support human editorial review."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..models import Book, Finding

_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.I)
_NOMINAL = re.compile(r"\b\w+(?:tion|sion|ment|ness|ity|ance|ence)\b", re.I)
_LIST = re.compile(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+", re.M)


def _cfg(config: Mapping[str, Any], name: str, default: Any) -> Any:
    section = config.get("style_patterns", {})
    return section.get(name, config.get(name, default)) if isinstance(section, Mapping) else config.get(name, default)


def _finding(sentence: Any, chapter: Any, code: str, reason: str, weight: float) -> Finding:
    loc = getattr(sentence, "location", None)
    return Finding("low", "style_patterns", getattr(loc, "file", getattr(chapter, "file", "")),
                   getattr(loc, "chapter", getattr(chapter, "title", "")), getattr(loc, "paragraph", 0),
                   getattr(loc, "sentence", 0), getattr(sentence, "text", "")[:300], reason,
                   "Review this pattern in context and revise only where it affects readability or voice.", code, weight)


def detect_style_patterns(book: Book, config: Mapping[str, Any] | None = None) -> list[Finding]:
    """Return signals for outlier sentence length, punctuation, passive, nominal, and list use."""
    config = config or {}
    if not _cfg(config, "enabled", True):
        return []
    max_words = int(_cfg(config, "max_sentence_words", 40))
    max_punctuation = float(_cfg(config, "max_punctuation_ratio", 0.18))
    passive_threshold = float(_cfg(config, "passive_ratio_threshold", 0.35))
    nominal_threshold = float(_cfg(config, "nominal_ratio_threshold", 0.20))
    findings: list[Finding] = []
    for chapter in getattr(book, "chapters", []):
        chapter_sentences = [s for p in getattr(chapter, "paragraphs", []) for s in getattr(p, "sentences", [])]
        passive_count = nominal_count = 0
        for sentence in chapter_sentences:
            text = getattr(sentence, "text", "")
            words = _WORD.findall(text)
            if not words:
                continue
            punctuation = sum(not char.isalnum() and not char.isspace() for char in text)
            if len(words) > max_words:
                findings.append(_finding(sentence, chapter, "long_sentence", f"Sentence has {len(words)} words, above configured review threshold {max_words}.", len(words) / max_words))
            if punctuation / max(len(text), 1) > max_punctuation:
                findings.append(_finding(sentence, chapter, "punctuation_density", "Punctuation density is above the configured review threshold.", 1.0))
            passive_count += bool(_PASSIVE.search(text))
            nominal_count += sum(bool(_NOMINAL.fullmatch(word)) for word in words)
        count = len(chapter_sentences)
        if count and passive_count / count >= passive_threshold:
            findings.append(_finding(chapter_sentences[0], chapter, "passive_distribution", f"{passive_count}/{count} sentences match a passive-voice heuristic.", passive_count / count))
        word_count = sum(len(_WORD.findall(getattr(s, "text", ""))) for s in chapter_sentences)
        if word_count and nominal_count / word_count >= nominal_threshold:
            findings.append(_finding(chapter_sentences[0], chapter, "nominalization_distribution", f"{nominal_count}/{word_count} words match nominalization endings.", nominal_count / word_count))
        for paragraph in getattr(chapter, "paragraphs", []):
            if len(_LIST.findall(getattr(paragraph, "text", ""))) >= int(_cfg(config, "list_item_threshold", 3)):
                sentence = next(iter(getattr(paragraph, "sentences", [])), paragraph)
                findings.append(_finding(sentence, chapter, "list_density", "Paragraph contains several list markers.", 1.0))
    return findings

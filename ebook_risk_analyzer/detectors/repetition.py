"""Identify repeated wording as deterministic editorial review signals."""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ..models import Book, Finding

_WORD = re.compile(r"[\w'-]+", re.UNICODE)
DEFAULT_MAX_SENTENCE_PAIRS = 10_000
DEFAULT_MAX_NGRAM_OCCURRENCES = 100_000


def _cfg(config: Mapping[str, Any], name: str, default: Any) -> Any:
    section = config.get("repetition", {})
    return section.get(name, config.get(name, default)) if isinstance(section, Mapping) else config.get(name, default)


def _nonnegative_int(value: Any, name: str) -> int:
    value = int(value)
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value


def _normalise(text: str) -> str:
    return " ".join(_WORD.findall(text.casefold()))


def _make(item: Any, chapter: Any, code: str, reason: str, weight: float = 1.0) -> Finding:
    loc = getattr(item, "location", None)
    return Finding("medium", "repetition", getattr(loc, "file", getattr(chapter, "file", "")),
                   getattr(loc, "chapter", getattr(chapter, "title", "")), getattr(loc, "paragraph", getattr(item, "index", 0)),
                   getattr(loc, "sentence", 0), getattr(item, "text", "")[:300], reason,
                   "Compare the occurrences and retain, vary, or remove intentional repetition.", code, weight)


def _similarity(left: set[str], right: set[str]) -> float:
    return (2 * len(left & right) / (len(left) + len(right))) if left or right else 0.0


def detect_repetition(book: Book, config: Mapping[str, Any] | None = None) -> list[Finding]:
    """Detect exact/similar repeated sentences and paragraphs plus repeated n-grams."""
    config = config or {}
    if not _cfg(config, "enabled", True):
        return []
    minimum = int(_cfg(config, "minimum_tokens", 5))
    similarity = float(_cfg(config, "similarity_threshold", 0.85))
    ngram_min, ngram_max = _cfg(config, "ngram_range", (3, 8))
    max_sentence_pairs = _nonnegative_int(
        _cfg(config, "max_sentence_pairs", DEFAULT_MAX_SENTENCE_PAIRS),
        "max_sentence_pairs",
    )
    max_ngram_occurrences = _nonnegative_int(
        _cfg(config, "max_ngram_occurrences", DEFAULT_MAX_NGRAM_OCCURRENCES),
        "max_ngram_occurrences",
    )
    sentences: list[tuple[Any, Any, str]] = []
    paragraphs: list[tuple[Any, Any, str]] = []
    for chapter in getattr(book, "chapters", []):
        for paragraph in getattr(chapter, "paragraphs", []):
            normalized = _normalise(getattr(paragraph, "text", ""))
            if len(normalized.split()) >= minimum:
                paragraphs.append((paragraph, chapter, normalized))
            for sentence in getattr(paragraph, "sentences", []):
                normalized = _normalise(getattr(sentence, "text", ""))
                if len(normalized.split()) >= minimum:
                    sentences.append((sentence, chapter, normalized))
    findings: list[Finding] = []
    comparison_cap_reached = False
    for label, entries in (("sentence", sentences), ("paragraph", paragraphs)):
        seen: dict[str, tuple[Any, Any]] = {}
        for item, chapter, normalized in entries:
            if normalized in seen:
                findings.append(_make(item, chapter, f"exact_{label}", f"Exact repeated {label}; first occurrence is elsewhere in the book."))
            else:
                seen[normalized] = (item, chapter)
        # Compare only unique normalized forms to avoid duplicate combinations.
        uniques = list(seen.items())
        comparisons = 0
        for index, (left_text, (left_item, left_chapter)) in enumerate(uniques):
            if comparisons >= max_sentence_pairs:
                if index + 1 < len(uniques):
                    comparison_cap_reached = True
                break
            left_words = set(left_text.split())
            for right_text, (right_item, right_chapter) in uniques[index + 1:]:
                if comparisons >= max_sentence_pairs:
                    comparison_cap_reached = True
                    break
                comparisons += 1
                if abs(len(left_text.split()) - len(right_text.split())) > max(2, len(left_text.split()) // 3):
                    continue
                score = _similarity(left_words, set(right_text.split()))
                if score >= similarity:
                    findings.append(_make(right_item, right_chapter, f"similar_{label}", f"Similar {label} wording ({score:.0%} shared vocabulary).", score))
    ngrams: defaultdict[tuple[str, ...], list[tuple[Any, Any]]] = defaultdict(list)
    ngram_occurrences = 0
    ngram_cap_reached = False
    for item, chapter, normalized in sentences:
        words = normalized.split()
        for width in range(int(ngram_min), int(ngram_max) + 1):
            for start in range(len(words) - width + 1):
                if ngram_occurrences >= max_ngram_occurrences:
                    ngram_cap_reached = True
                    break
                ngrams[tuple(words[start:start + width])].append((item, chapter))
                ngram_occurrences += 1
            if ngram_cap_reached:
                break
        if ngram_cap_reached:
            break
    reported_pairs: set[tuple[int, int]] = set()
    for tokens, occurrences in sorted(ngrams.items(), key=lambda pair: len(pair[0]), reverse=True):
        distinct = {(id(item), id(chapter)) for item, chapter in occurrences}
        if len(distinct) > 1:
            item, chapter = occurrences[-1]
            pair_key = tuple(sorted(id(entry[0]) for entry in occurrences[:2]))
            if pair_key not in reported_pairs:
                reported_pairs.add(pair_key)
                findings.append(_make(item, chapter, f"ngram_{len(tokens)}", f"Repeated {len(tokens)}-token phrase: {' '.join(tokens)!r}."))
    if comparison_cap_reached:
        item, chapter, _ = (sentences or paragraphs)[0]
        findings.append(_make(
            item, chapter, "similarity_comparison_cap_reached",
            f"Similarity comparison limit ({max_sentence_pairs}) was reached; similar-wording review may be incomplete.",
        ))
    if ngram_cap_reached:
        item, chapter, _ = sentences[0]
        findings.append(_make(
            item, chapter, "ngram_occurrence_cap_reached",
            f"N-gram occurrence limit ({max_ngram_occurrences}) was reached; repeated-phrase review may be incomplete.",
        ))
    return findings

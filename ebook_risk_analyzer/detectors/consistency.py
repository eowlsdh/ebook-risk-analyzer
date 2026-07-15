"""Offline consistency review signals / señales de revisión de consistencia."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

from ebook_risk_analyzer.models import Book, Finding, Sentence

_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s*(?:%|percent|por ciento))?", re.I)
_AGE = re.compile(r"\b(\d{1,3})\s*(?:years? old|años?)\b", re.I)
_DATE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{1,2},?\s+\d{4})\b", re.I)
_NAME = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2}\b")


def _finding(sentence: Sentence, category: str, code: str, reason: str) -> Finding:
    location = sentence.location
    return Finding(
        severity="medium", category=category, file=location.file, chapter=location.chapter,
        paragraph=location.paragraph, sentence=location.sentence, excerpt=sentence.text[:300],
        reason=reason, review_action="Compare the referenced passages and confirm the intended value or wording.",
        code=code, weight=0.5,
    )


def detect_consistency(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Return candidate inconsistencies, not assertions that any statement is wrong.

    Detecta candidatos de incoherencia numérica, de fecha, edad, porcentaje y nombre.
    """
    del config

    findings: list[Finding] = []
    # Nearby distinct values around an age/date/percentage cue are review candidates.
    for chapter in book.chapters:
        for paragraph in chapter.paragraphs:
            text = paragraph.text
            for label, pattern in (("age", _AGE), ("date", _DATE)):
                values = {m.group(0).casefold() for m in pattern.finditer(text)}
                if len(values) > 1 and paragraph.sentences:
                    findings.append(_finding(paragraph.sentences[0], "consistency", f"multiple_{label}s",
                        f"This paragraph contains multiple {label} expressions ({', '.join(sorted(values))}); this is a review signal, not a factual-error claim."))
            percentages = {m.group(0) for m in _NUMBER.finditer(text) if "%" in m.group(0) or "percent" in m.group(0).casefold() or "por ciento" in m.group(0).casefold()}
            if len(percentages) > 1 and paragraph.sentences:
                findings.append(_finding(paragraph.sentences[0], "consistency", "multiple_percentages",
                    "Multiple percentage expressions occur in one paragraph; review their denominator and context."))
            numbers = {m.group(0) for m in _NUMBER.finditer(text)}
            if len(numbers) > 1 and paragraph.sentences:
                findings.append(_finding(paragraph.sentences[0], "consistency", "multiple_numbers",
                    "Multiple numeric expressions occur in one paragraph; review whether their units and references are clear."))

    surnames: dict[str, set[str]] = defaultdict(set)
    name_sentences: dict[str, Sentence] = {}
    for chapter in book.chapters:
        for paragraph in chapter.paragraphs:
            for sentence in paragraph.sentences:
                for match in _NAME.finditer(sentence.text):
                    name = match.group(0)
                    surname = name.rsplit(" ", 1)[-1].casefold()
                    surnames[surname].add(name)
                    name_sentences.setdefault(name, sentence)
    for surname, names in surnames.items():
        if len(names) > 1:
            name = sorted(names)[0]
            findings.append(_finding(name_sentences[name], "consistency", "name_variant",
                f"Names sharing the surname “{surname}” use multiple full-name forms ({', '.join(sorted(names))}); review whether they identify the same person."))
    return findings


def detect(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Compatibility entry point for the consistency detector."""
    return detect_consistency(book, config)

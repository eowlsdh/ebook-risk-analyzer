"""Detect leftover conversational and prompt-like text for editorial review."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..models import Book, Finding

_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("as an ai", r"\b(?:as|being) an ai(?: language model)?\b", "First-person system disclaimer"),
    ("cannot comply", r"\b(?:i (?:cannot|can't)|unable to) (?:comply|help|provide)\b", "Conversational refusal"),
    ("prompt instruction", r"\b(?:ignore|follow) (?:the )?(?:previous|above|these) instructions\b", "Instruction-like wording"),
    ("assistant label", r"(?:^|\n)\s*(?:assistant|user|system)\s*:", "Conversation role label"),
    ("chinese assistant", r"(?:作为(?:一个)?(?:人工智能|ai)|我无法(?:帮助|提供)|请(?:告诉|提供)我)", "Conversational assistant phrasing"),
    ("chinese prompt", r"(?:忽略(?:之前|以上).*指令|以下是.*(?:回答|回复)|作为语言模型)", "Instruction-like Chinese wording"),
    ("korean assistant", r"(?:(?:인공지능|ai)\s*(?:언어\s*)?모델로서|(?:요청|그\s*요청).{0,30}?(?:도울|수행할|제공할)\s*수\s*없(?:습니다|어요))", "Conversational assistant phrasing"),
    ("korean prompt", r"(?:이전|앞선|위(?:의)?|기존)\s*(?:지시(?:사항)?|명령|지침).{0,30}?(?:무시|따르지)", "Instruction-like Korean wording"),
    ("template marker", r"\{\{[^{}]{2,80}\}\}|\[[A-Z][A-Z_ ]{2,}\]", "Unresolved template marker"),
)


def _setting(config: Mapping[str, Any], name: str, default: Any) -> Any:
    section = config.get("chatbot_residue", {})
    return section.get(name, config.get(name, default)) if isinstance(section, Mapping) else config.get(name, default)


def _finding(sentence: Any, chapter: Any, category: str, code: str, reason: str) -> Finding:
    location = getattr(sentence, "location", None)
    return Finding(
        severity="medium",
        category=category,
        file=getattr(location, "file", getattr(chapter, "file", "")),
        chapter=getattr(location, "chapter", getattr(chapter, "title", "")),
        paragraph=getattr(location, "paragraph", 0),
        sentence=getattr(location, "sentence", 0),
        excerpt=getattr(sentence, "text", "")[:300],
        reason=reason + "; review whether it belongs in reader-facing prose.",
        review_action="Confirm this wording is intentional or revise/remove it.",
        code=code,
        weight=1.0,
    )


def detect_chatbot_residue(book: Book, config: Mapping[str, Any] | None = None) -> list[Finding]:
    """Return bilingual conversational-residue signals found in book sentences."""
    config = config or {}
    if not _setting(config, "enabled", True):
        return []
    patterns = _setting(config, "patterns", _PATTERNS)
    configured_phrases = _setting(config, "phrases", ())
    compiled: list[tuple[str, re.Pattern[str], str]] = []
    if isinstance(patterns, (list, tuple)):
        for entry in patterns:
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                code, pattern, reason = entry
                compiled.append((str(code), re.compile(str(pattern), re.IGNORECASE), str(reason)))
    if isinstance(configured_phrases, (list, tuple)):
        compiled.extend(
            ("configured_phrase", re.compile(re.escape(phrase), re.IGNORECASE), "Configured conversational phrase")
            for phrase in configured_phrases
            if isinstance(phrase, str) and phrase
        )
    findings: list[Finding] = []
    for chapter in getattr(book, "chapters", []):
        for paragraph in getattr(chapter, "paragraphs", []):
            for sentence in getattr(paragraph, "sentences", []):
                text = getattr(sentence, "text", "")
                for code, pattern, reason in compiled:
                    if pattern.search(text):
                        findings.append(_finding(sentence, chapter, "chatbot_residue", code, reason))
                        break
    return findings

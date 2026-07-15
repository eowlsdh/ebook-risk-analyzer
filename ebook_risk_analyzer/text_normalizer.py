"""Safe text normalization and Korean/English sentence segmentation."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_WHITESPACE = re.compile(r"\s+")
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024
# Terminal punctuation handles both English and Korean typography. Korean endings without
# punctuation are split only before a following capital/Hangul sentence start.
_PUNCTUATION_BOUNDARY = re.compile(r'(?<=[.!?。！？])(?:[\]\)\}"”’\']*)\s+')
_KOREAN_BOUNDARY = re.compile(
    r'(?<=[다요죠까니다십시오])[\]\)\}"”’\']*\s+(?=[A-Z가-힣])'
)


def read_text_safely(path: str | Path, max_bytes: int = DEFAULT_MAX_FILE_SIZE) -> str:
    """Read a UTF-8 text file without exceeding the configured byte limit."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("The maximum file size must be a positive number of bytes.")
    with Path(path).open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Input file exceeds the allowed size.")
    return data.decode("utf-8")

def normalize_text(text: str) -> str:
    """Return Unicode-normalized text with runs of whitespace collapsed.

    Control characters are converted to spaces rather than silently retained.  Newlines
    are intentionally treated as whitespace because source paragraph boundaries are
    preserved by the parser, not by this value.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    return _WHITESPACE.sub(" ", normalized).strip()


def split_sentences(text: str) -> list[str]:
    """Split normalized Korean and English prose into reviewable sentence strings.

    The rules are deliberately conservative: punctuation creates a boundary only when
    followed by whitespace, avoiding splits in decimal numbers and common abbreviations.
    Korean declarative endings may also split before a clear next sentence start.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []
    pieces = _PUNCTUATION_BOUNDARY.split(normalized)
    sentences: list[str] = []
    for piece in pieces:
        sentences.extend(_KOREAN_BOUNDARY.split(piece))
    return [sentence.strip() for sentence in sentences if sentence.strip()]

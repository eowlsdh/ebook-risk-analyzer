"""Deterministic review-signal detectors for EPUB and HTML books.

Each detector returns :class:`~ebook_risk_analyzer.models.Finding` objects.  The
signals identify passages for editorial review; they do not attribute text to an
authoring system.
"""

from .chatbot_residue import detect_chatbot_residue
from .repetition import detect_repetition
from .style_patterns import detect_style_patterns
from .structure import detect_structure

__all__ = [
    "detect_chatbot_residue",
    "detect_repetition",
    "detect_style_patterns",
    "detect_structure",
]

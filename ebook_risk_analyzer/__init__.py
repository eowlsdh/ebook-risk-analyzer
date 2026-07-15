"""Offline-first ebook human-review risk-signal analyzer."""

from .epub_parser import parse_epub
from .html_parser import parse_directory, parse_html, parse_text
from .models import AnalysisReport, Book, Chapter, Finding, Paragraph, Resource, Sentence, SentenceLocation

__all__ = [
    "AnalysisReport",
    "Book",
    "Chapter",
    "Finding",
    "Paragraph",
    "Resource",
    "Sentence",
    "SentenceLocation",
    "parse_directory",
    "parse_epub",
    "parse_html",
    "parse_text",
]

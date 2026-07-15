"""Offline parsing of HTML, XHTML, plain text, and directory inputs."""

from __future__ import annotations

import hashlib
import re
import mimetypes
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from .models import Book, Chapter, Paragraph, Resource, Sentence, SentenceLocation
from .text_normalizer import normalize_text, split_sentences

_TEXT_EXTENSIONS = {".html", ".htm", ".xhtml", ".xml", ".txt"}
_REMOVE_TAGS = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "head"}
_BLOCK_TAGS = {"p", "li", "blockquote", "pre", "td", "th", "figcaption"}
_HEADING_TAGS = {f"h{level}" for level in range(1, 7)}
_HIDDEN_STYLE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", re.I)


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
_RESOURCE_EXTENSIONS = _IMAGE_EXTENSIONS | {".css"}
_DEFAULT_MAX_RESOURCE_FILE_SIZE = 50 * 1024 * 1024
_DEFAULT_MAX_RESOURCE_BYTES = 500 * 1024 * 1024
_DEFAULT_MAX_RESOURCE_FILES = 10_000
_DEFAULT_MAX_SOURCE_FILES = 10_000
def decode_bytes(data: bytes) -> str:
    """Decode input bytes with conservative EPUB/web encoding fallbacks."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp949", "windows-1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _visible(tag: Tag) -> bool:
    """Return whether a tag is not explicitly hidden from readers."""
    if tag.has_attr("hidden") or str(tag.get("aria-hidden", "")).lower() == "true":
        return False
    return not _HIDDEN_STYLE.search(" ".join(tag.get("style", [])) if isinstance(tag.get("style"), list) else str(tag.get("style", "")))


def _clean_soup(markup: str) -> BeautifulSoup:
    """Build a soup after removing non-reader and hidden content."""
    soup = BeautifulSoup(markup, "lxml")
    for tag in list(soup.find_all(_REMOVE_TAGS)):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.attrs is not None and not _visible(tag):
            tag.decompose()
    return soup


def _chapter_from_markup(markup: str, file_name: str, title: str = "", toc_title: str = "") -> Chapter:
    """Convert one HTML/XHTML document into a location-preserving chapter."""
    soup = _clean_soup(markup)
    headings = [normalize_text(tag.get_text(" ", strip=True)) for tag in soup.find_all(_HEADING_TAGS)]
    headings = [heading for heading in headings if heading]
    chapter_title = title or (headings[0] if headings else file_name)
    blocks: Iterable[Tag] = soup.find_all(_BLOCK_TAGS)
    paragraphs: list[Paragraph] = []
    for tag in blocks:
        if tag.find_parent(_BLOCK_TAGS) is not None:
            continue
        text = normalize_text(tag.get_text(" ", strip=True))
        if not text:
            continue
        paragraph_index = len(paragraphs)
        sentences = [
            Sentence(sentence, SentenceLocation(file_name, chapter_title, paragraph_index, index))
            for index, sentence in enumerate(split_sentences(text))
        ]
        paragraphs.append(Paragraph(text, paragraph_index, sentences))
    if not paragraphs:
        body = soup.body or soup
        text = normalize_text(body.get_text(" ", strip=True))
        if text:
            sentences = [Sentence(value, SentenceLocation(file_name, chapter_title, 0, index)) for index, value in enumerate(split_sentences(text))]
            paragraphs.append(Paragraph(text, 0, sentences))
    return Chapter(chapter_title, file_name, paragraphs, headings, toc_title)


def _html_metadata(markup: str) -> dict[str, str]:
    """Extract stable, reader-supplied metadata from an HTML document."""
    soup = BeautifulSoup(markup, "lxml")
    metadata: dict[str, str] = {}
    title_tag = soup.title
    title = normalize_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    if title:
        metadata["title"] = title
    language = normalize_text(str((soup.html or {}).get("lang", "")))
    if language:
        metadata["language"] = language
    aliases = {"dc.creator": "creator", "dc:creator": "creator", "dc.title": "dc:title"}
    for tag in soup.find_all("meta"):
        name = str(tag.get("name") or tag.get("property") or "").strip().casefold()
        value = normalize_text(str(tag.get("content", "")))
        if name and value:
            key = aliases.get(name, name)
            if key not in metadata:
                metadata[key] = value
    return metadata

_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def _resource_candidate(reference: str, document: Path, root: Path) -> Path | None:
    """Resolve a local resource reference without permitting root escape."""
    value = reference.split("#", 1)[0].split("?", 1)[0].strip()
    if not value or value.startswith(("/", "//")) or "://" in value or value.startswith("data:"):
        return None
    candidate = (document.parent / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file() or candidate.suffix.casefold() not in _RESOURCE_EXTENSIONS:
        return None
    return candidate


def _srcset_references(value: str) -> Iterable[str]:
    """Yield URL candidates from a srcset value."""
    for candidate in value.split(","):
        reference = candidate.strip().split(maxsplit=1)[0]
        if reference:
            yield reference


def _css_url_references(value: str) -> Iterable[str]:
    """Yield URL candidates from CSS url() functions."""
    for match in _CSS_URL.finditer(value):
        reference = match.group(2).strip()
        if reference:
            yield reference


def _local_resources(markup: str, document: Path, root: Path, relative_paths: bool) -> dict[str, tuple[Path, str | None]]:
    """Return local resource references keyed by stable resource path."""
    soup = BeautifulSoup(markup, "lxml")
    resources: dict[str, tuple[Path, str | None]] = {}

    def add(reference: str, alt_text: str | None = None) -> None:
        candidate = _resource_candidate(reference, document, root)
        if candidate is None:
            return
        relative = candidate.relative_to(root.resolve())
        key = relative.as_posix() if relative_paths else str(candidate)
        previous = resources.get(key)
        if previous is None or (previous[1] is None and alt_text is not None):
            resources[key] = (candidate, alt_text)

    for tag in soup.find_all(["img", "source", "image", "object", "embed", "link"]):
        rel_values = tag.get("rel", [])
        rel = {str(value).casefold() for value in ([rel_values] if isinstance(rel_values, str) else rel_values)}
        if tag.name == "link":
            if "stylesheet" in rel and isinstance(tag.get("href"), str):
                add(tag["href"])
            continue
        attribute = "data" if tag.name == "object" else "src"
        alt_text = normalize_text(str(tag.get("alt", ""))) if tag.name == "img" and tag.has_attr("alt") else None
        if isinstance(tag.get(attribute), str):
            add(tag[attribute], alt_text)
        if tag.name in {"img", "source"} and isinstance(tag.get("srcset"), str):
            for reference in _srcset_references(tag["srcset"]):
                add(reference, alt_text)
        if tag.name == "image":
            for attribute in ("href", "xlink:href"):
                if isinstance(tag.get(attribute), str):
                    add(tag[attribute])

    for tag in soup.find_all("style"):
        for reference in _css_url_references(tag.get_text()):
            add(reference)
    for tag in soup.find_all(style=True):
        for reference in _css_url_references(str(tag["style"])):
            add(reference)
    return resources


def _resource(path: Path, name: str, referenced: bool, alt_text: str | None) -> Resource:
    """Create a resource record from a preflighted local file."""
    digest = hashlib.sha256()
    with path.open("rb") as resource_file:
        for chunk in iter(lambda: resource_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return Resource(name, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.stat().st_size,
        digest.hexdigest(), referenced, alt_text)

def _preflight_resources(resources: Iterable[tuple[Path, str | None]], max_file_size: int,
                         max_total_size: int) -> None:
    """Reject resource files that exceed deterministic per-file or aggregate limits."""
    total_size = 0
    for path, _ in resources:
        size = path.stat().st_size
        if size > max_file_size:
            raise ValueError(f"Referenced resource exceeds max-file-size ({max_file_size} bytes): {path}")
        total_size += size
        if total_size > max_total_size:
            raise ValueError(f"Referenced resources exceed {max_total_size} total bytes")


def parse_html(path: Path | str, max_file_size: int = _DEFAULT_MAX_RESOURCE_FILE_SIZE,
               max_total_size: int = _DEFAULT_MAX_RESOURCE_BYTES) -> Book:
    """Parse one HTML or XHTML file into a :class:`Book` for human review."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"HTML input is not a readable file: {source}")
    raw = source.read_bytes()
    markup = decode_bytes(raw)
    metadata = _html_metadata(markup)
    chapter = _chapter_from_markup(markup, source.name, metadata.get("title", ""))
    local_resources = _local_resources(markup, source, source.parent, False)
    _preflight_resources(local_resources.values(), max_file_size, max_total_size)
    resources = [_resource(resource_path, name, True, alt_text) for name, (resource_path, alt_text) in sorted(
        local_resources.items()
    )]
    return Book(metadata, [chapter], resources, source, hashlib.sha256(raw).hexdigest())


def parse_text(path: Path | str) -> Book:
    """Parse a UTF-8-compatible plain-text file into one location-preserving chapter."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Text input is not a readable file: {source}")
    raw = source.read_bytes()
    title = source.stem
    paragraphs: list[Paragraph] = []
    for value in re.split(r"(?:\r?\n){2,}", decode_bytes(raw)):
        text = normalize_text(value)
        if not text:
            continue
        index = len(paragraphs)
        sentences = [Sentence(sentence, SentenceLocation(source.name, title, index, sentence_index)) for sentence_index, sentence in enumerate(split_sentences(text))]
        paragraphs.append(Paragraph(text, index, sentences))
    return Book({"title": title}, [Chapter(title, source.name, paragraphs)], [], source, hashlib.sha256(raw).hexdigest())


def parse_directory(path: Path | str, max_file_size: int = _DEFAULT_MAX_RESOURCE_FILE_SIZE,
                    max_total_size: int = _DEFAULT_MAX_RESOURCE_BYTES,
                    max_resource_files: int = _DEFAULT_MAX_RESOURCE_FILES) -> Book:
    """Parse supported files in a directory in deterministic relative-path order."""
    source = Path(path)
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Directory input is not readable: {source}")

    candidates: list[Path] = []
    resource_paths: list[Path] = []
    resource_total_size = 0
    source_root = source.resolve()
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        is_text = item.suffix.casefold() in _TEXT_EXTENSIONS
        is_resource = item.suffix.casefold() in _RESOURCE_EXTENSIONS
        if item.is_symlink():
            if is_text:
                raise ValueError(f"Directory contains an unsafe linked source file: {item}")
            if is_resource:
                raise ValueError(f"Directory contains an unsafe linked resource file: {item}")
            continue
        if not item.resolve().is_relative_to(source_root):
            if is_text:
                raise ValueError(f"Directory contains an unsafe linked source file: {item}")
            if is_resource:
                raise ValueError(f"Directory contains an unsafe linked resource file: {item}")
            continue
        if is_text:
            if len(candidates) >= _DEFAULT_MAX_SOURCE_FILES:
                raise ValueError(f"Directory contains more than {_DEFAULT_MAX_SOURCE_FILES} source files")
            candidates.append(item)
        if is_resource:
            if len(resource_paths) >= max_resource_files:
                raise ValueError(f"Directory contains more than {max_resource_files} resource files")
            resource_paths.append(item)
            size = item.stat().st_size
            if size > max_file_size:
                raise ValueError(f"Referenced resource exceeds max-file-size ({max_file_size} bytes): {item}")
            resource_total_size += size
            if resource_total_size > max_total_size:
                raise ValueError(f"Referenced resources exceed {max_total_size} total bytes")

    files = sorted(candidates, key=lambda item: item.relative_to(source).as_posix())
    if not files:
        raise ValueError(f"Directory contains no HTML, XHTML, or text files: {source}")
    chapters: list[Chapter] = []
    metadata: dict[str, str] = {}
    digest = hashlib.sha256()
    references: dict[str, str | None] = {}
    for item in files:
        raw = item.read_bytes()
        digest.update(item.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        relative = item.relative_to(source).as_posix()
        if item.suffix.lower() == ".txt":
            parsed = parse_text(item)
            document_metadata = parsed.metadata
            chapter = parsed.chapters[0]
            chapter.file = relative
            for paragraph in chapter.paragraphs:
                for sentence in paragraph.sentences:
                    sentence.location.file = relative
        else:
            markup = decode_bytes(raw)
            document_metadata = _html_metadata(markup)
            chapter = _chapter_from_markup(markup, relative)
            for name, (_, alt_text) in _local_resources(markup, item, source, True).items():
                if name not in references or (references[name] is None and alt_text is not None):
                    references[name] = alt_text
        for key, value in document_metadata.items():
            if value and key not in metadata:
                metadata[key] = value
        chapters.append(chapter)
    resources: list[Resource] = []
    for item in sorted(resource_paths, key=lambda candidate: candidate.relative_to(source).as_posix()):
        name = item.relative_to(source).as_posix()
        resources.append(_resource(item, name, name in references, references.get(name)))
    return Book(metadata or {"title": source.name}, chapters, resources, source, digest.hexdigest())

"""Offline image review signals / señales de revisión de imágenes."""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping
from pathlib import Path

from ebook_risk_analyzer.models import Book, Finding, Resource

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
_GENERIC_NAME = re.compile(r"^(?:image|img|photo|picture|scan|untitled|dsc)[_ -]?\d*$", re.I)


def _is_image(resource: Resource) -> bool:
    return resource.media_type.startswith("image/") or Path(resource.path).suffix.casefold() in _IMAGE_EXTENSIONS


def _dimensions(path: Path) -> tuple[int, int] | None:
    """Read PNG/GIF/JPEG dimensions only when the resource is a local readable file."""
    try:
        with path.open("rb") as image:
            header = image.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                return struct.unpack(">II", header[16:24])
            if header[:6] in (b"GIF87a", b"GIF89a") and len(header) >= 10:
                return struct.unpack("<HH", header[6:10])
            if header.startswith(b"\xff\xd8"):
                image.seek(2)
                while True:
                    marker = image.read(2)
                    if len(marker) != 2:
                        return None
                    while marker[0] != 0xFF:
                        marker = marker[1:] + image.read(1)
                    if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        image.read(3)
                        height, width = struct.unpack(">HH", image.read(4))
                        return width, height
                    length = struct.unpack(">H", image.read(2))[0]
                    image.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def _finding(book: Book, resource: Resource, code: str, reason: str, severity: str = "medium") -> Finding:
    resource_context = resource.path.strip() or "<unnamed resource>"
    return Finding(severity=severity, category="images", file=resource.path, chapter="", paragraph=0, sentence=0,
        excerpt=f"Image resource: {resource_context}", reason=reason,
        review_action="Review this image resource and its EPUB manifest or HTML references.", code=code, weight=0.5)


def detect_images(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Return local image-resource review signals; no remote fetches are attempted.

    Devuelve señales de recursos de imagen locales; nunca descarga ni verifica recursos remotos.
    """
    del config
    findings: list[Finding] = []
    images = [resource for resource in book.resources if _is_image(resource)]
    hashes: dict[str, list[Resource]] = {}
    for resource in images:
        content_hash = resource.sha256.strip()
        if content_hash:
            hashes.setdefault(content_hash, []).append(resource)
    for matching_resources in hashes.values():
        if len(matching_resources) > 1:
            for resource in matching_resources:
                findings.append(_finding(book, resource, "duplicate_image",
                    "Another inventoried image has the same nonempty content hash; review whether both resources are intentionally retained.", "low"))
    for resource in images:
        filename = Path(resource.path).stem
        if not resource.referenced:
            findings.append(_finding(book, resource, "unused_image", "No local HTML image reference was recorded for this image; review whether it is intentionally retained."))
        if resource.alt_text is None or not resource.alt_text.strip():
            findings.append(_finding(book, resource, "missing_alt_text", "No alternative text is available for this image; review accessibility context."))
        if resource.size <= 0:
            findings.append(_finding(book, resource, "missing_size", "This image has no recorded positive size; review manifest extraction or resource availability."))
        if not resource.sha256:
            findings.append(_finding(book, resource, "missing_hash", "This image has no recorded content hash; review resource inventory completeness.", "low"))
        if _GENERIC_NAME.match(filename):
            findings.append(_finding(book, resource, "generic_filename_weak", "The filename is generic. This is a weak organizational signal only, not evidence of a content problem.", "low"))
        dimensions = _dimensions(Path(resource.path))
        if dimensions is not None and (dimensions[0] < 32 or dimensions[1] < 32):
            findings.append(_finding(book, resource, "small_dimensions", f"Locally readable dimensions are {dimensions[0]}×{dimensions[1]}; review whether that size is intentional.", "low"))
    license_keys = {"license", "licence", "rights", "copyright"}
    if images and not any(str(key).casefold() in license_keys and str(value).strip() for key, value in book.metadata.items()):
        findings.append(_finding(book, images[0], "missing_image_license_context",
            "No book-level rights or license metadata is available for the inventoried images; review licensing documentation.", "low"))
    if not images and book.chapters:
        first = book.chapters[0]
        findings.append(Finding(severity="low", category="images", file=first.file, chapter=first.title, paragraph=0, sentence=0,
            excerpt=f"Image inventory: no image resources recorded for source file {first.file or '<unnamed chapter>'}.",
            reason="No image resources were inventoried; review whether the publication intentionally contains no images.",
            review_action="Confirm the resource inventory and intended image coverage.", code="no_images_inventory", weight=0.2))
    return findings


def detect(book: Book, config: Mapping[str, object] | None = None) -> list[Finding]:
    """Compatibility entry point for image signals."""
    return detect_images(book, config)

"""Defensive, offline EPUB container parsing."""

from __future__ import annotations

import hashlib
import posixpath
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

from .html_parser import _chapter_from_markup, decode_bytes
from .models import Book, Resource

_MAX_ENTRY_SIZE = 100 * 1024 * 1024
_MAX_TOTAL_SIZE = 500 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_MAX_ARCHIVE_MEMBERS = 10_000
_MAX_CENTRAL_DIRECTORY_SIZE = 64 * 1024 * 1024
_MAX_MANIFEST_ITEMS = 5_000
_MAX_SPINE_ITEMS = 5_000
_MAX_PACKAGED_RESOURCES = 5_000
_CONTAINER_NS = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}


_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_EOCD_SIZE = 22
_CENTRAL_DIRECTORY_HEADER_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIRECTORY_HEADER_SIZE = 46
_ZIP64_LOCATOR_SIZE = 20
_ZIP64_EOCD_SIZE = 56
_EOCD_MAX_TAIL_SIZE = _EOCD_SIZE + 0xFFFF


def _preflight_archive_member_count(source: Path) -> None:
    """Validate bounded central-directory metadata before constructing ZipFile."""
    try:
        file_size = source.stat().st_size
        with source.open("rb") as archive_file:
            tail_size = min(file_size, _EOCD_MAX_TAIL_SIZE)
            archive_file.seek(file_size - tail_size)
            tail = archive_file.read(tail_size)
            eocd_offset = tail.rfind(_EOCD_SIGNATURE)
            if eocd_offset < 0:
                return
            while eocd_offset >= 0:
                if len(tail) - eocd_offset >= _EOCD_SIZE:
                    eocd = tail[eocd_offset : eocd_offset + _EOCD_SIZE]
                    _, _, _, _, _, _, _, comment_size = struct.unpack("<4s4H2LH", eocd)
                    if eocd_offset + _EOCD_SIZE + comment_size == len(tail):
                        break
                eocd_offset = tail.rfind(_EOCD_SIGNATURE, 0, eocd_offset)
            if eocd_offset < 0:
                raise ValueError("EPUB ZIP metadata has a malformed or truncated end-of-central-directory record")

            eocd_absolute_offset = file_size - tail_size + eocd_offset
            _, _, _, _, eocd_member_count, eocd_central_size, eocd_central_offset, _ = struct.unpack(
                "<4s4H2LH", tail[eocd_offset : eocd_offset + _EOCD_SIZE]
            )
            metadata_offset = eocd_absolute_offset
            locator = b""
            if eocd_absolute_offset >= _ZIP64_LOCATOR_SIZE:
                archive_file.seek(eocd_absolute_offset - _ZIP64_LOCATOR_SIZE)
                locator = archive_file.read(_ZIP64_LOCATOR_SIZE)
            if locator[:4] == _ZIP64_LOCATOR_SIGNATURE:
                _, _, zip64_eocd_offset, _ = struct.unpack("<4sLQL", locator)
                if zip64_eocd_offset > file_size - _ZIP64_EOCD_SIZE:
                    raise ValueError("EPUB ZIP metadata has a truncated ZIP64 end-of-central-directory record")
                archive_file.seek(zip64_eocd_offset)
                zip64_eocd = archive_file.read(_ZIP64_EOCD_SIZE)
                if len(zip64_eocd) != _ZIP64_EOCD_SIZE:
                    raise ValueError("EPUB ZIP metadata has a truncated ZIP64 end-of-central-directory record")
                signature, record_size, _, _, _, _, _, member_count, central_size, central_offset = struct.unpack(
                    "<4sQ2H2L4Q", zip64_eocd
                )
                if (
                    signature != _ZIP64_EOCD_SIGNATURE
                    or record_size < 44
                    or zip64_eocd_offset + 12 + record_size > file_size
                ):
                    raise ValueError("EPUB ZIP metadata has a malformed ZIP64 end-of-central-directory record")
                metadata_offset = zip64_eocd_offset
            else:
                if (
                    eocd_member_count == 0xFFFF
                    or eocd_central_size == 0xFFFFFFFF
                    or eocd_central_offset == 0xFFFFFFFF
                ):
                    raise ValueError("EPUB ZIP metadata is missing its ZIP64 end-of-central-directory record")
                member_count = eocd_member_count
                central_size = eocd_central_size
                central_offset = eocd_central_offset

            if member_count > _MAX_ARCHIVE_MEMBERS:
                raise ValueError("EPUB contains too many archive members")
            if central_size > _MAX_CENTRAL_DIRECTORY_SIZE:
                raise ValueError("EPUB central directory is too large")
            if central_offset > metadata_offset or central_size > metadata_offset - central_offset:
                raise ValueError("EPUB ZIP metadata has an invalid central-directory range")

            consumed_size = 0
            scanned_member_count = 0
            archive_file.seek(central_offset)
            while consumed_size < central_size:
                remaining_size = central_size - consumed_size
                if remaining_size < _CENTRAL_DIRECTORY_HEADER_SIZE:
                    raise ValueError("EPUB ZIP metadata has a truncated central-directory header")
                header = archive_file.read(_CENTRAL_DIRECTORY_HEADER_SIZE)
                if len(header) != _CENTRAL_DIRECTORY_HEADER_SIZE:
                    raise ValueError("EPUB ZIP metadata has a truncated central-directory header")
                signature, *fields = struct.unpack("<4s6H3L5H2L", header)
                if signature != _CENTRAL_DIRECTORY_HEADER_SIGNATURE:
                    raise ValueError("EPUB ZIP metadata has a malformed central-directory header")
                name_size, extra_size, comment_size = fields[9:12]
                entry_size = _CENTRAL_DIRECTORY_HEADER_SIZE + name_size + extra_size + comment_size
                if entry_size > remaining_size:
                    raise ValueError("EPUB ZIP metadata has a malformed central-directory header length")
                archive_file.seek(entry_size - _CENTRAL_DIRECTORY_HEADER_SIZE, 1)
                consumed_size += entry_size
                scanned_member_count += 1
                if scanned_member_count > _MAX_ARCHIVE_MEMBERS:
                    raise ValueError("EPUB contains too many archive members")

            if scanned_member_count != member_count:
                raise ValueError("EPUB ZIP metadata has a mismatched central-directory member count")
    except OSError as error:
        raise ValueError(f"Unable to read EPUB safely: {error}") from error


def _safe_member(name: str) -> str:
    """Validate and normalize a ZIP member path without allowing traversal."""
    pure = PurePosixPath(name)
    if not name or pure.is_absolute() or ".." in pure.parts or "" in pure.parts:
        raise ValueError(f"EPUB contains unsafe archive path: {name!r}")
    return pure.as_posix()


def _parse_xml(data: bytes, label: str) -> ET.Element:
    """Parse local XML while rejecting DTD/entity declarations."""
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError(f"EPUB {label} must not contain DTD or entity declarations")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"EPUB has invalid {label}: {error}") from error


def _resolve(base: str, href: str) -> str:
    """Resolve an EPUB-relative href and reject escapes from the package root."""
    if not href or "#" in href:
        href = href.split("#", 1)[0]
    candidate = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    return _safe_member(candidate)


def _validate_archive(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Validate member names, encryption, and decompression limits."""
    infos = archive.infolist()
    if len(infos) > _MAX_ARCHIVE_MEMBERS:
        raise ValueError("EPUB contains too many archive members")
    members: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in infos:
        name = _safe_member(info.filename.rstrip("/")) if not info.is_dir() else _safe_member(info.filename.rstrip("/"))
        if name in members:
            raise ValueError(f"EPUB contains duplicate archive path: {name}")
        if info.flag_bits & 0x1:
            raise ValueError(f"EPUB contains encrypted entry: {name}")
        if info.file_size > _MAX_ENTRY_SIZE:
            raise ValueError(f"EPUB entry exceeds safe size limit: {name}")
        if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO):
            raise ValueError(f"EPUB entry has suspicious compression ratio: {name}")
        total_size += info.file_size
        if total_size > _MAX_TOTAL_SIZE:
            raise ValueError("EPUB expanded content exceeds safe total size limit")
        members[name] = info
    return members
_URL_REFERENCE = re.compile(r"""url\(\s*(?:["']([^"']*)["']|([^)\s]+))\s*\)""", re.IGNORECASE)


def _packaged_reference(base_path: str, value: str) -> str | None:
    """Resolve a local resource reference while ignoring external and fragment-only URLs."""
    source = value.split("#", 1)[0].split("?", 1)[0].strip()
    if not source or source.startswith(("/", "//")) or "://" in source or source.startswith("data:"):
        return None
    try:
        return _resolve(base_path, source)
    except ValueError:
        return None


def _add_reference(references: dict[str, str | None], resource_path: str | None, alt_text: str | None = None) -> None:
    """Record a resource reference without replacing meaningful alternative text."""
    if resource_path and (resource_path not in references or (references[resource_path] is None and alt_text)):
        references[resource_path] = alt_text


def _css_references(stylesheet: str, base_path: str) -> dict[str, str | None]:
    """Map local CSS url() references to packaged resource paths."""
    references: dict[str, str | None] = {}
    for match in _URL_REFERENCE.finditer(stylesheet):
        _add_reference(references, _packaged_reference(base_path, match.group(1) or match.group(2)))
    return references


def _image_references(markup: str, chapter_path: str) -> dict[str, str | None]:
    """Map local HTML, SVG, and CSS image references to packaged resource paths."""
    references: dict[str, str | None] = {}
    soup = BeautifulSoup(markup, "lxml")
    for image in soup.find_all("img"):
        alt_text = str(image.get("alt", "")).strip() or None
        _add_reference(references, _packaged_reference(chapter_path, str(image.get("src", ""))), alt_text)
        for candidate in str(image.get("srcset", "")).split(","):
            _add_reference(references, _packaged_reference(chapter_path, candidate.strip().split(" ", 1)[0]), alt_text)
    for source in soup.find_all("source"):
        _add_reference(references, _packaged_reference(chapter_path, str(source.get("src", ""))))
        for candidate in str(source.get("srcset", "")).split(","):
            _add_reference(references, _packaged_reference(chapter_path, candidate.strip().split(" ", 1)[0]))
    for element, attribute in (("object", "data"), ("embed", "src"), ("image", "href"), ("image", "xlink:href")):
        for tag in soup.find_all(element):
            _add_reference(references, _packaged_reference(chapter_path, str(tag.get(attribute, ""))))
    for style in soup.find_all("style"):
        for resource_path, alt_text in _css_references(style.get_text(), chapter_path).items():
            _add_reference(references, resource_path, alt_text)
    for tag in soup.find_all(style=True):
        for resource_path, alt_text in _css_references(str(tag["style"]), chapter_path).items():
            _add_reference(references, resource_path, alt_text)
    return references



def parse_epub(path: Path | str) -> Book:
    """Parse an EPUB ZIP container without extracting or modifying the source file.

    The parser validates archive paths and sizes, encryption flags, the required
    container descriptor, and its OPF package before reading spine documents.
    """
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"EPUB input is not a readable file: {source}")
    _preflight_archive_member_count(source)
    if not zipfile.is_zipfile(source):
        raise ValueError(f"Input is not a valid EPUB ZIP archive: {source}")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(source) as archive:
            members = _validate_archive(archive)
            mimetype = members.get("mimetype")
            if (
                mimetype is None
                or mimetype.compress_type != zipfile.ZIP_STORED
                or mimetype.header_offset != 0
                or archive.read(mimetype) != b"application/epub+zip"
            ):
                raise ValueError("EPUB is missing a valid mimetype declaration")
            container_info = members.get("META-INF/container.xml")
            if container_info is None:
                raise ValueError("EPUB is missing META-INF/container.xml")
            container = _parse_xml(archive.read(container_info), "container.xml")
            rootfile = container.find(".//container:rootfile", _CONTAINER_NS)
            if rootfile is None or not rootfile.get("full-path"):
                raise ValueError("EPUB container does not identify an OPF package")
            opf_path = _safe_member(rootfile.get("full-path", ""))
            opf_info = members.get(opf_path)
            if opf_info is None:
                raise ValueError(f"EPUB OPF package is missing: {opf_path}")
            opf = _parse_xml(archive.read(opf_info), "OPF package")
            metadata: dict[str, str] = {}
            for element in opf.findall(".//dc:*", _OPF_NS):
                value = (element.text or "").strip()
                local_name = element.tag.rsplit("}", 1)[-1]
                if value and local_name not in metadata:
                    metadata[local_name] = value
            manifest: dict[str, tuple[str, str]] = {}
            cover_ids: set[str] = set()
            manifest_count = 0
            for item in opf.iterfind(".//opf:manifest/opf:item", _OPF_NS):
                manifest_count += 1
                if manifest_count > _MAX_MANIFEST_ITEMS:
                    raise ValueError("EPUB OPF package contains too many manifest items")
                item_id, href = item.get("id"), item.get("href")
                if item_id and href:
                    manifest[item_id] = (_resolve(opf_path, href), item.get("media-type", "application/octet-stream"))
                    if "cover-image" in item.get("properties", "").split():
                        cover_ids.add(item_id)
            for meta in opf.findall(".//opf:metadata/opf:meta", _OPF_NS):
                if meta.get("name") == "cover" or meta.get("property") == "cover-image":
                    cover_id = (meta.get("content") or meta.text or "").strip()
                    if cover_id:
                        cover_ids.add(cover_id)
            if not manifest:
                raise ValueError("EPUB OPF package has no manifest")
            spine = opf.find(".//opf:spine", _OPF_NS)
            if spine is None:
                raise ValueError("EPUB OPF package has no spine")
            spine_ids: list[str] = []
            for itemref in spine.iterfind("opf:itemref", _OPF_NS):
                if len(spine_ids) >= _MAX_SPINE_ITEMS:
                    raise ValueError("EPUB OPF package contains too many spine items")
                spine_ids.append(itemref.get("idref", ""))
            packaged_resource_count = sum(
                member_path not in {"mimetype", "META-INF/container.xml", opf_path}
                for member_path in members
            )
            if packaged_resource_count > _MAX_PACKAGED_RESOURCES:
                raise ValueError("EPUB contains too many packaged resources")
            chapters = []
            image_references: dict[str, str | None] = {
                manifest[item_id][0]: None for item_id in cover_ids if item_id in manifest
            }
            for item_id in spine_ids:
                item = manifest.get(item_id)
                if item is None:
                    raise ValueError(f"EPUB spine references unknown manifest item: {item_id}")
                chapter_path, media_type = item
                chapter_info = members.get(chapter_path)
                if chapter_info is None:
                    raise ValueError(f"EPUB spine document is missing: {chapter_path}")
                if media_type not in {"application/xhtml+xml", "text/html", "application/xml"}:
                    raise ValueError(f"EPUB spine item is not an HTML document: {chapter_path}")
                markup = decode_bytes(archive.read(chapter_info))
                for resource_path, alt_text in _image_references(markup, chapter_path).items():
                    if resource_path not in image_references or (image_references[resource_path] is None and alt_text is not None):
                        image_references[resource_path] = alt_text
                chapters.append(_chapter_from_markup(markup, chapter_path))
            for stylesheet_path, stylesheet_info in members.items():
                manifest_item = next(
                    ((path_value, type_value) for path_value, type_value in manifest.values() if path_value == stylesheet_path),
                    None,
                )
                if (manifest_item and manifest_item[1] == "text/css") or stylesheet_path.endswith(".css"):
                    for resource_path, alt_text in _css_references(decode_bytes(archive.read(stylesheet_info)), stylesheet_path).items():
                        _add_reference(image_references, resource_path, alt_text)
            resources: list[Resource] = []
            spine_paths = {manifest[item_id][0] for item_id in spine_ids if item_id in manifest}
            for member_path, info in members.items():
                if member_path in {"mimetype", "META-INF/container.xml", opf_path}:
                    continue
                manifest_item = next(((path_value, type_value) for path_value, type_value in manifest.values() if path_value == member_path), None)
                media_type = manifest_item[1] if manifest_item else "application/octet-stream"
                is_image = media_type.startswith("image/") or PurePosixPath(member_path).suffix.casefold() in _IMAGE_EXTENSIONS
                referenced = member_path in image_references if is_image else member_path in spine_paths
                resources.append(Resource(member_path, media_type, info.file_size, hashlib.sha256(archive.read(info)).hexdigest(),
                    referenced, image_references.get(member_path) if is_image else None))
            return Book(metadata, chapters, resources, source, source_digest)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise ValueError(f"Unable to read EPUB safely: {error}") from error

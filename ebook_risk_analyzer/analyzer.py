"""Offline-first orchestration for ebook human-review signals."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import ssl
from collections.abc import Iterable, Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from http.client import HTTPResponse
from urllib.parse import SplitResult, urljoin, urlsplit

from .detectors.chatbot_residue import detect_chatbot_residue
from .detectors.citations import detect_citations
from .detectors.consistency import detect_consistency
from .detectors.images import detect_images
from .detectors.metadata import detect_metadata
from .detectors.repetition import detect_repetition
from .detectors.structure import detect_structure
from .detectors.style_patterns import detect_style_patterns
from .epub_parser import parse_epub
from .html_parser import parse_directory, parse_html, parse_text
from .models import AnalysisReport, Book, Finding, Sentence
from .scoring import deduplicate_findings, load_rules, risk_level, score_findings, scoring_disclaimer

_URL = re.compile(r"https?://[^\s<>\])}]+", re.IGNORECASE)
_SUPPORTED_TEXT_EXTENSIONS = {".html", ".htm", ".xhtml", ".xml", ".txt"}
_DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
_MAX_DIRECTORY_FILES = 2_000
_MAX_DIRECTORY_BYTES = 500 * 1024 * 1024
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_DETECTORS = (
    detect_chatbot_residue,
    detect_repetition,
    detect_style_patterns,
    detect_structure,
    detect_citations,
    detect_consistency,
    detect_images,
    detect_metadata,
)
_MAX_REDIRECTS = 3
_ALLOWED_LINK_PORTS = {80, 443}
_MAX_LINK_RESPONSE_BYTES = 64 * 1024


def _validated_link_target(url: str) -> tuple[SplitResult, tuple[int, tuple[Any, ...]]] | None:
    """Parse a safe URL and resolve it once to a public socket address."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or "%" in parsed.netloc
        or host.casefold() == "localhost"
        or host.casefold().endswith(".localhost")
    ):
        return None
    default_port = 443 if parsed.scheme.casefold() == "https" else 80
    if (port or default_port) not in _ALLOWED_LINK_PORTS:
        return None
    if re.fullmatch(r"[0-9A-Fa-fxX.]+", host) and not _is_public_address(host):
        return None
    try:
        addresses = socket.getaddrinfo(host, port or default_port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    public_addresses = [
        (family, sockaddr)
        for family, socktype, _protocol, _canonname, sockaddr in addresses
        if socktype == socket.SOCK_STREAM and _is_public_address(sockaddr[0])
    ]
    if len(public_addresses) != len(addresses) or not public_addresses:
        return None
    return parsed, public_addresses[0]


def _safe_link_url(url: str) -> bool:
    """Return whether a link resolves to an allowed public destination."""
    return _validated_link_target(url) is not None


def _host_header(parsed: SplitResult) -> str:
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme.casefold() == "https" else 80
    return host if (parsed.port or default_port) == default_port else f"{host}:{parsed.port}"


def _verify_link(url: str, timeout_seconds: float) -> tuple[int, str | None]:
    """Perform one bounded HEAD request using the address just validated for ``url``."""
    target = _validated_link_target(url)
    if target is None:
        raise ValueError("unsafe link target")
    parsed, (family, sockaddr) = target
    hostname = parsed.hostname
    assert hostname is not None
    connection = socket.socket(family, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout_seconds)
        connection.connect(sockaddr)
        stream: Any = connection
        if parsed.scheme.casefold() == "https":
            stream = ssl.create_default_context().wrap_socket(connection, server_hostname=hostname)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request = (
            f"HEAD {path} HTTP/1.1\r\n"
            f"Host: {_host_header(parsed)}\r\n"
            "User-Agent: ebook-risk-analyzer/0.1\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        stream.sendall(request)
        response = HTTPResponse(stream)
        response.begin()
        response.read(_MAX_LINK_RESPONSE_BYTES + 1)
        return response.status, response.getheader("Location")
    finally:
        connection.close()


def _is_public_address(address: str) -> bool:
    """Return whether an address is globally routable."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False




def parse_source(source: str | Path, max_file_size: int | None = None) -> Book:
    """Parse a supported local source with deterministic resource limits."""
    path = Path(source).expanduser()
    effective_limit = _DEFAULT_MAX_FILE_SIZE if max_file_size is None else max_file_size
    if effective_limit <= 0:
        raise ValueError("max_file_size must be a positive number of bytes")
    if path.is_symlink():
        raise ValueError(f"Input must not be a symbolic link: {path}")
    if path.is_dir():
        count = 0
        total_size = 0
        for child in path.rglob("*"):
            if not child.is_file() or child.suffix.lower() not in _SUPPORTED_TEXT_EXTENSIONS:
                continue
            count += 1
            if count > _MAX_DIRECTORY_FILES:
                raise ValueError(f"Input directory exceeds {_MAX_DIRECTORY_FILES} supported files")
            size = child.stat().st_size
            if size > effective_limit:
                raise ValueError(f"Input file exceeds max-file-size ({effective_limit} bytes): {child}")
            total_size += size
            if total_size > _MAX_DIRECTORY_BYTES:
                raise ValueError(f"Input directory exceeds {_MAX_DIRECTORY_BYTES} total bytes")
        return parse_directory(path, effective_limit, _MAX_DIRECTORY_BYTES)
    if not path.is_file():
        raise ValueError(f"Input is not a readable local file: {path}")
    if path.stat().st_size > effective_limit:
        raise ValueError(f"Input file exceeds max-file-size ({effective_limit} bytes): {path}")
    if path.suffix.lower() == ".epub":
        return parse_epub(path)
    if path.suffix.lower() in {".html", ".htm", ".xhtml", ".xml"}:
        return parse_html(path, effective_limit, _MAX_DIRECTORY_BYTES)
    if path.suffix.lower() == ".txt":
        return parse_text(path)
    raise ValueError("Supported inputs are .epub, HTML/XHTML/XML, .txt, and directories containing them")


def resolve_language(book: Book, language: str = "auto") -> str:
    """Resolve ``auto``, Korean, or English analysis language deterministically."""
    if language not in {"auto", "ko", "en"}:
        raise ValueError("language must be one of: auto, ko, en")
    if language != "auto":
        return language
    declared = book.metadata.get("language", "").casefold().replace("_", "-")
    if declared.startswith("ko"):
        return "ko"
    if declared.startswith("en"):
        return "en"
    sample = " ".join(sentence.text for chapter in book.chapters for paragraph in chapter.paragraphs for sentence in paragraph.sentences)[:10000]
    return "ko" if any("\uac00" <= char <= "\ud7a3" for char in sample) else "en"


def assign_finding_ids(findings: Iterable[Finding]) -> list[Finding]:
    """Assign deterministic IDs derived from each finding's stable review context."""
    assigned: list[Finding] = []
    for finding in findings:
        value = "\x1f".join((finding.category, finding.code, finding.file, finding.chapter, str(finding.paragraph), str(finding.sentence), finding.excerpt, finding.reason))
        finding.id = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        assigned.append(finding)
    return assigned


_KOREAN_CHATBOT_REASONS = {
    "First-person system disclaimer": "1인칭 시스템 고지 문구",
    "Conversational refusal": "대화형 거절 표현",
    "Instruction-like wording": "지시문과 유사한 표현",
    "Conversation role label": "대화 역할 표지",
    "Conversational assistant phrasing": "대화형 보조자 표현",
    "Instruction-like Chinese wording": "지시문과 유사한 중국어 표현",
    "Instruction-like Korean wording": "지시문과 유사한 한국어 표현",
    "Unresolved template marker": "미해결 템플릿 표지",
    "Configured conversational phrase": "설정된 대화형 표현",
}
_KOREAN_REVIEW_ACTIONS = {
    "Confirm this wording is intentional or revise/remove it.": "이 표현이 의도된 것인지 확인하고, 필요하면 수정하거나 제거하세요.",
    "Review the surrounding claim and add, correct, or document an appropriate source where needed.": "주변 주장을 검토하고, 필요하면 적절한 출처를 추가, 수정 또는 기록하세요.",
    "Compare the referenced passages and confirm the intended value or wording.": "참조된 구절을 검토·비교하여 의도한 값이나 표현을 확인하세요.",
    "Review this image resource and its EPUB manifest or HTML references.": "이 이미지 리소스와 EPUB 매니페스트 또는 HTML 참조를 검토하세요.",
    "Confirm the resource inventory and intended image coverage.": "리소스 목록과 의도한 이미지 범위를 확인하세요.",
    "Review the EPUB package metadata and align it with the publication’s displayed information.": "EPUB 패키지 메타데이터를 검토하고 출판물 표시 정보와 맞추세요.",
    "Compare the occurrences and retain, vary, or remove intentional repetition.": "반복 위치를 검토·비교하여 의도된 반복을 유지, 변경 또는 제거하세요.",
    "Check the book structure and revise the source or navigation metadata as needed.": "도서 구조를 확인하고 필요하면 원본 또는 탐색 메타데이터를 수정하세요.",
    "Review this pattern in context and revise only where it affects readability or voice.": "문맥에서 이 패턴을 검토하고 가독성이나 문체에 영향을 주는 경우에만 수정하세요.",
    "Confirm the link manually or update/remove it from the publication.": "링크를 직접 확인하고 출판물에서 업데이트하거나 제거하세요.",
}
_KOREAN_CATEGORY_TEMPLATES = {
    "chatbot_residue": "대화형 문구 검토 신호",
    "repetition": "반복 표현 검토 신호",
    "style_patterns": "문체 패턴 검토 신호",
    "structure": "도서 구조 검토 신호",
    "citations": "인용 및 출처 검토 신호",
    "consistency": "표현 일관성 검토 신호",
    "images": "이미지 리소스 검토 신호",
    "metadata": "출판 메타데이터 검토 신호",
}


def _korean_link_reason(reason: str) -> str:
    """Preserve a checked URL and technical result in Korean review wording."""
    match = _URL.search(reason)
    url = match.group(0) if match else ""
    status = re.search(r"\b(?:HTTP status )?(\d{3})\b", reason)
    if status:
        detail = f"HTTP 상태 {status.group(1)}"
    elif "request could not be completed" in reason:
        detail = "요청을 완료할 수 없음"
    else:
        detail = "확인 결과를 가져올 수 없음"
    return f"링크 확인이 요청되었고 {url}에서 문제가 감지되었습니다. 응답 정보: {detail}. URL과 출처 문맥을 검토하세요."


def _localize_findings(findings: Iterable[Finding], language: str) -> list[Finding]:
    """Localize assembled review wording while retaining source-specific context."""
    if language != "ko":
        return list(findings)

    localized: list[Finding] = []
    for finding in findings:
        if finding.code == "link_verification":
            finding.reason = _korean_link_reason(finding.reason)
        elif finding.category == "chatbot_residue":
            for english, korean in _KOREAN_CHATBOT_REASONS.items():
                finding.reason = finding.reason.replace(english, korean)
            finding.reason = finding.reason.replace(
                "; review whether it belongs in reader-facing prose.",
                "; 독자용 본문에 포함할 표현인지 검토하세요.",
            )
            if re.search(r"[A-Za-z]{3}", finding.reason):
                finding.reason = "대화형 문구 검토 신호입니다. 독자용 본문에 포함할 표현인지 검토하세요."
        else:
            template = _KOREAN_CATEGORY_TEMPLATES.get(finding.category, "검토 신호")
            details: list[str] = [f"탐지 규칙: {finding.code}"]
            parenthesized = re.search(r"\(([^()]*)\)", finding.reason)
            if parenthesized:
                details.append(f"감지된 값: {parenthesized.group(1)}")
            if finding.code == "source_needed_marker":
                details.append("감지된 출처 표지: source-needed marker")
            numbers = re.findall(r"\d+(?:\.\d+)?", finding.reason)
            if numbers:
                details.append(f"근거 수치: {', '.join(numbers)}")
            if finding.excerpt:
                details.append(f"원문 일부: {finding.excerpt[:160]}")
            finding.reason = f"{template}입니다. {'; '.join(details)}. 원문의 수치, 값 및 출처 문맥을 확인하세요."
        original_action = finding.review_action
        finding.review_action = _KOREAN_REVIEW_ACTIONS.get(
            original_action,
            "원문의 위치와 문맥을 사람이 검토하여 필요한 경우에만 수정하세요.",
        )
        localized.append(finding)
    return localized


def _excluded(finding: Finding, rules: Mapping[str, Any]) -> bool:
    """Return whether a configured exclusion suppresses a review signal."""
    exclusions = rules.get("exclusions", {})
    if not isinstance(exclusions, Mapping):
        return False
    files = exclusions.get("files", [])
    file_globs = exclusions.get("file_globs", [])
    phrases = exclusions.get("phrases", [])
    headings = exclusions.get("headings", [])
    return (
        (finding.file in files if isinstance(files, list) else False)
        or (any(fnmatch(finding.file, pattern) for pattern in file_globs if isinstance(pattern, str)) if isinstance(file_globs, list) else False)
        or (finding.excerpt in phrases if isinstance(phrases, list) else False)
        or (finding.chapter in headings if isinstance(headings, list) else False)
    )


def _link_findings(book: Book, timeout_seconds: float, max_links: int) -> list[Finding]:
    """Verify explicitly requested HTTP(S) links and return review signals for failures."""
    findings: list[Finding] = []
    checked: set[str] = set()
    for chapter in book.chapters:
        for paragraph in chapter.paragraphs:
            for sentence in paragraph.sentences:
                for url in _URL.findall(sentence.text):
                    if url in checked or len(checked) >= max_links:
                        continue
                    checked.add(url)
                    current_url = url
                    detail = "could not be safely completed"
                    for redirect_count in range(_MAX_REDIRECTS + 1):
                        try:
                            status, location_header = _verify_link(current_url, timeout_seconds)
                        except (OSError, ValueError, ssl.SSLError):
                            break
                        if 200 <= status < 300:
                            detail = "success"
                            break
                        if status >= 400:
                            detail = f"HTTP status {status}"
                            break
                        if not location_header or redirect_count == _MAX_REDIRECTS:
                            break
                        current_url = urljoin(current_url, location_header)
                    if detail == "success":
                        continue
                    location = sentence.location
                    findings.append(Finding("medium", "citations", location.file, location.chapter, location.paragraph, location.sentence, sentence.text[:300], f"Link verification was requested and {url} {detail}; review the URL and its source context.", "Confirm the link manually or update/remove it from the publication.", "link_verification", 1.0))
    return findings


def analyze_book(book: Book, rules: Mapping[str, Any], language: str = "auto", verify_links: bool = False) -> AnalysisReport:
    """Run all eight local detectors and return a deterministic analysis report."""
    resolved_language = resolve_language(book, language)
    findings = [finding for detector in _DETECTORS for finding in detector(book, rules) if not _excluded(finding, rules)]
    links = rules.get("links", {})
    if verify_links:
        timeout = float(links.get("timeout_seconds", 5)) if isinstance(links, Mapping) else 5.0
        maximum = int(links.get("max_links", 100)) if isinstance(links, Mapping) else 100
        findings.extend(_link_findings(book, max(0.1, timeout), max(0, maximum)))
    findings = _localize_findings(findings, resolved_language)
    findings = assign_finding_ids(deduplicate_findings(findings))
    findings.sort(key=lambda finding: (finding.category, finding.file, finding.chapter, finding.paragraph, finding.sentence, finding.code, finding.id))
    scores, overall = score_findings(findings, rules)
    highest_severity = max(
        (finding.severity.casefold() for finding in findings),
        key=lambda severity: _SEVERITY_RANK.get(severity, 0),
        default="none",
    )
    summary: dict[str, object] = {
        "finding_count": len(findings), "overall_score": overall, "risk_level": risk_level(overall),
        "language": resolved_language, "link_verification": verify_links,
        "highest_finding_severity": highest_severity, "disclaimer": scoring_disclaimer(rules),
    }
    return AnalysisReport(book=book, summary=summary, category_scores=scores, findings=findings)


def analyze_source(source: str | Path, config_path: str | Path | None = None, language: str = "auto", verify_links: bool = False, max_file_size: int | None = None) -> AnalysisReport:
    """Load rules, parse one local source, and run the complete review analysis."""
    return analyze_book(parse_source(source, max_file_size), load_rules(config_path), language, verify_links)


def compare_sources(source1: str | Path, source2: str | Path, config_path: str | Path | None = None, language: str = "auto", verify_links: bool = False, max_file_size: int | None = None) -> dict[str, object]:
    """Return a deterministic comparison of two complete source analyses."""
    left = analyze_source(source1, config_path, language, verify_links, max_file_size)
    right = analyze_source(source2, config_path, language, verify_links, max_file_size)
    return {
        "books": [{"source": str(left.book.source_path), "sha256": left.book.sha256, "summary": left.summary, "category_scores": left.category_scores}, {"source": str(right.book.source_path), "sha256": right.book.sha256, "summary": right.summary, "category_scores": right.category_scores}],
        "score_delta": float(right.summary["overall_score"]) - float(left.summary["overall_score"]),
        "category_score_delta": {key: right.category_scores[key] - left.category_scores[key] for key in sorted(left.category_scores)},
    }

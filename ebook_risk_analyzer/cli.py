"""Command-line interface for the offline-first ebook review-signal analyzer."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence

from .analyzer import analyze_source, compare_sources

_LOG = logging.getLogger("ebook_risk_analyzer")
_SEVERITY = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _positive_size(value: str) -> int:
    """Parse a positive byte count for ``--max-file-size``."""
    try:
        size = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("max-file-size must be an integer number of bytes") from error
    if size <= 0:
        raise argparse.ArgumentTypeError("max-file-size must be greater than zero")
    return size


def _parser() -> argparse.ArgumentParser:
    """Build the public CLI parser."""
    parser = argparse.ArgumentParser(prog="ebook-risk-analyzer", description="Generate offline human-review signals for EPUB and HTML ebooks.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, sources in (("analyze", ("source",)), ("compare", ("source1", "source2"))):
        command = commands.add_parser(name)
        command.add_argument("--verbose", action="store_true", help="Show diagnostic progress messages.")
        for source in sources:
            command.add_argument(source.upper(), type=Path, help="Local EPUB, HTML, text, or source directory.")
        command.add_argument("--output", "-o", required=True, type=Path, help="Output directory.")
        command.add_argument("--language", choices=("auto", "ko", "en"), default="auto", help="Language selection (default: auto).")
        command.add_argument("--verify-links", action="store_true", help="Explicitly permit HTTP(S) link verification; default makes no network requests.")
        command.add_argument("--max-file-size", type=_positive_size, help="Maximum bytes allowed per input file.")
        command.add_argument("--config", type=Path, help="YAML rules override file.")
        command.add_argument("--format", choices=("json", "html", "all"), default="all", help="Output format selection.")
        command.add_argument("--fail-on", choices=("high", "critical", "never"), default="never", help="Exit nonzero when a finding meets this severity.")
    return parser


def _write_comparison(comparison: dict[str, object], output: Path, output_format: str) -> None:
    """Write deterministic JSON and/or escaped-free plain comparison HTML output."""
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output_format in {"json", "all"}:
        (output / "report.json").write_text(payload, encoding="utf-8")
    if output_format in {"html", "all"}:
        import html
        (output / "report.html").write_text("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Ebook comparison</title></head><body><h1>Ebook review-signal comparison</h1><pre>" + html.escape(payload) + "</pre></body></html>\n", encoding="utf-8")


def _fails(report_findings: object, threshold: str, risk_score: float = 0.0) -> bool:
    """Return whether findings or the aggregate risk band meet the exit threshold."""
    if threshold == "never":
        return False
    minimum = _SEVERITY[threshold]
    severity_match = any(
        _SEVERITY.get(getattr(finding, "severity", "").casefold(), 0) >= minimum
        for finding in report_findings  # type: ignore[union-attr]
    )
    score_threshold = 60.0 if threshold == "high" else 80.0
    return severity_match or risk_score >= score_threshold
def _comparison_fails(comparison: object, threshold: str) -> bool:
    """Return whether either comparison input met the requested severity threshold."""
    if threshold == "never" or not isinstance(comparison, dict):
        return False
    minimum = _SEVERITY[threshold]
    books = comparison.get("books", [])
    if not isinstance(books, list):
        return False
    for book in books:
        if not isinstance(book, dict):
            continue
        summary = book.get("summary", {})
        if not isinstance(summary, dict):
            continue
        severity = summary.get("highest_finding_severity", "")
        score = summary.get("overall_score", 0)
        if isinstance(severity, str) and _SEVERITY.get(severity.casefold(), 0) >= minimum:
            return True
        score_threshold = 60.0 if threshold == "high" else 80.0
        if isinstance(score, (int, float)) and float(score) >= score_threshold:
            return True
    return False




def main(argv: Sequence[str] | None = None) -> int:
    """Run the analyzer CLI and return a process-compatible status code."""
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        if args.command == "analyze":
            _LOG.info("Parsing and analyzing %s", args.SOURCE)
            report = analyze_source(args.SOURCE, args.config, args.language, args.verify_links, args.max_file_size)
            from .report_generator import write_reports
            write_reports(report, args.output, args.format)
            _LOG.info("Wrote review artifacts to %s", args.output)
            return 1 if _fails(report.findings, args.fail_on, float(report.summary.get("overall_score", 0))) else 0
        _LOG.info("Comparing %s and %s", args.SOURCE1, args.SOURCE2)
        comparison = compare_sources(args.SOURCE1, args.SOURCE2, args.config, args.language, args.verify_links, args.max_file_size)
        _write_comparison(comparison, args.output, args.format)
        return 1 if _comparison_fails(comparison, args.fail_on) else 0
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

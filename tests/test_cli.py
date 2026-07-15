import io
import socket
from pathlib import Path

import pytest

import ebook_risk_analyzer.analyzer as analyzer
import ebook_risk_analyzer.cli as cli
from ebook_risk_analyzer.models import AnalysisReport, Book, Chapter, Finding, Paragraph, Sentence, SentenceLocation
from ebook_risk_analyzer.scoring import CATEGORY_KEYS


def report_with_severity(severity: str = "high") -> AnalysisReport:
    finding = Finding(severity, "repetition", "book.txt", "Book", 0, 0, "text", "reason", "review", "code", 1.0, "id")
    book = Book({}, [], [], Path("book.txt"), "digest")
    return AnalysisReport(book, {}, {key: 0.0 for key in CATEGORY_KEYS}, [finding])
def link_book(url: str) -> Book:
    location = SentenceLocation("book.html", "Book", 1, 1)
    sentence = Sentence(url, location)
    return Book({}, [Chapter("Book", "book.html", [Paragraph(url, 1, [sentence])])], [], Path("book.html"), "digest")


@pytest.mark.parametrize("url", [
    "http://localhost/",
    "http://sub.localhost/",
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://10.0.0.1/",
    "http://[::]/",
    "http://[fc00::1]/",
    "http://[fe80::1]/",
    "http://[ff00::1]/",
    "http://169.254.1.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://2130706433/",
    "http://127.1/",
    "http://0x7f000001/",
    "http://%31%32%37.0.0.1/",
    "http://public.example:8080/",
    "http://user:password@public.example/",
])
def _mock_link_transport(monkeypatch, addresses, responses):
    connections = []

    class FakeSocket:
        def __init__(self, response):
            self.response = response
            self.connected = None
            self.sent = b""

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.connected = address
            connections.append(self)

        def sendall(self, data):
            self.sent += data

        def makefile(self, mode):
            return io.BytesIO(self.response)

        def close(self):
            self.closed = True

    response_iter = iter(responses)
    monkeypatch.setattr(analyzer.socket, "getaddrinfo", lambda host, port, type: [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, port)) for address in addresses(host)
    ])
    monkeypatch.setattr(analyzer.socket, "socket", lambda family, kind: FakeSocket(next(response_iter)))
    return connections


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://sub.localhost/", "http://127.0.0.1/", "http://[::1]/",
    "http://10.0.0.1/", "http://[::]/", "http://[fc00::1]/", "http://[fe80::1]/",
    "http://[ff00::1]/", "http://169.254.1.1/", "http://172.16.0.1/",
    "http://192.168.1.1/", "http://2130706433/", "http://127.1/",
    "http://0x7f000001/", "http://%31%32%37.0.0.1/", "http://public.example:8080/",
    "http://user:password@public.example/",
])
def test_link_verification_rejects_unsafe_destinations_without_dns_or_http(url, monkeypatch):
    monkeypatch.setattr(analyzer.socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("unsafe URL was resolved"))
    monkeypatch.setattr(analyzer.socket, "socket", lambda *args: pytest.fail("unsafe URL was opened"))
    assert analyzer._link_findings(link_book(url), 1, 1)


def test_link_verification_rejects_internal_dns_answer_without_http(monkeypatch):
    monkeypatch.setattr(analyzer.socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.5", 80))])
    monkeypatch.setattr(analyzer.socket, "socket", lambda *args: pytest.fail("internal DNS target was opened"))
    findings = analyzer._link_findings(link_book("http://public.example/"), 1, 1)
    assert len(findings) == 1


def test_link_verification_pins_validated_address_despite_changing_dns(monkeypatch):
    answers = iter(["8.8.8.8", "127.0.0.1"])
    connections = _mock_link_transport(monkeypatch, lambda host: [next(answers)], [b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"])
    assert analyzer._link_findings(link_book("http://public.example/path"), 5, 1) == []
    assert [connection.connected for connection in connections] == [("8.8.8.8", 80)]
    assert b"Host: public.example\r\n" in connections[0].sent


def test_link_verification_revalidates_redirect_and_rejects_private_target(monkeypatch):
    responses = [b"HTTP/1.1 302 Found\r\nLocation: http://private.example/\r\nContent-Length: 0\r\n\r\n"]
    connections = _mock_link_transport(monkeypatch, lambda host: ["8.8.8.8"] if host == "public.example" else ["192.168.1.5"], responses)
    findings = analyzer._link_findings(link_book("http://public.example/"), 5, 1)
    assert len(findings) == 1
    assert [connection.connected for connection in connections] == [("8.8.8.8", 80)]


def test_link_verification_uses_original_hostname_for_https_sni(monkeypatch):
    connections = _mock_link_transport(monkeypatch, lambda host: ["8.8.8.8"], [b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"])
    wrapped = []

    class Context:
        def wrap_socket(self, connection, server_hostname):
            wrapped.append((connection, server_hostname))
            return connection

    monkeypatch.setattr(analyzer.ssl, "create_default_context", lambda: Context())
    assert analyzer._link_findings(link_book("https://public.example/"), 5, 1) == []
    assert wrapped == [(connections[0], "public.example")]


def test_analyze_options_are_forwarded_and_fail_on_controls_status(tmp_path, monkeypatch):
    received = {}

    def fake_analyze(source, config, language, verify_links, max_file_size):
        received.update(source=source, config=config, language=language, verify_links=verify_links, max_file_size=max_file_size)
        return report_with_severity()

    monkeypatch.setattr(cli, "analyze_source", fake_analyze)
    monkeypatch.setattr("ebook_risk_analyzer.report_generator.write_reports", lambda report, output, format: {})
    config = tmp_path / "rules.yaml"
    status = cli.main(["analyze", str(tmp_path / "book.txt"), "--output", str(tmp_path / "output"), "--config", str(config), "--language", "ko", "--verify-links", "--max-file-size", "9", "--format", "json", "--fail-on", "high"])

    assert status == 1
    assert received == {"source": tmp_path / "book.txt", "config": config, "language": "ko", "verify_links": True, "max_file_size": 9}
    assert cli.main(["analyze", str(tmp_path / "book.txt"), "--output", str(tmp_path / "output"), "--fail-on", "critical"]) == 0


def test_compare_writes_requested_artifacts_and_forwards_options(tmp_path, monkeypatch):
    received = {}

    def fake_compare(left, right, config, language, verify_links, max_file_size):
        received.update(left=left, right=right, config=config, language=language, verify_links=verify_links, max_file_size=max_file_size)
        return {"score_delta": 0.0, "books": [], "category_score_delta": {}}

    monkeypatch.setattr(cli, "compare_sources", fake_compare)
    output = tmp_path / "comparison"
    assert cli.main(["compare", "left.html", "right.html", "--output", str(output), "--language", "en", "--max-file-size", "4", "--format", "all"]) == 0
    assert received == {"left": Path("left.html"), "right": Path("right.html"), "config": None, "language": "en", "verify_links": False, "max_file_size": 4}
    assert (output / "report.json").is_file()
    assert (output / "report.html").is_file()


def test_default_cli_analysis_accepts_directory_and_sample_without_network(tmp_path, monkeypatch):
    source_dir = tmp_path / "book"
    source_dir.mkdir()
    (source_dir / "chapter.html").write_text("<html><body><h1>Sample</h1><p>Visit https://example.invalid/only-for-local-review.</p></body></html>", encoding="utf-8")
    sample = tmp_path / "sample.txt"
    sample.write_text("A standalone local sample.", encoding="utf-8")

    def forbidden_network(*args, **kwargs):
        raise AssertionError("default analysis must not make network requests")

    monkeypatch.setattr(analyzer, "_verify_link", forbidden_network)
    assert cli.main(["analyze", str(source_dir), "--output", str(tmp_path / "directory-output")]) == 0
    assert cli.main(["analyze", str(sample), "--output", str(tmp_path / "sample-output")]) == 0
    assert (tmp_path / "directory-output" / "report.json").is_file()
    assert (tmp_path / "sample-output" / "report.json").is_file()
def test_config_cannot_enable_link_verification_without_cli_flag(tmp_path, monkeypatch):
    source = tmp_path / "book.html"
    source.write_text("<p>Visit https://example.invalid/local-only.</p>", encoding="utf-8")
    config = tmp_path / "rules.yaml"
    config.write_text("links:\n  enabled: true\n", encoding="utf-8")

    def forbidden_network(*args, **kwargs):
        raise AssertionError("configuration must not permit network requests")

    monkeypatch.setattr(analyzer, "_verify_link", forbidden_network)

    assert cli.main([
        "analyze", str(source), "--output", str(tmp_path / "output"), "--config", str(config),
    ]) == 0


def test_cli_rejects_single_file_symlink(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("Local book.", encoding="utf-8")
    link = tmp_path / "book-link.txt"
    link.symlink_to(source)

    with pytest.raises(SystemExit) as error:
        cli.main(["analyze", str(link), "--output", str(tmp_path / "output")])

    assert error.value.code == 2


def test_compare_fail_on_uses_each_book_highest_finding_severity(tmp_path, monkeypatch):
    def fake_compare(*args):
        return {
            "score_delta": 0.0,
            "category_score_delta": {},
            "books": [
                {"summary": {"highest_finding_severity": "high"}},
                {"summary": {"highest_finding_severity": "low"}},
            ],
        }

    monkeypatch.setattr(cli, "compare_sources", fake_compare)

    arguments = ["compare", "left.html", "right.html", "--output", str(tmp_path / "output")]
    assert cli.main([*arguments, "--fail-on", "high"]) == 1
    assert cli.main([*arguments, "--fail-on", "critical"]) == 0


def test_analyze_fail_on_critical_exits_for_critical_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "analyze_source", lambda *args: report_with_severity("critical"))
    monkeypatch.setattr("ebook_risk_analyzer.report_generator.write_reports", lambda *args: None)

    assert cli.main([
        "analyze", str(tmp_path / "book.txt"), "--output", str(tmp_path / "output"),
        "--fail-on", "critical",
    ]) == 1



def test_korean_localization_covers_every_category_and_link_findings():
    findings = [
        Finding("low", category, "book.txt", "Book", 1, 1, f"context-{category}",
                "First-person system disclaimer; review whether it belongs in reader-facing prose."
                if category == "chatbot_residue" else "English detector reason.",
                "Confirm this wording is intentional or revise/remove it."
                if category == "chatbot_residue" else "Unmapped review action.", "representative", 1.0)
        for category in CATEGORY_KEYS
    ]
    findings.append(Finding(
        "medium", "citations", "book.txt", "Book", 1, 1, "link context",
        "Link verification was requested and https://example.test/path HTTP status 404; review the URL and its source context.",
        "Confirm the link manually or update/remove it from the publication.", "link_verification", 1.0,
    ))

    localized = analyzer._localize_findings(findings, "ko")

    assert len(localized) == len(findings)
    assert all(any("가" <= character <= "힣" for character in finding.reason) for finding in localized)
    assert all(any("가" <= character <= "힣" for character in finding.review_action) for finding in localized)
    assert [finding.code for finding in localized[:-1]] == ["representative"] * len(CATEGORY_KEYS)
    assert [finding.excerpt for finding in localized[:-1]] == [f"context-{category}" for category in CATEGORY_KEYS]
    link = localized[-1]
    assert "https://example.test/path" in link.reason
    assert "404" in link.reason
    assert "HTTP status" not in link.reason
def test_korean_localization_preserves_detector_specific_review_details():
    findings = [
        Finding("medium", "style_patterns", "book.txt", "Book", 1, 1, "A 12-word excerpt.",
                "Sentence has 12 words, above configured review threshold 10.",
                "Review this pattern in context and revise only where it affects readability or voice.", "long_sentence", 1.0),
        Finding("medium", "consistency", "book.txt", "Book", 2, 1, "Ages 7 and 9.",
                "This paragraph contains multiple age expressions (7 years old, 9 years old); this is a review signal, not a factual-error claim.",
                "Compare the referenced passages and confirm the intended value or wording.", "multiple_ages", 1.0),
        Finding("medium", "citations", "book.txt", "Book", 3, 1, "[source needed]",
                "The text includes a source-needed marker; review whether a citation should be supplied.",
                "Review the surrounding claim and add, correct, or document an appropriate source where needed.", "source_needed_marker", 1.0),
        Finding("low", "repetition", "book.txt", "Book", 4, 1, "Repeated phrase.",
                "Pair review was truncated after 25 candidate pairs.",
                "Compare the occurrences and retain, vary, or remove intentional repetition.", "pair_limit_reached", 1.0),
    ]

    localized = analyzer._localize_findings(findings, "ko")

    expected_details = (
        ("12", "10", "long_sentence"),
        ("7 years old", "9 years old", "multiple_ages"),
        ("source-needed marker", "source_needed_marker"),
        ("25", "pair_limit_reached"),
    )
    for finding, details in zip(localized, expected_details):
        assert all(detail in finding.reason or detail == finding.code for detail in details)
        assert finding.code in details
        assert finding.excerpt
        assert "검토" in finding.review_action


def test_english_localization_leaves_finding_wording_unchanged():
    finding = Finding(
        "medium", "citations", "book.txt", "Book", 1, 1, "context",
        "English detector reason.", "English review action.", "representative", 1.0,
    )

    localized = analyzer._localize_findings([finding], "en")

    assert localized == [finding]
    assert localized[0].reason == "English detector reason."
    assert localized[0].review_action == "English review action."

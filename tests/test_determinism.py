from ebook_risk_analyzer.analyzer import analyze_source
from ebook_risk_analyzer.report_generator import generate_reports


def test_same_local_input_produces_byte_identical_reports(tmp_path):
    source = tmp_path / "book.html"
    source.write_text(
        "<html><head><title>Stable Book</title></head><body>"
        "<h1>Chapter</h1><p>This sentence repeats exactly. This sentence repeats exactly.</p>"
        "<p>References: DOI 10.0000/example and https://example.invalid.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    first = analyze_source(source)
    second = analyze_source(source)
    first_paths = generate_reports(first, tmp_path / "first")
    second_paths = generate_reports(second, tmp_path / "second")

    assert first.summary == second.summary
    assert first.category_scores == second.category_scores
    assert [finding.id for finding in first.findings] == [finding.id for finding in second.findings]
    assert {name: path.read_bytes() for name, path in first_paths.items()} == {
        name: path.read_bytes() for name, path in second_paths.items()
    }

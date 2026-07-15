from pathlib import Path

import pytest

import ebook_risk_analyzer.analyzer as analyzer
from ebook_risk_analyzer.detectors.metadata import detect_metadata
from ebook_risk_analyzer.html_parser import parse_directory
from ebook_risk_analyzer.models import Book, Chapter, Finding
from ebook_risk_analyzer.scoring import CATEGORY_KEYS, category_scores, load_rules, risk_level, total_score


def finding(category="repetition", weight=1.0, finding_id=""):
    return Finding("high", category, "chapter.html", "Chapter", 1, 1, "Repeated text.", "Review repeated text.", "Compare the source.", "repeat", weight, finding_id)


def test_scores_have_all_categories_deduplicate_and_cap_at_100():
    rules = load_rules()
    duplicate = finding(weight=100.0, finding_id="same")
    scores = category_scores([duplicate, finding(weight=1.0, finding_id="same")], rules)

    assert tuple(scores) == CATEGORY_KEYS
    assert set(scores) == set(CATEGORY_KEYS)
    assert scores["repetition"] == 100.0
    assert all(0.0 <= score <= 100.0 for score in scores.values())


def test_total_score_is_capped_at_100_even_when_rules_exceed_cap():
    rules = {"weights": {"category": {category: 10_000 for category in CATEGORY_KEYS}}, "scoring": {"maximum_score": 10_000}}

    assert total_score({category: 100.0 for category in CATEGORY_KEYS}, rules) == 100.0


def test_risk_levels_change_at_each_exact_boundary():
    assert risk_level(0) == "낮은 위험"
    assert risk_level(29.999) == "낮은 위험"
    assert risk_level(30) == "추가 자료 확인 필요"
    assert risk_level(59.999) == "추가 자료 확인 필요"
    assert risk_level(60) == "사람 검토 필요"
    assert risk_level(79.999) == "사람 검토 필요"
    assert risk_level(80) == "우선 검토 필요"
    assert risk_level(100) == "우선 검토 필요"
def test_load_rules_rejects_unknown_keys_at_every_mapping_depth(tmp_path: Path):
    override = tmp_path / "rules.yaml"
    override.write_text("weights:\n  category:\n    metdata: 0.2\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Unknown rule configuration key.*weights.category.metdata"):
        load_rules(override)


def test_load_rules_merges_valid_nested_override(tmp_path: Path):
    override = tmp_path / "rules.yaml"
    override.write_text("weights:\n  category:\n    metadata: 0.2\n", encoding="utf-8")

    rules = load_rules(override)

    assert rules["weights"]["category"]["metadata"] == 0.2
    assert rules["weights"]["category"]["repetition"] == 0.14


def test_directory_metadata_is_merged_in_sorted_order_and_retains_generator(tmp_path: Path):
    (tmp_path / "b.html").write_text(
        '<html lang="en"><head><title>Later</title><meta name="generator" content="Tool"></head><body><p>B.</p></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "a.html").write_text(
        '<html lang="ko"><head><title>First</title><meta name="creator" content="Author"></head><body><p>A.</p></body></html>',
        encoding="utf-8",
    )

    book = parse_directory(tmp_path)

    assert book.metadata == {"title": "First", "language": "ko", "creator": "Author", "generator": "Tool"}


def test_metadata_normalizes_author_aliases_and_reports_author_title_variants():
    book = Book(
        {"title": "Published Title", "dc:title": "Working Title", "author": "A. Writer", "creator": "Another Writer",
         "language": "en", "identifier": "urn:test"},
        [Chapter("Published Title", "book.html")],
        [],
        Path("book.html"),
        "digest",
    )

    codes = {finding.code for finding in detect_metadata(book)}

    assert {"author_metadata_variant", "title_metadata_variant"} <= codes


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("links:\n  enabled: 'false'\n", r"links.enabled.*boolean"),
        ("thresholds:\n  category_score_points: 0\n", r"thresholds.category_score_points"),
        ("thresholds:\n  category_score_points: 'many'\n", r"thresholds.category_score_points.*number"),
    ],
)
def test_load_rules_rejects_invalid_value_types_and_ranges(tmp_path: Path, contents: str, message: str):
    override = tmp_path / "rules.yaml"
    override.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_rules(override)


def test_string_false_cannot_enable_link_verification(monkeypatch):
    book = Book({}, [], [], Path("book.html"), "digest")
    rules = load_rules()
    rules["links"]["enabled"] = "false"
    invoked = False

    def unexpected_link_check(*args, **kwargs):
        nonlocal invoked
        invoked = True
        return []

    monkeypatch.setattr(analyzer, "_link_findings", unexpected_link_check)

    report = analyzer.analyze_book(book, rules)

    assert not invoked
    assert report.summary["link_verification"] is False

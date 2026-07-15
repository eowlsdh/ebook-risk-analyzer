"""Rule loading and deterministic, human-review-oriented risk scoring."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

import yaml

from .models import Finding

CATEGORY_KEYS: tuple[str, ...] = (
    "chatbot_residue",
    "repetition",
    "style_patterns",
    "structure",
    "citations",
    "consistency",
    "images",
    "metadata",
)

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "default_rules.yaml"


def _default_rules_path() -> Path:
    """Locate packaged defaults in a source checkout or installed environment."""
    source_path = _DEFAULT_RULES_PATH
    if source_path.is_file():
        return source_path
    return Path(sys.prefix) / "share" / "ebook-risk-analyzer" / "config" / "default_rules.yaml"
_DEFAULT_SEVERITY_WEIGHTS: dict[str, float] = {"low": 1.0, "medium": 2.0, "high": 4.0}
_DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "chatbot_residue": 0.18,
    "repetition": 0.14,
    "style_patterns": 0.10,
    "structure": 0.12,
    "citations": 0.12,
    "consistency": 0.12,
    "images": 0.12,
    "metadata": 0.10,
}


def _as_mapping(value: Any, source: Path) -> dict[str, Any]:
    """Return a YAML mapping or raise a clear configuration error."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Rule configuration must be a mapping: {source}")
    return value


_NUMERIC_RANGES: dict[tuple[str, ...], tuple[float, float, bool]] = {
    ("thresholds", "category_score_points"): (0.0, 10_000.0, False),
    ("weights", "severity", "low"): (0.0, 1_000.0, True),
    ("weights", "severity", "medium"): (0.0, 1_000.0, True),
    ("weights", "severity", "high"): (0.0, 1_000.0, True),
    ("weights", "category", "chatbot_residue"): (0.0, 1.0, True),
    ("weights", "category", "repetition"): (0.0, 1.0, True),
    ("weights", "category", "style_patterns"): (0.0, 1.0, True),
    ("weights", "category", "structure"): (0.0, 1.0, True),
    ("weights", "category", "citations"): (0.0, 1.0, True),
    ("weights", "category", "consistency"): (0.0, 1.0, True),
    ("weights", "category", "images"): (0.0, 1.0, True),
    ("weights", "category", "metadata"): (0.0, 1.0, True),
    ("links", "timeout_seconds"): (0.1, 60.0, False),
    ("links", "max_links"): (1.0, 2_000.0, False),
    ("scoring", "maximum_score"): (0.0, 100.0, False),
    ("scoring", "category_score_cap"): (0.0, 100.0, False),
}


def _validate_rule_values(value: Any, schema: Any, source: Path,
                          prefix: tuple[str, ...] = ()) -> None:
    """Validate merged rule values against the shipped configuration schema."""
    rendered_path = ".".join(prefix) or "root"
    if isinstance(schema, Mapping):
        if not isinstance(value, Mapping):
            raise ValueError(f"Rule configuration value “{rendered_path}” in {source} must be a mapping")
        for key, default_value in schema.items():
            if key not in value:
                raise ValueError(f"Rule configuration value “{rendered_path}.{key}” is required in {source}")
            _validate_rule_values(value[key], default_value, source, (*prefix, key))
        return
    if isinstance(schema, bool):
        if not isinstance(value, bool):
            raise ValueError(f"Rule configuration value “{rendered_path}” in {source} must be a boolean")
        return
    if isinstance(schema, (int, float)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"Rule configuration value “{rendered_path}” in {source} must be a number")
        lower, upper, inclusive_lower = _NUMERIC_RANGES.get(prefix, (0.0, 1_000_000.0, True))
        numeric = float(value)
        if not ((numeric >= lower if inclusive_lower else numeric > lower) and numeric <= upper):
            lower_operator = ">=" if inclusive_lower else ">"
            raise ValueError(
                f"Rule configuration value “{rendered_path}” in {source} must be "
                f"{lower_operator} {lower} and <= {upper}"
            )
        return
    if isinstance(schema, str):
        if not isinstance(value, str):
            raise ValueError(f"Rule configuration value “{rendered_path}” in {source} must be a string")
        return
    if isinstance(schema, list):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Rule configuration value “{rendered_path}” in {source} must be a list of strings")
        return
    raise ValueError(f"Unsupported rule schema value at “{rendered_path}” in {source}")

def _validate_override_keys(override: Mapping[str, Any], schema: Mapping[str, Any], source: Path,
                            prefix: tuple[str, ...] = ()) -> None:
    """Reject override keys that are absent from the shipped rule schema."""
    for key, value in override.items():
        path = (*prefix, key)
        if key not in schema:
            rendered_path = ".".join(path)
            raise ValueError(
                f"Unknown rule configuration key “{rendered_path}” in {source}; "
                "check the spelling against config/default_rules.yaml."
            )
        default_value = schema[key]
        if isinstance(value, Mapping) and isinstance(default_value, Mapping):
            _validate_override_keys(value, default_value, source, path)



def _merge_rules(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings, with override scalars and lists replacing defaults."""
    merged = deepcopy(dict(base))
    for key in sorted(override):
        override_value = override[key]
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = _merge_rules(base_value, override_value)
        else:
            merged[key] = deepcopy(override_value)
    return merged


def load_rules(override_path: str | Path | None = None) -> dict[str, Any]:
    """Load default rules and recursively merge one optional user YAML override.

    Mapping keys are merged at every depth; list and scalar overrides replace their
    default values. The result contains no references to either parsed YAML object.
    """
    default_path = _default_rules_path()
    with default_path.open(encoding="utf-8") as stream:
        defaults = _as_mapping(yaml.safe_load(stream), default_path)
    _validate_rule_values(defaults, defaults, default_path)
    if override_path is None:
        return deepcopy(defaults)

    path = Path(override_path)
    with path.open(encoding="utf-8") as stream:
        override = _as_mapping(yaml.safe_load(stream), path)
    _validate_override_keys(override, defaults, path)
    merged = _merge_rules(defaults, override)
    _validate_rule_values(merged, defaults, path)
    return merged


def _number(value: Any, fallback: float) -> float:
    """Convert a configured numeric value without accepting booleans."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else fallback


def _finding_key(finding: Finding) -> tuple[str, ...]:
    """Build a stable identity for duplicate suppression without merging locations."""
    if finding.id:
        return ("id", finding.category, finding.id)
    return (
        "location",
        finding.category,
        finding.code,
        finding.file,
        finding.chapter,
        str(finding.paragraph),
        str(finding.sentence),
        finding.excerpt,
        finding.reason,
    )


def deduplicate_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Keep the highest-weight copy of each issue, preserving input order on ties."""
    unique: dict[tuple[str, ...], Finding] = {}
    for finding in findings:
        key = _finding_key(finding)
        existing = unique.get(key)
        if existing is None or finding.weight > existing.weight:
            unique[key] = finding
    return list(unique.values())


def _effective_weight(finding: Finding, rules: Mapping[str, Any]) -> float:
    """Return a non-negative issue weight, using severity only when weight is absent."""
    if finding.weight > 0:
        return finding.weight
    weights = rules.get("weights", {})
    severity_weights = weights.get("severity", {}) if isinstance(weights, Mapping) else {}
    configured = severity_weights.get(finding.severity.lower(), _DEFAULT_SEVERITY_WEIGHTS.get(finding.severity.lower(), 1.0)) if isinstance(severity_weights, Mapping) else 1.0
    return max(0.0, _number(configured, 1.0))


def category_scores(findings: Iterable[Finding], rules: Mapping[str, Any]) -> dict[str, float]:
    """Return normalized 0--100 scores for every supported review-signal category."""
    thresholds = rules.get("thresholds", {})
    scoring = rules.get("scoring", {})
    points = _number(thresholds.get("category_score_points") if isinstance(thresholds, Mapping) else None, 10.0)
    cap = _number(scoring.get("category_score_cap") if isinstance(scoring, Mapping) else None, 100.0)
    points = points if points > 0 else 10.0
    cap = min(100.0, max(0.0, cap))
    totals = {category: 0.0 for category in CATEGORY_KEYS}
    for finding in deduplicate_findings(findings):
        if finding.category in totals:
            totals[finding.category] += _effective_weight(finding, rules)
    return {category: min(cap, (weight / points) * 100.0) for category, weight in totals.items()}


def total_score(scores: Mapping[str, float], rules: Mapping[str, Any]) -> float:
    """Combine normalized category scores into a capped 0--100 review priority score."""
    weights_section = rules.get("weights", {})
    configured = weights_section.get("category", {}) if isinstance(weights_section, Mapping) else {}
    category_weights = configured if isinstance(configured, Mapping) else {}
    weighted_total = sum(
        max(0.0, _number(scores.get(category), 0.0))
        * max(0.0, _number(category_weights.get(category), _DEFAULT_CATEGORY_WEIGHTS[category]))
        for category in CATEGORY_KEYS
    )
    scoring = rules.get("scoring", {})
    maximum = _number(scoring.get("maximum_score") if isinstance(scoring, Mapping) else None, 100.0)
    return min(100.0, max(0.0, min(maximum, weighted_total)))


def score_findings(findings: Iterable[Finding], rules: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    """Return normalized per-category scores and the capped overall review priority."""
    scores = category_scores(findings, rules)
    return scores, total_score(scores, rules)


def risk_level(score: float | int) -> str:
    """Return the required Korean review-priority band for a clamped score."""
    clamped = min(100.0, max(0.0, float(score)))
    if clamped < 30:
        return "낮은 위험"
    if clamped < 60:
        return "추가 자료 확인 필요"
    if clamped < 80:
        return "사람 검토 필요"
    return "우선 검토 필요"


def scoring_disclaimer(rules: Mapping[str, Any]) -> str:
    """Return the non-diagnostic disclaimer displayed with every score."""
    scoring = rules.get("scoring", {})
    configured = scoring.get("disclaimer") if isinstance(scoring, Mapping) else None
    if isinstance(configured, str) and configured.strip():
        return configured
    return "이 점수만으로 작성 주체를 확정할 수 없음. 사람의 원문 검토와 제작 이력 확인이 필요함."

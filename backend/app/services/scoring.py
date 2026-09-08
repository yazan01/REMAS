"""Deterministic maturity scoring engine.

Kept as pure functions over plain dataclasses so the whole calculation can be
unit-tested against iValue's reference case without touching the database or the
API (BRD FR-26: "All scoring calculations must be deterministic and testable").

Formula note
------------
BRD p.7 states ``Axis Score = Sum(Question Score x Question Weight) / Questions
count``. Dividing by the question count instead of the sum of weights pushes the
result outside the 1-5 scale as soon as any weight differs from 1 (three answers
of 5 at weight 2 give 30/3 = 10). This module implements the weighted mean --
divide by the sum of weights -- and keeps the divisor selectable through
``scoring_config`` so the BRD's literal wording can be switched back on if iValue
signs it off:

    formula = "weighted_average"       -> / sum(weights)     [default]
    formula = "brd_literal"            -> / count(questions)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCORE_PRECISION = 2


@dataclass(slots=True)
class QuestionInput:
    id: str
    code: str
    weight: float = 1.0
    score: int | None = None
    is_not_applicable: bool = False
    is_mandatory: bool = True
    evidence_required: bool = False
    has_evidence: bool = False
    source: str = "answer"  # answer | override | unanswered | not_applicable


@dataclass(slots=True)
class AxisInput:
    id: str
    code: str
    weight: float = 1.0
    strategic_importance: float = 1.0
    questions: list[QuestionInput] = field(default_factory=list)


@dataclass(slots=True)
class AxisResult:
    axis_id: str
    code: str
    weight: float
    score: float | None
    maturity_level: int | None
    total_questions: int
    applicable_questions: int
    answered_questions: int
    not_applicable_questions: int
    unanswered_mandatory: int
    coverage: float
    evidence_completeness: float
    is_scored: bool
    exclusion_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis_id": self.axis_id,
            "code": self.code,
            "weight": self.weight,
            "score": self.score,
            "maturity_level": self.maturity_level,
            "total_questions": self.total_questions,
            "applicable_questions": self.applicable_questions,
            "answered_questions": self.answered_questions,
            "not_applicable_questions": self.not_applicable_questions,
            "unanswered_mandatory": self.unanswered_mandatory,
            "coverage": self.coverage,
            "evidence_completeness": self.evidence_completeness,
            "is_scored": self.is_scored,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(slots=True)
class ScoringResult:
    overall_score: float | None
    maturity_level: int | None
    completeness: float
    evidence_completeness: float
    axes: list[AxisResult]
    strengths: list[str]
    gaps: list[str]
    priorities: list[dict[str, Any]]
    config: dict[str, Any]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "maturity_level": self.maturity_level,
            "completeness": self.completeness,
            "evidence_completeness": self.evidence_completeness,
            "axes": [a.as_dict() for a in self.axes],
            "strengths": self.strengths,
            "gaps": self.gaps,
            "priorities": self.priorities,
            "config": self.config,
            "warnings": self.warnings,
        }


DEFAULT_PRIORITY_WEIGHTS = {
    "maturity_gap": 0.4,
    "axis_weight": 0.25,
    "evidence_gap": 0.2,
    "strategic_importance": 0.15,
}


def level_for_score(score: float | None, config: dict[str, Any]) -> int | None:
    """Map a numeric score onto a maturity level using configurable thresholds."""
    if score is None:
        return None
    thresholds = sorted(
        config.get("thresholds", []), key=lambda t: t["min_score"], reverse=True
    )
    for threshold in thresholds:
        if score >= threshold["min_score"]:
            return int(threshold["level"])
    return int(config.get("scale_min", 1))


def _round(value: float) -> float:
    return round(value + 0.0, SCORE_PRECISION)


def _score_axis(axis: AxisInput, config: dict[str, Any]) -> AxisResult:
    na_handling = config.get("na_handling", "exclude")
    formula = config.get("formula", "weighted_average")
    min_coverage = float(config.get("min_axis_coverage", 0.0))

    total = len(axis.questions)
    na_questions = [q for q in axis.questions if q.is_not_applicable]
    applicable = [q for q in axis.questions if not q.is_not_applicable]

    if na_handling == "zero":
        # Treat N/A as a zero-scoring but counted question.
        scored = [q for q in axis.questions if q.is_not_applicable or q.score is not None]
        applicable = axis.questions
    else:
        scored = [q for q in applicable if q.score is not None]

    answered = len(scored)
    applicable_count = len(applicable)
    unanswered_mandatory = sum(
        1 for q in applicable if q.is_mandatory and q.score is None and not q.is_not_applicable
    )

    evidence_needed = [q for q in applicable if q.evidence_required]
    evidence_completeness = (
        _round(sum(1 for q in evidence_needed if q.has_evidence) / len(evidence_needed))
        if evidence_needed
        else 1.0
    )

    coverage = _round(answered / applicable_count) if applicable_count else 0.0

    if answered == 0:
        return AxisResult(
            axis_id=axis.id,
            code=axis.code,
            weight=axis.weight,
            score=None,
            maturity_level=None,
            total_questions=total,
            applicable_questions=applicable_count,
            answered_questions=0,
            not_applicable_questions=len(na_questions),
            unanswered_mandatory=unanswered_mandatory,
            coverage=0.0,
            evidence_completeness=evidence_completeness,
            is_scored=False,
            exclusion_reason="no_answers",
        )

    numerator = 0.0
    weight_sum = 0.0
    for q in scored:
        value = 0.0 if (q.is_not_applicable and na_handling == "zero") else float(q.score or 0)
        numerator += value * q.weight
        weight_sum += q.weight

    divisor = weight_sum if formula == "weighted_average" else float(answered)
    raw = numerator / divisor if divisor else 0.0
    score = _round(raw)

    is_scored = coverage >= min_coverage
    reason = None if is_scored else "below_min_coverage"

    return AxisResult(
        axis_id=axis.id,
        code=axis.code,
        weight=axis.weight,
        score=score,
        maturity_level=level_for_score(score, config),
        total_questions=total,
        applicable_questions=applicable_count,
        answered_questions=answered,
        not_applicable_questions=len(na_questions),
        unanswered_mandatory=unanswered_mandatory,
        coverage=coverage,
        evidence_completeness=evidence_completeness,
        is_scored=is_scored,
        exclusion_reason=reason,
    )


def _priorities(
    axes: list[AxisResult], config: dict[str, Any], strategic: dict[str, float]
) -> list[dict[str, Any]]:
    """Rank improvement areas (BRD FR-25): maturity gap, axis weight, evidence
    completeness and strategic importance, each with a configurable weight."""
    weights = {**DEFAULT_PRIORITY_WEIGHTS, **(config.get("priority_weights") or {})}
    scale_max = float(config.get("scale_max", 5))
    scale_min = float(config.get("scale_min", 1))
    span = max(scale_max - scale_min, 1.0)

    scored = [a for a in axes if a.is_scored and a.score is not None]
    if not scored:
        return []

    max_axis_weight = max((a.weight for a in scored), default=1.0) or 1.0
    max_strategic = max((strategic.get(a.axis_id, 1.0) for a in scored), default=1.0) or 1.0

    rows: list[dict[str, Any]] = []
    for axis in scored:
        gap = (scale_max - float(axis.score)) / span
        evidence_gap = 1.0 - axis.evidence_completeness
        priority = (
            weights["maturity_gap"] * gap
            + weights["axis_weight"] * (axis.weight / max_axis_weight)
            + weights["evidence_gap"] * evidence_gap
            + weights["strategic_importance"]
            * (strategic.get(axis.axis_id, 1.0) / max_strategic)
        )
        rows.append(
            {
                "axis_id": axis.axis_id,
                "code": axis.code,
                "score": axis.score,
                "maturity_gap": _round(gap),
                "evidence_gap": _round(evidence_gap),
                "priority_score": _round(priority),
            }
        )

    rows.sort(key=lambda r: (-r["priority_score"], r["score"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def compute(axes: list[AxisInput], config: dict[str, Any]) -> ScoringResult:
    """Calculate question -> axis -> overall scores for one assessment."""
    formula = config.get("formula", "weighted_average")
    results = [_score_axis(axis, config) for axis in axes]
    warnings: list[str] = []

    scorable = [a for a in results if a.is_scored and a.score is not None]
    if formula == "brd_literal":
        warnings.append(
            "scoring.formula.brd_literal_may_exceed_scale"
        )

    if scorable:
        numerator = sum(float(a.score) * a.weight for a in scorable)
        weight_sum = sum(a.weight for a in scorable)
        divisor = weight_sum if formula == "weighted_average" else float(len(scorable))
        overall = _round(numerator / divisor) if divisor else None
    else:
        overall = None
        warnings.append("scoring.no_axis_met_minimum_coverage")

    excluded = [a for a in results if not a.is_scored and a.exclusion_reason == "below_min_coverage"]
    if excluded:
        warnings.append("scoring.axes_excluded_below_coverage")

    total_applicable = sum(a.applicable_questions for a in results)
    total_answered = sum(a.answered_questions for a in results)
    completeness = _round(total_answered / total_applicable) if total_applicable else 0.0

    evidence_axes = [a for a in results if a.applicable_questions]
    evidence_completeness = (
        _round(sum(a.evidence_completeness for a in evidence_axes) / len(evidence_axes))
        if evidence_axes
        else 1.0
    )

    ranked = sorted(scorable, key=lambda a: float(a.score), reverse=True)
    strength_cut = float(config.get("strength_threshold", 3.5))
    gap_cut = float(config.get("gap_threshold", 2.5))
    strengths = [a.axis_id for a in ranked if float(a.score) >= strength_cut][:5]
    gaps = [a.axis_id for a in reversed(ranked) if float(a.score) < gap_cut][:5]

    strategic = {a.axis_id: 1.0 for a in results}
    for axis in axes:
        strategic[axis.id] = axis.strategic_importance

    return ScoringResult(
        overall_score=overall,
        maturity_level=level_for_score(overall, config),
        completeness=completeness,
        evidence_completeness=evidence_completeness,
        axes=results,
        strengths=strengths,
        gaps=gaps,
        priorities=_priorities(results, config, strategic),
        config=dict(config),
        warnings=warnings,
    )

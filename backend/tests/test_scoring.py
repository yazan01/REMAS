"""Golden tests for the scoring engine.

These are the tests that must be re-pointed at iValue's reference case the moment
it is delivered (implementation plan, gate G2). Until then they pin the two
things that are already decided: the arithmetic stays inside the 1-5 scale, and
the result is reproducible.
"""

from __future__ import annotations

import pytest

from app.models.content import DEFAULT_SCORING_CONFIG
from app.services import scoring


def config(**overrides) -> dict:
    return {**DEFAULT_SCORING_CONFIG, **overrides}


def axis(code: str, questions: list[tuple[float, int | None]], weight: float = 1.0):
    return scoring.AxisInput(
        id=f"id-{code}",
        code=code,
        weight=weight,
        questions=[
            scoring.QuestionInput(id=f"{code}-{i}", code=f"{code}-Q{i}", weight=w, score=s)
            for i, (w, s) in enumerate(questions, start=1)
        ],
    )


def test_weighted_average_stays_within_scale():
    """The BRD's literal formula divides by question count. With three answers of
    5 at weight 2 that yields 30/3 = 10 — outside the 1-5 scale. The weighted
    mean returns 5."""
    weighted = axis("AX01", [(2.0, 5), (2.0, 5), (2.0, 5)])
    result = scoring.compute([weighted], config())
    assert result.axes[0].score == 5.0
    assert result.overall_score == 5.0

    literal = scoring.compute([axis("AX01", [(2.0, 5), (2.0, 5), (2.0, 5)])],
                              config(formula="brd_literal"))
    assert literal.axes[0].score == 10.0  # documents the defect, does not endorse it
    assert "scoring.formula.brd_literal_may_exceed_scale" in literal.warnings


def test_weights_shift_the_axis_score():
    unweighted = scoring.compute([axis("A", [(1.0, 1), (1.0, 5)])], config())
    assert unweighted.axes[0].score == 3.0

    weighted = scoring.compute([axis("A", [(3.0, 1), (1.0, 5)])], config())
    assert weighted.axes[0].score == 2.0  # (3*1 + 1*5) / 4


def test_not_applicable_is_excluded_from_the_denominator():
    """Assumption pending iValue's decision: an N/A question is neutralised, not
    scored zero. The alternative is one config flag away."""
    questions = [
        scoring.QuestionInput(id="q1", code="Q1", weight=1.0, score=4),
        scoring.QuestionInput(id="q2", code="Q2", weight=1.0, score=4),
        scoring.QuestionInput(id="q3", code="Q3", weight=1.0, is_not_applicable=True),
    ]
    ax = scoring.AxisInput(id="a", code="A", questions=questions)

    excluded = scoring.compute([ax], config(min_axis_coverage=0.0))
    assert excluded.axes[0].score == 4.0
    assert excluded.axes[0].applicable_questions == 2
    assert excluded.axes[0].not_applicable_questions == 1

    zeroed = scoring.compute([ax], config(na_handling="zero", min_axis_coverage=0.0))
    assert zeroed.axes[0].score == pytest.approx(2.67, abs=0.01)  # (4+4+0)/3


def test_axis_below_minimum_coverage_is_excluded_from_overall():
    thin = scoring.AxisInput(
        id="thin",
        code="THIN",
        questions=[
            scoring.QuestionInput(id="q1", code="Q1", score=5),
            scoring.QuestionInput(id="q2", code="Q2"),
            scoring.QuestionInput(id="q3", code="Q3"),
            scoring.QuestionInput(id="q4", code="Q4"),
            scoring.QuestionInput(id="q5", code="Q5"),
        ],
    )
    full = axis("FULL", [(1.0, 2), (1.0, 2)])

    result = scoring.compute([thin, full], config(min_axis_coverage=0.6))
    thin_result = next(a for a in result.axes if a.code == "THIN")
    assert thin_result.is_scored is False
    assert thin_result.exclusion_reason == "below_min_coverage"
    assert result.overall_score == 2.0  # only the fully answered axis counts
    assert "scoring.axes_excluded_below_coverage" in result.warnings


def test_axis_weights_apply_to_the_overall_score():
    heavy = axis("HEAVY", [(1.0, 5)], weight=3.0)
    light = axis("LIGHT", [(1.0, 1)], weight=1.0)
    result = scoring.compute([heavy, light], config())
    assert result.overall_score == 4.0  # (5*3 + 1*1) / 4


def test_maturity_level_thresholds():
    assert scoring.level_for_score(4.6, DEFAULT_SCORING_CONFIG) == 5
    assert scoring.level_for_score(4.5, DEFAULT_SCORING_CONFIG) == 5
    assert scoring.level_for_score(4.49, DEFAULT_SCORING_CONFIG) == 4
    assert scoring.level_for_score(1.0, DEFAULT_SCORING_CONFIG) == 1
    assert scoring.level_for_score(None, DEFAULT_SCORING_CONFIG) is None


def test_unanswered_assessment_produces_no_score():
    empty = scoring.AxisInput(
        id="a", code="A", questions=[scoring.QuestionInput(id="q1", code="Q1")]
    )
    result = scoring.compute([empty], config())
    assert result.overall_score is None
    assert result.maturity_level is None
    assert result.axes[0].exclusion_reason == "no_answers"
    assert "scoring.no_axis_met_minimum_coverage" in result.warnings


def test_evidence_completeness_and_priority_ranking():
    strong = scoring.AxisInput(
        id="strong",
        code="STRONG",
        weight=1.0,
        questions=[
            scoring.QuestionInput(
                id="s1", code="S1", score=5, evidence_required=True, has_evidence=True
            )
        ],
    )
    weak = scoring.AxisInput(
        id="weak",
        code="WEAK",
        weight=2.0,
        questions=[
            scoring.QuestionInput(
                id="w1", code="W1", score=2, evidence_required=True, has_evidence=False
            )
        ],
    )
    result = scoring.compute([strong, weak], config())

    assert result.priorities[0]["code"] == "WEAK"  # low score + high weight + no evidence
    assert result.priorities[0]["rank"] == 1
    assert next(a for a in result.axes if a.code == "WEAK").evidence_completeness == 0.0
    assert next(a for a in result.axes if a.code == "STRONG").evidence_completeness == 1.0
    assert "strong" in result.strengths
    assert "weak" in result.gaps


def test_calculation_is_deterministic():
    axes = [axis("A", [(1.2, 3), (0.8, 4)]), axis("B", [(1.0, 2)], weight=1.5)]
    first = scoring.compute(axes, config()).as_dict()
    second = scoring.compute(axes, config()).as_dict()
    assert first == second

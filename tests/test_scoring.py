"""Tests for the deterministic scoring engine and the sample projects."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "samples"))

import make_sample_data  # noqa: E402
from agent.agent import run_project_pipeline  # noqa: E402
from agent.parser import parse_projects_from_file  # noqa: E402
from agent.scorer import (  # noqa: E402
    BASE_WEIGHTS, RAG_AMBER, RAG_GREEN, _normalise_weights, _score_to_rag,
)

TODAY = datetime(2026, 7, 2)


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    """Build the three fictional sample workbooks and score them offline."""
    out = {}
    make_sample_data.OUT_DIR = tmp_path_factory.mktemp("samples")
    for spec in make_sample_data.PROJECTS:
        path = make_sample_data.build_project(spec)
        (data,) = parse_projects_from_file(path)
        out[spec["name"]] = run_project_pipeline(data, use_llm=False, today=TODAY)
    return out


def test_base_weights_sum_to_one():
    assert sum(BASE_WEIGHTS.values()) == pytest.approx(1.0)


def test_weights_renormalise_without_sentiment():
    w = {k: v for k, v in BASE_WEIGHTS.items() if k != "sentiment"}
    n = _normalise_weights(w)
    assert sum(n.values()) == pytest.approx(1.0)
    assert n["schedule"] == pytest.approx(0.35 / 0.90)


@pytest.mark.parametrize("score,rag", [
    (100, "Green"), (RAG_GREEN, "Green"), (RAG_GREEN - 0.1, "Amber"),
    (RAG_AMBER, "Amber"), (RAG_AMBER - 0.1, "Red"), (0, "Red"),
])
def test_rag_thresholds(score, rag):
    assert _score_to_rag(score) == rag


def test_sample_projects_cover_all_three_bands(reports):
    rags = {r.overall_rag for r in reports.values()}
    assert rags == {"Green", "Amber", "Red"}


def test_scores_are_ordered_by_health(reports):
    s = {name.split(" - ")[0]: r.overall_score for name, r in reports.items()}
    assert s["Orion Retail"] > s["Harbor Foods"] > s["Summit Energy"]


def test_report_rag_matches_report_score(reports):
    for r in reports.values():
        assert _score_to_rag(r.overall_score) == r.overall_rag


def test_scoring_is_deterministic(reports):
    spec = make_sample_data.PROJECTS[2]
    (data,) = parse_projects_from_file(make_sample_data.OUT_DIR / spec["file"])
    again = run_project_pipeline(data, use_llm=False, today=TODAY)
    assert again.overall_score == reports[spec["name"]].overall_score


def test_unowned_on_hold_tasks_lower_the_score(reports):
    # Summit has on-hold, unowned and overdue critical work; Orion has none.
    assert reports["Summit Energy - Sourcing Rollout"].red_tasks > \
        reports["Orion Retail - S2P Implementation"].red_tasks


def test_confidence_is_reported_and_bounded(reports):
    for r in reports.values():
        assert 20 <= r.confidence <= 100
        assert any("Budget" in m for m in r.ignored_metrics)


def test_portfolio_trajectory_compares_weeks_not_projects(tmp_path):
    """Regression: per-project score histories used to be flattened together,
    so one week of three different projects read as a 'trend'."""
    import json
    from aggregator.trends import compute_trends

    def write(name, week, score):
        (tmp_path / f"{name}_{week}.json").write_text(json.dumps({
            "project_name": name, "as_of": week, "overall_score": score,
            "overall_rag": "Green", "confidence": 80, "pace_gap": 0,
        }))

    for name, score in [("A", 95), ("B", 80), ("C", 40)]:   # one week only
        write(name, "2026-07-02", score)
    assert compute_trends(tmp_path).portfolio_trajectory == "Insufficient data"

    for name, score in [("A", 95), ("B", 80), ("C", 40)]:   # a second, identical week
        write(name, "2026-07-09", score)
    assert compute_trends(tmp_path).portfolio_trajectory == "Stable"

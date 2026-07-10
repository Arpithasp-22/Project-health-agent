"""
trends.py
---------
Reads all weekly JSON reports from outputs/weekly/ and computes
cross-project, cross-week trends.

This is the analytical layer for the monthly executive presentation.
It answers questions like:
    - Are projects improving or deteriorating week over week?
    - What are the most common risk categories across the portfolio?
    - Which projects are consistently Amber/Red?
    - Are there emerging risk patterns this month?

Output: a TrendSummary dataclass consumed by synthesizer.py and builder.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProjectTrend:
    """Week-over-week history for a single project."""
    project_name:    str
    weeks:           list[str]         # ISO date strings, chronological
    rag_history:     list[str]         # Red/Amber/Green per week
    score_history:   list[float]
    confidence_history: list[int]
    pace_gap_history: list[float]      # negative = behind schedule
    latest_rag:      str = ""
    latest_score:    float = 0.0
    latest_stage:    str = ""
    trajectory:      str = ""          # "Improving" / "Stable" / "Deteriorating"


@dataclass
class TrendSummary:
    """Portfolio-level trends across all projects and weeks."""
    report_month:        str                    # e.g. "July 2026"
    projects:            list[ProjectTrend]
    portfolio_rag_dist:  dict[str, int]         # {"Red": 1, "Amber": 0, "Green": 1}
    top_risk_categories: list[dict]             # [{"category": ..., "count": ...}]
    common_facts:        list[str]              # Most-repeated observed facts
    emerging_risks:      list[str]              # Risks appearing for first time or growing
    portfolio_trajectory: str                  # overall direction
    weekly_snapshots:    list[dict]             # for chart data
    all_recommendations: list[dict]            # deduplicated, priority-sorted
    data_sources:        list[str]             # files consumed


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_weekly_reports(weekly_dir: Path) -> list[dict]:
    """Load all JSON report files, sorted chronologically."""
    reports = []
    for f in sorted(weekly_dir.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
                data["_source_file"] = f.name
                reports.append(data)
        except Exception as e:
            print(f"[trends] Warning: could not read {f.name}: {e}")
    return reports


# ---------------------------------------------------------------------------
# Trajectory calculation
# ---------------------------------------------------------------------------

_RAG_NUMERIC = {"Green": 2, "Amber": 1, "Red": 0}


def _rag_to_num(rag: str) -> int:
    return _RAG_NUMERIC.get(rag, 1)


def _compute_trajectory(scores: list[float]) -> str:
    """Given a time-series of scores, determine the trend direction."""
    if len(scores) < 2:
        return "Insufficient data"
    first_half = sum(scores[:len(scores)//2]) / max(len(scores)//2, 1)
    second_half = sum(scores[len(scores)//2:]) / max(len(scores) - len(scores)//2, 1)
    delta = second_half - first_half
    if delta > 5:
        return "Improving"
    if delta < -5:
        return "Deteriorating"
    return "Stable"


# ---------------------------------------------------------------------------
# Main aggregation
# ---------------------------------------------------------------------------

def compute_trends(weekly_dir: Path) -> TrendSummary:
    """
    Load all weekly reports and produce a TrendSummary.

    Gracefully handles a single week of data (no trend line, just snapshot).
    """
    reports = _load_weekly_reports(weekly_dir)

    if not reports:
        return TrendSummary(
            report_month         = "N/A",
            projects             = [],
            portfolio_rag_dist   = {},
            top_risk_categories  = [],
            common_facts         = [],
            emerging_risks       = [],
            portfolio_trajectory = "No data",
            weekly_snapshots     = [],
            all_recommendations  = [],
            data_sources         = [],
        )

    # ── Group by project name ──
    by_project: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        by_project[r.get("project_name", "Unknown")].append(r)

    # ── Per-project trends ──
    project_trends: list[ProjectTrend] = []
    for pname, proj_reports in by_project.items():
        proj_reports.sort(key=lambda r: r.get("as_of", ""))
        pt = ProjectTrend(
            project_name        = pname,
            weeks               = [r["as_of"] for r in proj_reports],
            rag_history         = [r.get("overall_rag", "Unknown") for r in proj_reports],
            score_history       = [r.get("overall_score", 0) for r in proj_reports],
            confidence_history  = [r.get("confidence", 0) for r in proj_reports],
            pace_gap_history    = [r.get("pace_gap", 0) for r in proj_reports],
            latest_rag          = proj_reports[-1].get("overall_rag", "Unknown"),
            latest_score        = proj_reports[-1].get("overall_score", 0),
            latest_stage        = proj_reports[-1].get("project_stage", "Unknown"),
        )
        pt.trajectory = _compute_trajectory(pt.score_history)
        project_trends.append(pt)

    # ── Portfolio RAG distribution (from latest report per project) ──
    rag_dist: Counter = Counter()
    for pt in project_trends:
        rag_dist[pt.latest_rag] += 1

    # ── Risk category aggregation ──
    cat_counter: Counter = Counter()
    for r in reports:
        for cat in r.get("risk_categories", []):
            cat_counter[cat.get("category", "")] += cat.get("count", 0)
    top_risk_cats = [
        {"category": cat, "count": cnt}
        for cat, cnt in cat_counter.most_common(6)
        if cat
    ]

    # ── Common observed facts ──
    fact_counter: Counter = Counter()
    for r in reports:
        for fact in r.get("observed_facts", []):
            # Normalise slightly to group similar facts
            key = fact[:80].lower()
            fact_counter[key] += 1
    common_facts = [
        fact for fact, _cnt in fact_counter.most_common(5)
    ]

    # ── Emerging risks ──
    # Risks from the most recent week that weren't present in earlier weeks
    # (or whose count grew significantly)
    emerging_risks: list[str] = []
    if len(reports) >= 2:
        latest_facts = set()
        for r in reports:
            if r.get("as_of") == max(r2.get("as_of", "") for r2 in reports):
                latest_facts.update(
                    f[:80].lower() for f in r.get("observed_facts", [])
                )
        earlier_facts = set()
        for r in reports:
            if r.get("as_of") != max(r2.get("as_of", "") for r2 in reports):
                earlier_facts.update(
                    f[:80].lower() for f in r.get("observed_facts", [])
                )
        emerging = latest_facts - earlier_facts
        emerging_risks = list(emerging)[:4]
    else:
        # Single snapshot: surface Red-tagged findings as risks
        for r in reports:
            if r.get("overall_rag") == "Red":
                emerging_risks.extend(r.get("observed_facts", [])[:2])

    # ── Portfolio trajectory ──
    all_scores = [s for pt in project_trends for s in pt.score_history]
    portfolio_trajectory = _compute_trajectory(all_scores)

    # ── Weekly snapshots (for chart data in presentation) ──
    all_weeks = sorted(set(r.get("as_of", "") for r in reports))
    weekly_snapshots = []
    for week in all_weeks:
        week_reports = [r for r in reports if r.get("as_of") == week]
        snap = {
            "week": week,
            "projects": [
                {
                    "name":  r.get("project_name"),
                    "rag":   r.get("overall_rag"),
                    "score": r.get("overall_score"),
                }
                for r in week_reports
            ],
            "avg_score": round(
                sum(r.get("overall_score", 0) for r in week_reports)
                / len(week_reports), 1
            ) if week_reports else 0,
        }
        weekly_snapshots.append(snap)

    # ── All recommendations (deduplicated, priority-sorted) ──
    seen_actions: set[str] = set()
    all_recs: list[dict] = []
    for r in sorted(reports, key=lambda x: x.get("as_of", ""), reverse=True):
        for rec in r.get("recommendations", []):
            action_key = rec.get("action", "")[:60].lower()
            if action_key not in seen_actions:
                seen_actions.add(action_key)
                all_recs.append({**rec, "project": r.get("project_name")})
    # Sort: High first
    all_recs.sort(key=lambda r: 0 if r.get("priority") == "High" else 1)

    # ── Month label ──
    latest_date = max((r.get("as_of", "") for r in reports), default="")
    if latest_date:
        from datetime import datetime as dt
        try:
            report_month = dt.strptime(latest_date, "%Y-%m-%d").strftime("%B %Y")
        except ValueError:
            report_month = latest_date
    else:
        report_month = "Unknown"

    return TrendSummary(
        report_month         = report_month,
        projects             = project_trends,
        portfolio_rag_dist   = dict(rag_dist),
        top_risk_categories  = top_risk_cats,
        common_facts         = common_facts,
        emerging_risks       = emerging_risks,
        portfolio_trajectory = portfolio_trajectory,
        weekly_snapshots     = weekly_snapshots,
        all_recommendations  = all_recs[:8],
        data_sources         = [r["_source_file"] for r in reports],
    )

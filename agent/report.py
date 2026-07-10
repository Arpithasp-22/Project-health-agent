"""
report.py
---------
Assembles the final project health report from all pipeline layers.

Inputs:
    - ProjectData         (parser)
    - list[ScoredNode]    (scorer)
    - ProjectLLMOutput    (llm_layer)
    - ConfidenceResult    (confidence)

Outputs:
    - ProjectReport       dataclass (in-memory, fully serialisable)
    - JSON file           (machine-readable, saved to outputs/weekly/)
    - Markdown file       (human-readable, saved to outputs/weekly/)

The ProjectReport is the single source of truth consumed by:
    - app.py   (Streamlit UI)
    - builder.py (PowerPoint)
    - database.py (SQLite persistence)
    - aggregator/trends.py (weekly trend analysis)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.confidence import ConfidenceResult
from agent.llm_layer import ProjectLLMOutput
from agent.scorer import ScoredNode, flatten_scored_tree


# ---------------------------------------------------------------------------
# PhaseReport — one entry per top-level scored phase/milestone
# ---------------------------------------------------------------------------

@dataclass
class PhaseReport:
    name:           str
    score:          float
    rag:            str
    pct_complete:   float
    is_on_hold:     bool
    is_at_risk:     bool
    reason_codes:   list[str]
    task_count:     int
    red_tasks:      int
    amber_tasks:    int
    green_tasks:    int
    tasks:          list[dict]   # flat list of leaf task dicts for display


# ---------------------------------------------------------------------------
# ProjectReport — top-level report for one project
# ---------------------------------------------------------------------------

@dataclass
class ProjectReport:
    # Identity
    project_name:    str
    project_manager: str
    project_stage:   str
    source_file:     str
    as_of:           str          # ISO date "YYYY-MM-DD"
    run_timestamp:   str

    # Overall result
    overall_score:   float
    overall_rag:     str

    # Confidence
    confidence:      int
    confidence_note: str
    ignored_metrics: list[str]

    # Schedule pace (derived from meta)
    pct_complete:    float
    pct_time_elapsed: float
    pace_gap:        float        # negative = behind

    # Phase breakdown
    phases:          list[PhaseReport] = field(default_factory=list)

    # LLM outputs
    narrative:       str = ""
    recommendations: list[dict] = field(default_factory=list)
    llm_available:   bool = True

    # Ambiguities surfaced by tree builder
    ambiguities:     list[str] = field(default_factory=list)

    # Summary counts
    total_tasks:     int = 0
    red_tasks:       int = 0
    amber_tasks:     int = 0
    green_tasks:     int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scored_node_to_dict(node: ScoredNode) -> dict:
    """Convert a ScoredNode to a plain dict (JSON-safe)."""
    return {
        "name":               node.name,
        "level":              node.level,
        "node_type":          node.node_type,
        "score":              node.score,
        "rag":                node.rag,
        "pct_complete":       round(node.pct_complete * 100, 1),
        "overdue_days":       node.overdue_days,
        "schedule_health":    node.schedule_health,
        "milestone_health":   node.milestone_health,
        "is_on_hold":         node.is_on_hold,
        "is_at_risk":         node.is_at_risk,
        "is_critical":        node.is_critical,
        "has_owner":          node.has_owner,
        "sentiment_available": node.sentiment_available,
        "sentiment_label":    node.sentiment_label,
        "reason_codes":       node.reason_codes,
        "indicator_scores":   node.indicator_scores,
        "indicator_weights":  node.indicator_weights,
        "ambiguity_flags":    node.ambiguity_flags,
        "start_date":         node.start_date.isoformat() if node.start_date else None,
        "end_date":           node.end_date.isoformat() if node.end_date else None,
    }


def _compute_pace(meta) -> tuple[float, float, float]:
    """
    Returns (pct_time_elapsed, pct_work_done, pace_gap).
    Uses meta.today as reference date.
    """
    today = meta.today or datetime.now()
    pct_done = meta.pct_complete * 100.0

    if meta.start_date and meta.end_date:
        total_span = max((meta.end_date - meta.start_date).days, 1)
        elapsed    = (today - meta.start_date).days
        pct_elapsed = max(0.0, min(100.0, elapsed / total_span * 100.0))
    else:
        pct_elapsed = 0.0

    pace_gap = pct_done - pct_elapsed
    return round(pct_elapsed, 1), round(pct_done, 1), round(pace_gap, 1)


def _build_phase_report(scored_root: ScoredNode) -> PhaseReport:
    """Build a PhaseReport from one top-level ScoredNode."""
    # Handle "No Data" nodes (roots with no descendants)
    if scored_root.rag == "No Data":
        return PhaseReport(
            name         = scored_root.name,
            score        = 0.0,  # Display as 0 for informational nodes
            rag          = "No Data",
            pct_complete = scored_root.pct_complete * 100 if scored_root.pct_complete else 0.0,
            is_on_hold   = False,
            is_at_risk   = False,
            reason_codes = scored_root.reason_codes,
            task_count   = 0,
            red_tasks    = 0,
            amber_tasks  = 0,
            green_tasks  = 0,
            tasks        = [],
        )
    
    # Collect all leaf descendants for task-level display
    all_flat = flatten_scored_tree([scored_root])
    leaf_tasks = [n for n in all_flat if n.node_type == "leaf"]

    red   = sum(1 for t in leaf_tasks if t.rag == "Red")
    amber = sum(1 for t in leaf_tasks if t.rag == "Amber")
    green = sum(1 for t in leaf_tasks if t.rag == "Green")

    task_dicts = [_scored_node_to_dict(t) for t in leaf_tasks]

    return PhaseReport(
        name         = scored_root.name,
        score        = scored_root.score if scored_root.score is not None else 0.0,
        rag          = scored_root.rag,
        pct_complete = round(scored_root.pct_complete * 100, 1),
        is_on_hold   = scored_root.is_on_hold,
        is_at_risk   = scored_root.is_at_risk,
        reason_codes = scored_root.reason_codes,
        task_count   = len(leaf_tasks),
        red_tasks    = red,
        amber_tasks  = amber,
        green_tasks  = green,
        tasks        = task_dicts,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_report(
    meta:           Any,                 # ProjectMeta from parser
    source_file:    str,
    scored_roots:   list[ScoredNode],    # top-level scored phases
    llm_output:     ProjectLLMOutput,
    confidence:     ConfidenceResult,
    ambiguities:    list[str] | None = None,
) -> ProjectReport:
    """
    Assemble one ProjectReport from all pipeline outputs.

    Args:
        meta:         ProjectMeta (dates, PM, stage, etc.)
        source_file:  filename of the source Excel
        scored_roots: top-level ScoredNode list from scorer.score_tree()
        llm_output:   narrative + recommendations from llm_layer
        confidence:   data quality confidence score
        ambiguities:  structural warnings from tree_builder

    Returns:
        ProjectReport — fully populated, ready for serialisation
    """
    now = datetime.now()

    # Overall project score = weighted average of phase scores
    if scored_roots:
        total_w = sum(1.5 if r.is_critical else 1.0 for r in scored_roots)
        overall = sum(
            r.score * (1.5 if r.is_critical else 1.0)
            for r in scored_roots
        ) / max(total_w, 1)
        overall = round(overall, 1)
        overall_rag = (
            "Green" if overall >= 80
            else "Amber" if overall >= 60
            else "Red"
        )
    else:
        overall = 0.0
        overall_rag = "Red"

    # Pace stats
    pct_elapsed, pct_done, pace_gap = _compute_pace(meta)

    # Phase reports
    phases = [_build_phase_report(r) for r in scored_roots]

    # Summary counts across all leaf tasks
    all_flat  = flatten_scored_tree(scored_roots)
    all_leaves = [n for n in all_flat if n.node_type == "leaf"]
    red_count   = sum(1 for t in all_leaves if t.rag == "Red")
    amber_count = sum(1 for t in all_leaves if t.rag == "Amber")
    green_count = sum(1 for t in all_leaves if t.rag == "Green")

    return ProjectReport(
        project_name    = meta.project_name,
        project_manager = meta.project_manager,
        project_stage   = meta.project_stage,
        source_file     = Path(source_file).name,
        as_of           = (meta.today or now).strftime("%Y-%m-%d"),
        run_timestamp   = now.isoformat(timespec="seconds"),
        overall_score   = overall,
        overall_rag     = overall_rag,
        confidence      = confidence.score,
        confidence_note = confidence.note,
        ignored_metrics = confidence.ignored_metrics,
        pct_complete    = pct_done,
        pct_time_elapsed = pct_elapsed,
        pace_gap        = pace_gap,
        phases          = phases,
        narrative       = llm_output.project_narrative,
        recommendations = llm_output.recommendations,
        llm_available   = llm_output.llm_available,
        ambiguities     = ambiguities or [],
        total_tasks     = len(all_leaves),
        red_tasks       = red_count,
        amber_tasks     = amber_count,
        green_tasks     = green_count,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def report_to_dict(report: ProjectReport) -> dict:
    """Convert ProjectReport to a JSON-safe dict."""
    d = asdict(report)
    return d


def save_report_json(report: ProjectReport, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = "".join(c if c.isalnum() else "-" for c in report.project_name.lower())
    slug = slug[:40].strip("-")
    filename = f"{slug}_{report.as_of}.json"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report_to_dict(report), f, indent=2, ensure_ascii=False,
                  default=str)
    return filepath


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

_RAG_EMOJI = {"Red": "🔴", "Amber": "🟡", "Green": "🟢"}


def _rag(r: str) -> str:
    return _RAG_EMOJI.get(r, "⚪")


def render_markdown(report: ProjectReport) -> str:
    lines: list[str] = []

    lines += [
        f"# Weekly Health Report — {report.project_name}",
        f"**Date:** {report.as_of}  |  "
        f"**PM:** {report.project_manager}  |  "
        f"**Stage:** {report.project_stage}",
        "",
        "---",
        f"## {_rag(report.overall_rag)} Overall Status: "
        f"{report.overall_rag}  ({report.overall_score}/100)",
        f"**Confidence:** {report.confidence}%  —  *{report.confidence_note}*",
        "",
    ]

    if report.ignored_metrics:
        lines.append(
            f"**Metrics not assessed:** {', '.join(report.ignored_metrics)}"
        )
        lines.append("")

    if report.ambiguities:
        lines.append("**Structural notes:**")
        for a in report.ambiguities:
            lines.append(f"- ⚠️ {a}")
        lines.append("")

    # Schedule pace
    direction = "behind" if report.pace_gap < 0 else "ahead of"
    lines += [
        "---",
        "## Schedule Pace",
        f"- Work done: **{report.pct_complete:.0f}%**  "
        f"Timeline elapsed: **{report.pct_time_elapsed:.0f}%**",
        f"- **{abs(report.pace_gap):.0f}% {direction} pace**",
        "",
    ]

    # Phase breakdown
    lines += [
        "---",
        "## Phase Breakdown",
        "",
        f"| Phase | Score | Status | Tasks | 🔴 | 🟡 | 🟢 |",
        f"|-------|-------|--------|-------|-----|-----|-----|",
    ]
    for ph in report.phases:
        icon = _rag(ph.rag)
        lines.append(
            f"| {ph.name[:45]} | {ph.score} | "
            f"{icon} {ph.rag} | {ph.task_count} | "
            f"{ph.red_tasks} | {ph.amber_tasks} | {ph.green_tasks} |"
        )
    lines.append("")

    # Narrative
    lines += [
        "---",
        "## Analyst Narrative",
        "*(LLM-generated explanation — score and RAG are from the scoring engine)*",
        "",
        report.narrative,
        "",
    ]

    # Recommendations
    if report.recommendations:
        lines += ["---", "## Recommendations", ""]
        for i, rec in enumerate(report.recommendations, 1):
            pri = rec.get("priority", "Medium")
            lines.append(f"**{i}. [{pri}]** Risk: *{rec['risk']}*")
            lines.append(f"   → {rec['action']}")
            if rec.get("linked_phase"):
                lines.append(f"   Phase: {rec['linked_phase']}")
            lines.append("")

    lines += [
        "---",
        f"*Source: {report.source_file}  |  "
        f"Generated: {report.run_timestamp}*",
    ]

    if not report.llm_available:
        lines.append(
            "*⚠️ LLM unavailable — narrative uses fallback logic.*"
        )

    return "\n".join(lines)


def save_report_markdown(report: ProjectReport, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = "".join(c if c.isalnum() else "-" for c in report.project_name.lower())
    slug = slug[:40].strip("-")
    filename = f"{slug}_{report.as_of}.md"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    return filepath

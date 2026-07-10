"""
scorer.py
---------
Layer 2 of the health engine — deterministic health scoring.

This module contains ZERO parsing logic and ZERO LLM calls.
It receives a tree of TreeNode objects and returns a tree of ScoredNode
objects. Every score is fully traceable to specific data signals.

Scoring model (aligned with methodology.md)
-------------------------------------------
Five indicators, each normalised 0-100:

    Schedule Health    35%   (or 38.9% when sentiment unavailable)
    Milestone Health   25%   (or 27.8% when sentiment unavailable)
    Task Progress      20%   (or 22.2% when sentiment unavailable)
    Blockers & Risks   10%   (or 11.1% when sentiment unavailable)
    Stakeholder Sent.  10%   (excluded + weights redistributed if unavailable)

RAG thresholds (per methodology):
    Green  : 80 – 100
    Amber  : 60 –  79
    Red    : below 60

Roll-up rule:
    parent_score = weighted_avg(children)
    weight = 1.5 if child.is_critical else 1.0

The LLM never calls any function in this module.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.tree_builder import TreeNode


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Base indicator weights (must sum to 1.0)
BASE_WEIGHTS: dict[str, float] = {
    "schedule":  0.35,
    "milestone": 0.25,
    "progress":  0.20,
    "blockers":  0.10,
    "sentiment": 0.10,
}

# RAG thresholds
RAG_GREEN = 80.0
RAG_AMBER = 60.0

# Schedule health flag → numeric score
SCHEDULE_HEALTH_MAP: dict[str, float] = {
    "Green":   100.0,
    "Yellow":  60.0,
    "Amber":   60.0,
    "Red":     20.0,
    "Unknown": 50.0,
}

# Sentinel for "not available"
NOT_AVAILABLE = None


# ---------------------------------------------------------------------------
# ScoredNode
# ---------------------------------------------------------------------------

@dataclass
class ScoredNode:
    """
    One node in the scored tree.

    Every field is a structured fact derived from data.
    The LLM receives this and explains it — it never modifies it.
    """
    # Identity
    name:           str
    level:          int
    node_type:      str          # "leaf" | "branch" | "root"
    row_index:      int

    # Final result
    score:          float | None # 0-100, or None for "No Data" nodes
    rag:            str          # "Red" | "Amber" | "Green" | "No Data"

    # Per-indicator scores (None = unavailable)
    indicator_scores: dict[str, float | None] = field(default_factory=dict)
    # Actual weights used after normalisation
    indicator_weights: dict[str, float] = field(default_factory=dict)

    # Raw facts — passed to LLM as structured evidence
    pct_complete:       float       = 0.0
    overdue_days:       int | None  = None   # positive = overdue
    schedule_health:    str         = "Unknown"
    milestone_health:   str         = "Unknown"  # nearest ancestor's status
    is_on_hold:         bool        = False
    is_at_risk:         bool        = False
    is_critical:        bool        = False
    has_owner:          bool        = False
    sentiment_available: bool       = False
    sentiment_label:    str | None  = None   # "Positive"|"Neutral"|"Negative"

    # Machine-readable reason codes for auditability
    reason_codes:   list[str]       = field(default_factory=list)

    # Ambiguity flags from tree builder
    ambiguity_flags: list[str]      = field(default_factory=list)

    # Children (scored)
    children:       list["ScoredNode"] = field(default_factory=list)

    # Source task name and start/end dates for display
    start_date:     datetime | None = None
    end_date:       datetime | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_rag(score: float) -> str:
    if score >= RAG_GREEN:
        return "Green"
    if score >= RAG_AMBER:
        return "Amber"
    return "Red"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    """Redistribute weights so they sum to 1.0."""
    total = sum(weights.values())
    if total == 0:
        n = len(weights)
        return {k: 1.0 / n for k in weights}
    return {k: v / total for k, v in weights.items()}


def _compute_overdue_days(node: TreeNode, today: datetime) -> int | None:
    """Return positive int if overdue, negative if time remaining, None if no dates."""
    if node.end_date is None:
        return None
    delta = (today - node.end_date).days
    return delta   # positive = overdue, negative = future


# ---------------------------------------------------------------------------
# Indicator 1 — Schedule Health (35%)
# ---------------------------------------------------------------------------

def _score_schedule(node: TreeNode) -> float:
    """
    Maps the schedule_health flag directly to a score.
    This is the PM's assessment stored in the project plan.
    """
    raw = node.schedule_health
    return SCHEDULE_HEALTH_MAP.get(raw, 50.0)


# ---------------------------------------------------------------------------
# Indicator 2 — Milestone Health (25%)
# ---------------------------------------------------------------------------

def _score_milestone(node: TreeNode, today: datetime) -> float:
    """
    Derives milestone health from the nearest non-leaf ancestor's status
    and due date. For a leaf task, this reflects the health of its
    containing phase/summary.

    If no ancestor exists (top-level leaf), uses the node's own status.
    """
    # Find the nearest branch/root ancestor
    ref_node = node.phase_ancestor() or node

    status   = ref_node.task_row.status
    end_date = ref_node.task_row.end_date

    is_overdue = (
        end_date is not None and
        end_date < today and
        status != "Completed"
    )
    is_future = end_date is not None and end_date >= today

    if status == "Completed":
        return 100.0
    elif status == "In Progress":
        return 30.0 if is_overdue else 70.0
    elif status == "Not Started":
        return 20.0 if is_overdue else 80.0
    elif status in ("On Hold",):
        return 10.0
    else:
        return 50.0


# ---------------------------------------------------------------------------
# Indicator 3 — Task Progress (20%)
# ---------------------------------------------------------------------------

def _score_progress(node: TreeNode, today: datetime) -> float:
    """
    Compares actual completion % against expected completion % based on
    elapsed time. If dates are unavailable, uses pct_complete directly.
    """
    pct_actual = node.pct_complete * 100.0   # 0-100

    # If task is completed, full marks
    if node.task_row.status == "Completed":
        return 100.0

    start = node.task_row.start_date
    end   = node.task_row.end_date

    if start is None or end is None:
        # No dates — use completion % directly
        return _clamp(pct_actual)

    total_days = max((end - start).days, 1)
    elapsed    = max((today - start).days, 0)

    if elapsed <= 0:
        # Not started yet and it's still in the future — healthy
        return 90.0 if node.task_row.status == "Not Started" else _clamp(pct_actual)

    pct_elapsed = _clamp(elapsed / total_days * 100.0)

    # Gap: how far behind is actual vs expected
    gap = pct_elapsed - pct_actual   # positive = behind schedule

    if gap <= 0:
        # Ahead of or on schedule
        return 100.0
    else:
        # Behind: each 1% behind = -1.5 pts, capped at 0
        return _clamp(100.0 - gap * 1.5)


# ---------------------------------------------------------------------------
# Indicator 4 — Blockers & Risks (10%)
# ---------------------------------------------------------------------------

def _score_blockers(node: TreeNode, today: datetime) -> tuple[float, list[str]]:
    """
    Starts at 100 and subtracts penalties for blockers and risk flags.
    Returns (score, reason_codes).
    """
    score  = 100.0
    codes: list[str] = []

    if node.is_on_hold:
        score = 0.0
        codes.append("on_hold")
        return score, codes   # on hold overrides everything

    if node.is_at_risk:
        score -= 30.0
        codes.append("at_risk")

    if not node.has_owner:
        score -= 20.0
        codes.append("no_owner")

    # Critical + overdue
    if node.is_critical and node.end_date and node.end_date < today:
        overdue = (today - node.end_date).days
        score -= 40.0
        codes.append(f"critical_overdue_{overdue}d")

    return _clamp(score), codes


# ---------------------------------------------------------------------------
# Indicator 5 — Stakeholder Sentiment (10%)
# ---------------------------------------------------------------------------

def _score_sentiment(
    sentiment_label: str | None
) -> tuple[float | None, bool]:
    """
    Maps a sentiment label to a score.
    Returns (score_or_None, available_bool).

    sentiment_label is set by llm_layer.py BEFORE scoring.
    If no comments exist for this node, sentiment_label is None.
    """
    if sentiment_label is None:
        return NOT_AVAILABLE, False

    mapping = {
        "Positive": 100.0,
        "Neutral":  60.0,
        "Negative": 20.0,
    }
    score = mapping.get(sentiment_label, 60.0)
    return score, True


# ---------------------------------------------------------------------------
# Score a single leaf node
# ---------------------------------------------------------------------------

def _score_leaf(
    node:            TreeNode,
    today:           datetime,
    sentiment_label: str | None,
) -> ScoredNode:
    """
    Compute health score for a leaf task using all 5 indicators.
    Weights are normalised if sentiment is unavailable.
    """
    reason_codes: list[str] = []

    # Compute each indicator
    s_schedule  = _score_schedule(node)
    s_milestone = _score_milestone(node, today)
    s_progress  = _score_progress(node, today)
    s_blockers, blocker_codes = _score_blockers(node, today)
    s_sentiment, sent_avail   = _score_sentiment(sentiment_label)
    reason_codes.extend(blocker_codes)

    # Compute overdue days for facts
    overdue_days = _compute_overdue_days(node, today)
    if overdue_days is not None and overdue_days > 0:
        reason_codes.append(f"overdue_{overdue_days}d")
    if node.task_row.status == "Not Started" and node.start_date and node.start_date < today:
        days_late = (today - node.start_date).days
        reason_codes.append(f"late_to_start_{days_late}d")

    # Build indicator scores dict
    indicator_scores: dict[str, float | None] = {
        "schedule":  s_schedule,
        "milestone": s_milestone,
        "progress":  s_progress,
        "blockers":  s_blockers,
        "sentiment": s_sentiment,
    }

    # Build weights — exclude sentiment if unavailable and renormalise
    active_weights = {k: v for k, v in BASE_WEIGHTS.items()}
    if not sent_avail:
        del active_weights["sentiment"]
    normalised = _normalise_weights(active_weights)

    # Compute final score
    score = sum(
        indicator_scores[k] * normalised[k]
        for k in normalised
        if indicator_scores[k] is not None
    )
    score = _clamp(score)
    rag   = _score_to_rag(score)

    # Milestone health label for facts
    ref = node.phase_ancestor() or node
    milestone_health = ref.task_row.status

    return ScoredNode(
        name              = node.name,
        level             = node.level,
        node_type         = "leaf",
        row_index         = node.row_index,
        score             = round(score, 1),
        rag               = rag,
        indicator_scores  = {k: round(v, 1) if v is not None else None
                             for k, v in indicator_scores.items()},
        indicator_weights = {k: round(v, 4) for k, v in normalised.items()},
        pct_complete      = node.pct_complete,
        overdue_days      = overdue_days if overdue_days and overdue_days > 0 else None,
        schedule_health   = node.schedule_health,
        milestone_health  = milestone_health,
        is_on_hold        = node.is_on_hold,
        is_at_risk        = node.is_at_risk,
        is_critical       = node.is_critical,
        has_owner         = node.has_owner,
        sentiment_available = sent_avail,
        sentiment_label   = sentiment_label,
        reason_codes      = reason_codes,
        ambiguity_flags   = list(node.ambiguity_flags),
        start_date        = node.start_date,
        end_date          = node.end_date,
    )


# ---------------------------------------------------------------------------
# Roll up a branch/root node from its scored children
# ---------------------------------------------------------------------------

def _rollup(
    node:     TreeNode,
    children: list[ScoredNode],
) -> ScoredNode:
    """
    Compute a parent node's score as the weighted average of its children.
    Critical children are weighted 1.5x; others 1.0x.
    
    If a node has no descendants, it is classified as "No Data" —
    an informational/header node that cannot be scored.
    """
    if not children:
        # No descendants — this is an informational/header node
        return ScoredNode(
            name            = node.name,
            level           = node.level,
            node_type       = node.node_type,
            row_index       = node.row_index,
            score           = None,  # Changed: null instead of 0.0
            rag             = "No Data",  # Changed: "No Data" instead of "Red"
            reason_codes    = ["no_executable_tasks"],
            ambiguity_flags = list(node.ambiguity_flags) + ["informational_node"],
            start_date      = node.start_date,
            end_date        = node.end_date,
            pct_complete    = node.pct_complete,
        )

    total_weight  = 0.0
    weighted_sum  = 0.0

    for child in children:
        w = 1.5 if child.is_critical else 1.0
        weighted_sum  += child.score * w
        total_weight  += w

    score = _clamp(weighted_sum / total_weight) if total_weight > 0 else 0.0
    rag   = _score_to_rag(score)

    # Aggregate facts for display
    total_tasks    = len(children)
    red_tasks      = sum(1 for c in children if c.rag == "Red")
    amber_tasks    = sum(1 for c in children if c.rag == "Amber")
    on_hold_tasks  = sum(1 for c in children if c.is_on_hold)
    at_risk_tasks  = sum(1 for c in children if c.is_at_risk)
    overdue_tasks  = sum(1 for c in children if c.overdue_days and c.overdue_days > 0)
    avg_pct        = sum(c.pct_complete for c in children) / total_tasks

    reason_codes: list[str] = []
    if red_tasks:
        reason_codes.append(f"{red_tasks}_red_children")
    if on_hold_tasks:
        reason_codes.append(f"{on_hold_tasks}_on_hold")
    if overdue_tasks:
        reason_codes.append(f"{overdue_tasks}_overdue_children")

    return ScoredNode(
        name              = node.name,
        level             = node.level,
        node_type         = node.node_type,
        row_index         = node.row_index,
        score             = round(score, 1),
        rag               = rag,
        pct_complete      = round(avg_pct, 3),
        is_on_hold        = any(c.is_on_hold for c in children),
        is_at_risk        = any(c.is_at_risk for c in children),
        is_critical       = any(c.is_critical for c in children),
        has_owner         = any(c.has_owner for c in children),
        reason_codes      = reason_codes,
        ambiguity_flags   = list(node.ambiguity_flags),
        children          = children,
        start_date        = node.start_date,
        end_date          = node.end_date,
    )


# ---------------------------------------------------------------------------
# Recursive tree scorer
# ---------------------------------------------------------------------------

def _score_node(
    node:                 TreeNode,
    today:                datetime,
    comment_map:          dict[int, str | None],
) -> ScoredNode:
    """
    Recursively score a node bottom-up.

    comment_map: {node.row_index: sentiment_label or None}
    Sentiment labels must be pre-computed by llm_layer.py before
    this function is called.
    """
    if node.is_leaf:
        sentiment_label = comment_map.get(node.row_index)
        return _score_leaf(node, today, sentiment_label)

    # Score all children first
    scored_children = [
        _score_node(child, today, comment_map)
        for child in node.children
    ]

    # Roll up
    parent = _rollup(node, scored_children)
    return parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_tree(
    roots:       list[TreeNode],
    today:       datetime | None  = None,
    comment_map: dict[int, str | None] | None = None,
) -> list[ScoredNode]:
    """
    Score every node in the tree bottom-up.

    Args:
        roots:       Top-level TreeNode objects (from tree_builder.build_tree)
        today:       Reference date for overdue calculations.
                     Defaults to datetime.now() if not provided.
        comment_map: {node.row_index: sentiment_label}
                     Pre-computed by llm_layer.py from file comments.
                     Pass None if no sentiment data available.

    Returns:
        list[ScoredNode] — one per root, with full child tree attached.
    """
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if comment_map is None:
        comment_map = {}

    scored_roots: list[ScoredNode] = []
    for root in roots:
        scored = _score_node(root, today, comment_map)
        scored_roots.append(scored)

    return scored_roots


def flatten_scored_tree(roots: list[ScoredNode]) -> list[ScoredNode]:
    """Return all ScoredNodes in depth-first order (for tables/reports)."""
    result: list[ScoredNode] = []
    def _walk(node: ScoredNode):
        result.append(node)
        for child in node.children:
            _walk(child)
    for root in roots:
        _walk(root)
    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from agent.parser import parse_projects_from_file
    from agent.tree_builder import build_tree
    from datetime import datetime

    TODAY = datetime(2026, 7, 2)

    files = [
        Path(__file__).parent.parent / "Project Plan B.xlsx",
        Path(__file__).parent.parent / "S2P Project.xlsx",
    ]

    for f in files:
        all_projects = parse_projects_from_file(f)
        print(f"\n{'='*60}")
        print(f"FILE: {f.name}")

        for proj in all_projects:
            tree = build_tree(proj.tasks)
            if not tree.scoreable_roots:
                print(f"\n  [{proj.meta.project_name}] — no scoreable roots, skipping")
                continue

            scored = score_tree(tree.scoreable_roots, today=TODAY)
            print(f"\n  PROJECT: {proj.meta.project_name}")
            print(f"  {'Phase/Task':<45} {'Score':>6} {'RAG':<8} {'Type'}")
            print(f"  {'-'*70}")

            for root in scored:
                icon = "🔴" if root.rag == "Red" else "🟡" if root.rag == "Amber" else "🟢"
                print(f"  {root.name[:45]:<45} {root.score:>6.1f} {icon+root.rag:<10} {root.node_type}")
                for child in root.children[:3]:
                    icon2 = "🔴" if child.rag=="Red" else "🟡" if child.rag=="Amber" else "🟢"
                    print(f"    {child.name[:43]:<43} {child.score:>6.1f} {icon2+child.rag:<10} {child.node_type}")

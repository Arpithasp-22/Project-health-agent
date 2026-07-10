"""
confidence.py
-------------
Tracks what data was available vs missing and computes a confidence score
(0-100%) that is reported alongside every RAG classification.

This is what separates a trustworthy system from a black box.
If the confidence is 62%, the reviewer knows why — specific fields are missing
and the report says so explicitly.

Deduction table (documented, consistent):
    Missing budget data          : -15  (budget not in these files at all)
    No comments in file          : -10  (can't assess stakeholder sentiment)
    Baseline dates mostly missing: -12  (can't compute true variance)
    Schedule variance unparseable: -8   (summary-level variance unavailable)
    High unparseable cell ratio  : -8   (data quality is poor)
    No project end date          : -10  (can't compute pace)
    No project start date        : -5
    Missing assigned owners >30%  : -5  (ownership gaps)

Maximum possible score: 100 (all data present and clean)
Minimum reported:       20  (floor — even bad data gives some signal)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.parser import ProjectData


# ---------------------------------------------------------------------------
# Deduction definitions
# ---------------------------------------------------------------------------

@dataclass
class Deduction:
    reason: str
    points: int
    applied: bool = False


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceResult:
    score:      int             # 0-100
    deductions: list[Deduction] = field(default_factory=list)

    @property
    def note(self) -> str:
        """One-line summary of what reduced confidence."""
        applied = [d for d in self.deductions if d.applied]
        if not applied:
            return "All key data fields present — high confidence"
        parts = [f"{d.reason} (-{d.points}%)" for d in applied]
        return "; ".join(parts)

    @property
    def ignored_metrics(self) -> list[str]:
        """Human-readable list of metrics that couldn't be assessed."""
        mapping = {
            "Budget data not available in source file":     "Budget burn rate",
            "No comments — stakeholder sentiment unavailable": "Stakeholder sentiment",
            "Baseline dates missing for most tasks":        "Baseline schedule variance",
            "Schedule variance field unparseable":          "Summary-level schedule delta",
            "High rate of unparseable cells in task data":  "Partial task field data",
            "Project end date missing":                     "Timeline pace calculation",
            "Project start date missing":                   "Elapsed time calculation",
            "Over 30% of active tasks have no owner":       "Task ownership coverage",
        }
        applied_reasons = {d.reason for d in self.deductions if d.applied}
        return [v for k, v in mapping.items() if k in applied_reasons]


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_confidence(data: ProjectData) -> ConfidenceResult:
    """
    Inspect the parsed ProjectData and data_quality dict to determine
    how complete the data is, then return a ConfidenceResult with score
    and itemised deductions.
    """
    dq   = data.data_quality
    meta = data.meta
    tasks = data.tasks

    deductions: list[Deduction] = [
        Deduction("Budget data not available in source file",          15),
        Deduction("No comments — stakeholder sentiment unavailable",   10),
        Deduction("Baseline dates missing for most tasks",             12),
        Deduction("Schedule variance field unparseable",                8),
        Deduction("High rate of unparseable cells in task data",        8),
        Deduction("Project end date missing",                          10),
        Deduction("Project start date missing",                         5),
        Deduction("Over 30% of active tasks have no owner",             5),
    ]

    # Budget: never present in these files — always deduct
    deductions[0].applied = True

    # Comments
    if not dq.get("has_comments", False):
        deductions[1].applied = True

    # Baseline dates: deduct if >50% of tasks are missing both baseline dates
    missing_bl_pct = dq.get("missing_baseline_pct", 0)
    if missing_bl_pct > 50:
        deductions[2].applied = True

    # Schedule variance in summary unparseable
    missing_summary = dq.get("missing_summary_fields", [])
    if "schedule_variance" in missing_summary or "schedule_delta" in missing_summary:
        deductions[3].applied = True

    # Unparseable cell ratio: deduct if >10% of cells in task sheet are unparseable
    total_rows = dq.get("total_task_rows", 1)
    unparseable = dq.get("unparseable_cell_count", 0)
    # Each row has ~21 mapped columns
    total_cells = total_rows * 21
    if total_cells > 0 and (unparseable / total_cells) > 0.10:
        deductions[4].applied = True

    # Project dates
    if meta.end_date is None:
        deductions[5].applied = True
    if meta.start_date is None:
        deductions[6].applied = True

    # Unassigned active tasks
    live_active = [
        t for t in tasks
        if t.status in ("In Progress", "Not Started") and not t.is_not_applicable
    ]
    if live_active:
        unassigned = sum(1 for t in live_active if t.assigned_to is None)
        if unassigned / len(live_active) > 0.30:
            deductions[7].applied = True

    total_deduction = sum(d.points for d in deductions if d.applied)
    score = max(20, 100 - total_deduction)

    return ConfidenceResult(score=score, deductions=deductions)

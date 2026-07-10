"""
agent.py
--------
Main pipeline orchestrator.

Full pipeline for one file:

    1. parse_projects_from_file()
       → list[ProjectData]  (one per depth-0 root in the file)

    2. For each ProjectData:
       a. build_tree(tasks)
          → TreeResult  (hierarchy reconstructed from flat rows)

       b. map_comments_to_nodes()
          → {node_index: [comment_text]}

       c. classify_comment_sentiment()  [LLM — PRE-SCORING]
          → {node_index: SentimentResult}

       d. score_tree(roots, today, comment_map)
          → list[ScoredNode]  (scores at every level, bottom-up)

       e. compute_confidence(data)
          → ConfidenceResult

       f. generate_project_output()  [LLM — POST-SCORING]
          → ProjectLLMOutput  (narrative + recommendations)

       g. build_report()
          → ProjectReport

       h. save_report_json / save_report_markdown / database writes

Usage
-----
    python agent/agent.py                        # all .xlsx in health_agent/
    python agent/agent.py path/to/file.xlsx      # specific file
    python agent/agent.py --no-llm               # skip Gemini, scores only
    python agent/agent.py --output-dir /path     # custom output dir
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.confidence import compute_confidence
from agent.llm_layer import (
    ProjectLLMOutput,
    build_comment_map,
    classify_comment_sentiment,
    generate_project_output,
)
from agent.parser import ProjectData, parse_projects_from_file
from agent.report import (
    ProjectReport,
    build_report,
    render_markdown,
    report_to_dict,
    save_report_json,
    save_report_markdown,
)
from agent.scorer import ScoredNode, flatten_scored_tree, score_tree
from agent.tree_builder import build_tree, map_comments_to_nodes

OUTPUT_DIR = ROOT / "outputs" / "weekly"


# ---------------------------------------------------------------------------
# Single-project pipeline
# ---------------------------------------------------------------------------

def run_project_pipeline(
    data:    ProjectData,
    use_llm: bool = True,
    today:   datetime | None = None,
) -> ProjectReport:
    """
    Run the full pipeline for one ProjectData slice.

    Args:
        data:    Parsed project (one depth-0 root and its descendants)
        use_llm: If False, skips all Gemini calls
        today:   Override reference date (defaults to meta.today or now)

    Returns:
        ProjectReport — fully populated
    """
    project_name = data.meta.project_name
    ref_date     = today or data.meta.today or \
                   datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n  {'─'*56}")
    print(f"  Project : {project_name}")
    print(f"  PM      : {data.meta.project_manager}")
    print(f"  As of   : {ref_date.strftime('%Y-%m-%d')}")

    # ── Step 1: Build tree ──────────────────────────────────────────────
    print("  [1/5] Building task tree...")
    tree = build_tree(data.tasks)

    if not tree.scoreable_roots:
        print(f"        ⚠  No scoreable roots — skipping (ambiguities: "
              f"{tree.ambiguities[:2]})")
        llm_empty = ProjectLLMOutput(
            project_name      = project_name,
            project_narrative = (
                f"{project_name} could not be scored — no descendant tasks "
                f"were found in the project plan."
            ),
            recommendations = [],
            llm_available   = False,
            fallback_reason = "No scoreable roots in task tree",
        )
        conf = compute_confidence(data)
        return build_report(
            meta         = data.meta,
            source_file  = data.source_file,
            scored_roots = [],
            llm_output   = llm_empty,
            confidence   = conf,
            ambiguities  = tree.ambiguities,
        )

    print(f"        → {len(tree.all_nodes)} nodes, "
          f"{len(tree.scoreable_roots)} scoreable roots")
    if tree.ambiguities:
        for a in tree.ambiguities[:2]:
            print(f"        ⚠  {a}")

    # ── Step 2: Map comments to nodes ───────────────────────────────────
    print("  [2/5] Mapping comments to tasks...")
    comments_by_node = map_comments_to_nodes(tree.all_nodes, data.comments)
    print(f"        → {len(comments_by_node)} task(s) have comments")

    # ── Step 3: Classify sentiment (pre-scoring LLM call) ───────────────
    comment_map: dict[int, str | None] = {}
    if use_llm and comments_by_node:
        print("  [3/5] Classifying comment sentiment (Gemini)...")
        sentiment_results = classify_comment_sentiment(comments_by_node)
        comment_map       = build_comment_map(sentiment_results)
        pos = sum(1 for s in sentiment_results.values() if s.label == "Positive")
        neu = sum(1 for s in sentiment_results.values() if s.label == "Neutral")
        neg = sum(1 for s in sentiment_results.values() if s.label == "Negative")
        print(f"        → Positive: {pos}  Neutral: {neu}  Negative: {neg}")
    else:
        reason = "--no-llm" if not use_llm else "no comments in file"
        print(f"  [3/5] Skipping sentiment ({reason})")

    # ── Step 4: Score tree ──────────────────────────────────────────────
    print("  [4/5] Scoring task tree (deterministic)...")
    scored_roots = score_tree(
        roots       = tree.scoreable_roots,
        today       = ref_date,
        comment_map = comment_map,
    )

    # Compute overall project score for display
    if scored_roots:
        # Exclude "No Data" nodes from portfolio statistics
        scoreable = [r for r in scored_roots if r.rag != "No Data"]
        if scoreable:
            total_w = sum(1.5 if r.is_critical else 1.0 for r in scoreable)
            overall = sum(
                r.score * (1.5 if r.is_critical else 1.0)
                for r in scoreable
            ) / max(total_w, 1)
            overall_rag = "Green" if overall >= 80 else "Amber" if overall >= 60 else "Red"
        else:
            # All roots are "No Data"
            overall     = None
            overall_rag = "No Data"
    else:
        overall     = 0.0
        overall_rag = "Red"

    if overall is not None:
        icon = "🟢" if overall_rag == "Green" else "🟡" if overall_rag == "Amber" else "🔴"
        print(f"        → {icon} {overall_rag}  (score: {overall:.1f}/100)")
    else:
        print(f"        → ⚪ {overall_rag}  (no executable tasks)")

    # Print phase summary
    for phase in scored_roots:
        if phase.rag == "No Data":
            print(f"           ⚪ {phase.name[:40]:<40} {'N/A':>5}  (informational node)")
        else:
            ph_icon = "🟢" if phase.rag=="Green" else "🟡" if phase.rag=="Amber" else "🔴"
            all_leaves = [n for n in flatten_scored_tree([phase]) if n.node_type == "leaf"]
            print(f"           {ph_icon} {phase.name[:40]:<40} "
                  f"{phase.score:>5.1f}  ({len(all_leaves)} tasks)")

    # ── Step 5: Confidence ──────────────────────────────────────────────
    conf = compute_confidence(data)
    print(f"  [5/5] Confidence: {conf.score}%")

    # ── Step 6: LLM project narrative + recommendations ─────────────────
    observed_facts: list[str] = []
    # Only include scoreable roots (exclude "No Data" nodes)
    scoreable_roots = [r for r in scored_roots if r.rag != "No Data"]
    for r in scoreable_roots:
        if r.reason_codes:
            observed_facts.append(f"{r.name}: {', '.join(r.reason_codes[:2])}")

    if use_llm and overall is not None:
        print("        Generating narrative (Gemini)...")
        llm_output = generate_project_output(
            project_name   = project_name,
            overall_score  = round(overall, 1),
            overall_rag    = overall_rag,
            scored_roots   = scoreable_roots,  # Pass only scoreable roots
            observed_facts = observed_facts,
            project_stage  = data.meta.project_stage,
        )
        if not llm_output.llm_available:
            print(f"        ⚠  LLM unavailable: {llm_output.fallback_reason}")
    else:
        llm_output = ProjectLLMOutput(
            project_name      = project_name,
            project_narrative = _build_offline_narrative(
                project_name, overall or 0.0, overall_rag, scoreable_roots
            ),
            recommendations   = _build_offline_recommendations(
                project_name, overall_rag, scoreable_roots
            ),
            llm_available = False,
            fallback_reason   = "--no-llm" if not use_llm else "no_scoreable_data",
        )

    # ── Step 7: Build report ────────────────────────────────────────────
    report = build_report(
        meta         = data.meta,
        source_file  = data.source_file,
        scored_roots = scored_roots,
        llm_output   = llm_output,
        confidence   = conf,
        ambiguities  = tree.ambiguities,
    )

    return report


# ---------------------------------------------------------------------------
# Offline fallbacks (no LLM)
# ---------------------------------------------------------------------------

def _build_offline_narrative(
    name: str, score: float, rag: str, roots: list[ScoredNode]
) -> str:
    red   = sum(1 for r in roots if r.rag == "Red")
    amber = sum(1 for r in roots if r.rag == "Amber")
    total = len(roots)
    return (
        f"{name} has an overall health score of {score:.1f}/100 ({rag}). "
        f"Of {total} phases assessed, {red} are Red and {amber} are Amber. "
        f"Run with LLM enabled for a detailed narrative and recommendations."
    )


def _build_offline_recommendations(
    name: str, rag: str, roots: list[ScoredNode]
) -> list[dict]:
    recs = []
    for r in [x for x in roots if x.rag in ("Red", "Amber")][:3]:
        recs.append({
            "risk":         f"{r.name} is {r.rag} ({r.score:.1f}/100)",
            "action":       f"PM to review {r.name} and escalate blockers.",
            "priority":     "High" if r.rag == "Red" else "Medium",
            "linked_phase": r.name,
        })
    return recs or [{"risk": f"{name} overall", "action": "Review with PM.",
                     "priority": "Medium", "linked_phase": None}]


# ---------------------------------------------------------------------------
# File-level runner — one file → multiple ProjectReports
# ---------------------------------------------------------------------------

def run_file(
    filepath: str | Path,
    use_llm:  bool = True,
    output_dir: Path = OUTPUT_DIR,
) -> list[ProjectReport]:
    """
    Process one file and return a list of ProjectReports
    (one per scoreable project found inside the file).
    """
    filepath = Path(filepath)
    print(f"\n{'='*60}")
    print(f"  FILE: {filepath.name}")

    try:
        all_data = parse_projects_from_file(filepath)
    except Exception as e:
        print(f"  ❌  Could not parse file: {e}")
        return []

    print(f"  Found {len(all_data)} project slice(s)")

    reports: list[ProjectReport] = []

    for data in all_data:
        try:
            report = run_project_pipeline(data, use_llm=use_llm)
            reports.append(report)

            # Save outputs
            json_path = save_report_json(report, output_dir)
            md_path   = save_report_markdown(report, output_dir)
            print(f"        → JSON: {json_path.name}")
            print(f"        → MD  : {md_path.name}")

            # Database writes
            try:
                from database import save_report as db_save_report
                from database import save_daily_metric
                rd = report_to_dict(report)
                db_save_report(rd)
                save_daily_metric(rd)
            except Exception as e:
                print(f"        ⚠  DB write failed: {e}")

        except Exception as e:
            print(f"  ❌  Pipeline failed for "
                  f"{data.meta.project_name}: {e}")
            import traceback
            traceback.print_exc()

    return reports


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evidence-Based Project Health Agent"
    )
    parser.add_argument(
        "files", nargs="*",
        help="Path(s) to project plan files (.xlsx, .xls, .csv). "
             "Defaults to all supported files in the health_agent folder.",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip Gemini API calls — deterministic scoring only.",
    )
    parser.add_argument(
        "--output-dir", default=str(OUTPUT_DIR),
        help="Directory to write weekly reports into.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    use_llm    = not args.no_llm

    # Collect files
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = []
        for ext in ("*.xlsx", "*.xls", "*.csv"):
            files.extend(
                f for f in sorted(ROOT.glob(ext))
                if not f.name.startswith("~$")
            )

    if not files:
        print("[agent] No project files found.")
        sys.exit(1)

    print(f"\n[agent] {len(files)} file(s) to process")
    print(f"[agent] LLM: {'enabled (Gemini)' if use_llm else 'disabled'}")
    print(f"[agent] Output: {output_dir}")

    all_reports: list[ProjectReport] = []
    for f in files:
        reports = run_file(f, use_llm=use_llm, output_dir=output_dir)
        all_reports.extend(reports)

    # Summary table
    print(f"\n{'='*60}")
    print(f"  SUMMARY — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  {'Project':<42} {'RAG':<8} {'Score':<8} {'Conf'}")
    print(f"  {'─'*58}")
    for r in all_reports:
        if r.overall_rag == "No Data":
            print(f"  {r.project_name[:40]:<42} "
                  f"⚪No Data  "
                  f"{'N/A':<8} "
                  f"{r.confidence}%")
        else:
            icon = "🟢" if r.overall_rag=="Green" else "🟡" if r.overall_rag=="Amber" else "🔴"
            print(f"  {r.project_name[:40]:<42} "
                  f"{icon+r.overall_rag:<10} "
                  f"{r.overall_score:<8} "
                  f"{r.confidence}%")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

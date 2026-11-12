"""
builder.py
----------
Generates a 6-slide executive PowerPoint presentation using python-pptx.

Slide structure:
    1. Cover            — Title, date, portfolio headline
    2. Portfolio Snapshot — RAG distribution donut + project health grid
    3. Schedule Velocity  — Completion % vs timeline % per project (bar chart)
    4. Root Cause Analysis — Top risk categories (horizontal bar chart)
    5. Emerging Risks & Trends — Trend narrative + risk signals
    6. Recommendations    — 3-4 portfolio-level actions
    (7. Appendix)         — Per-project dimension breakdown table

Run:
    python presentation/builder.py
    python presentation/builder.py --output my_report.pptx
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

import matplotlib
matplotlib.use("Agg")   # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from aggregator.synthesizer import ExecutiveSynthesis, synthesize
from aggregator.trends import TrendSummary, compute_trends

WEEKLY_DIR  = ROOT / "outputs" / "weekly"
MONTHLY_DIR = ROOT / "outputs" / "monthly"


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

COLORS = {
    "red":    RGBColor(0xC0, 0x39, 0x2B),
    "amber":  RGBColor(0xE6, 0x7E, 0x22),
    "green":  RGBColor(0x27, 0xAE, 0x60),
    "white":  RGBColor(0xFF, 0xFF, 0xFF),
    "dark":   RGBColor(0x1A, 0x1A, 0x2E),
    "mid":    RGBColor(0x16, 0x21, 0x3E),
    "accent": RGBColor(0x0F, 0x3A, 0x6E),
    "light":  RGBColor(0xEC, 0xF0, 0xF1),
    "grey":   RGBColor(0x95, 0xA5, 0xA6),
}

_RAG_COLOR = {
    "Red":     COLORS["red"],
    "Amber":   COLORS["amber"],
    "Green":   COLORS["green"],
    "Unknown": COLORS["grey"],
}

_MPL_RAG = {
    "Red":   "#C0392B",
    "Amber": "#E67E22",
    "Green": "#27AE60",
}


# ---------------------------------------------------------------------------
# Helper: text box
# ---------------------------------------------------------------------------

def _add_textbox(
    slide, left, top, width, height,
    text: str,
    font_size: int = 14,
    bold: bool = False,
    color: RGBColor = None,
    align=PP_ALIGN.LEFT,
    wrap: bool = True,
):
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    txBox.word_wrap = wrap
    tf = txBox.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return txBox


def _add_rect(slide, left, top, width, height, fill_color: RGBColor, alpha: bool = False):
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    return shape


# ---------------------------------------------------------------------------
# Helper: matplotlib figure → pptx image
# ---------------------------------------------------------------------------

def _fig_to_image(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="none", transparent=True)
    buf.seek(0)
    plt.close(fig)
    return buf


# ---------------------------------------------------------------------------
# Chart generators
# ---------------------------------------------------------------------------

def _make_donut_chart(rag_dist: dict[str, int]) -> io.BytesIO:
    labels = [k for k in rag_dist if rag_dist[k] > 0]
    sizes  = [rag_dist[k] for k in labels]
    colors = [_MPL_RAG.get(k, "#95A5A6") for k in labels]

    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, colors=colors,
        autopct="%1.0f%%", startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 2},
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_fontsize(11)
        at.set_color("white")
        at.set_fontweight("bold")

    legend_patches = [
        mpatches.Patch(color=_MPL_RAG.get(lbl, "#95A5A6"), label=f"{lbl} ({rag_dist[lbl]})")
        for lbl in labels
    ]
    ax.legend(handles=legend_patches, loc="lower center",
              bbox_to_anchor=(0.5, -0.15), ncol=len(labels),
              fontsize=10, frameon=False)
    ax.set_title("Project Health\nDistribution", fontsize=12, fontweight="bold", pad=8)
    fig.patch.set_alpha(0)
    return _fig_to_image(fig)


def _make_pace_chart(projects) -> io.BytesIO:
    """Horizontal bar chart: work done vs timeline elapsed per project."""
    names    = [p.project_name[:30] for p in projects]
    # Get latest values from last weekly report — stored in pace_gap_history
    work_done = []
    elapsed   = []
    for p in projects:
        # Reconstruct from pace_gap and most-recent score
        gap = p.pace_gap_history[-1] if p.pace_gap_history else 0
        # We don't store pct_elapsed directly in ProjectTrend, so approximate
        # from score history (schedule score ≈ proxy for pace)
        elapsed.append(min(100, max(0, p.latest_score)))
        work_done.append(min(100, max(0, p.latest_score + gap)))

    x = range(len(names))
    fig, ax = plt.subplots(figsize=(6, max(2.5, len(names) * 1.2)))
    bar_w = 0.35
    bars1 = ax.barh([i + bar_w/2 for i in x], work_done,
                    height=bar_w, label="Work Done %", color="#27AE60", alpha=0.85)
    bars2 = ax.barh([i - bar_w/2 for i in x], elapsed,
                    height=bar_w, label="Timeline Elapsed %", color="#2980B9", alpha=0.85)

    ax.set_yticks(list(x))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Percentage (%)", fontsize=9)
    ax.set_title("Schedule Pace: Work Done vs Timeline Elapsed", fontsize=11, fontweight="bold")
    ax.set_xlim(0, 110)
    ax.legend(fontsize=9, frameon=False)
    ax.axvline(x=50, color="grey", linestyle="--", linewidth=0.8, alpha=0.5)
    for bar in bars1:
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                f"{bar.get_width():.0f}%", va="center", fontsize=8)

    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    plt.tight_layout()
    return _fig_to_image(fig)


def _make_risk_category_chart(top_risks: list[dict]) -> io.BytesIO:
    """Horizontal bar chart of risk category frequency."""
    if not top_risks:
        fig, ax = plt.subplots(figsize=(5, 2))
        ax.text(0.5, 0.5, "No comment data available",
                ha="center", va="center", fontsize=11, color="grey")
        ax.axis("off")
        fig.patch.set_alpha(0)
        return _fig_to_image(fig)

    labels = [r["category"] for r in top_risks]
    counts = [r["count"] for r in top_risks]
    total  = sum(counts)
    pcts   = [c / total * 100 for c in counts]

    palette = ["#C0392B", "#E67E22", "#2980B9", "#8E44AD", "#27AE60", "#16A085"]
    colors  = palette[:len(labels)]

    fig, ax = plt.subplots(figsize=(6, max(2.5, len(labels) * 0.7)))
    bars = ax.barh(labels[::-1], pcts[::-1], color=colors[::-1], alpha=0.85)
    for bar, pct in zip(bars, pcts[::-1]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                f"{pct:.0f}%", va="center", fontsize=9)
    ax.set_xlabel("% of Flagged Comments", fontsize=9)
    ax.set_title("Root Cause Distribution (Comment Analysis)", fontsize=11, fontweight="bold")
    ax.set_xlim(0, max(pcts) * 1.2 + 5)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    plt.tight_layout()
    return _fig_to_image(fig)


# ---------------------------------------------------------------------------
# Slide builders
# ---------------------------------------------------------------------------

SLIDE_W = 10.0
SLIDE_H = 7.5


def _slide_cover(prs: Presentation, trends: TrendSummary, synthesis: ExecutiveSynthesis):
    layout = prs.slide_layouts[6]   # blank
    slide  = prs.slides.add_slide(layout)

    # Background
    _add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, COLORS["dark"])

    # Accent bar
    _add_rect(slide, 0, 5.8, SLIDE_W, 0.08, COLORS["accent"])

    _add_textbox(slide, 0.6, 1.2, 8.8, 1.0,
                 "PROJECT PORTFOLIO", font_size=13, bold=True,
                 color=COLORS["grey"], align=PP_ALIGN.LEFT)

    _add_textbox(slide, 0.6, 1.8, 8.8, 1.4,
                 "Monthly Health Report", font_size=36, bold=True,
                 color=COLORS["white"], align=PP_ALIGN.LEFT)

    _add_textbox(slide, 0.6, 3.1, 8.8, 0.6,
                 trends.report_month, font_size=22,
                 color=COLORS["light"], align=PP_ALIGN.LEFT)

    _add_textbox(slide, 0.6, 3.9, 8.8, 0.8,
                 synthesis.portfolio_headline, font_size=14,
                 color=COLORS["light"], align=PP_ALIGN.LEFT)

    _add_textbox(slide, 0.6, 6.1, 8.8, 0.5,
                 f"Prepared: {datetime.now().strftime('%B %d, %Y')}  |  "
                 f"Evidence-Based Health Agent v1.0",
                 font_size=10, color=COLORS["grey"])


def _slide_portfolio_snapshot(
    prs: Presentation, trends: TrendSummary
):
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["mid"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Portfolio Snapshot", font_size=22, bold=True,
                 color=COLORS["white"])
    _add_textbox(slide, 0.3, 0.55, 9.4, 0.3,
                 f"As of {trends.report_month}  |  {len(trends.projects)} active project(s)",
                 font_size=10, color=COLORS["grey"])

    # Donut chart (left half)
    donut_img = _make_donut_chart(trends.portfolio_rag_dist)
    slide.shapes.add_picture(donut_img, Inches(0.3), Inches(1.1),
                              Inches(4.0), Inches(3.8))

    # Project health grid (right half)
    grid_top = 1.2
    _add_textbox(slide, 4.7, grid_top - 0.1, 5.0, 0.35,
                 "Project Status", font_size=13, bold=True,
                 color=COLORS["dark"])
    row_h = 0.7
    for i, pt in enumerate(trends.projects):
        y = grid_top + 0.3 + i * row_h
        rag_color = _RAG_COLOR.get(pt.latest_rag, COLORS["grey"])
        _add_rect(slide, 4.7, y, 0.18, 0.35, rag_color)
        _add_textbox(slide, 5.0, y, 4.5, 0.35,
                     f"{pt.project_name[:38]}",
                     font_size=11, bold=True, color=COLORS["dark"])
        _add_textbox(slide, 5.0, y + 0.28, 4.5, 0.28,
                     f"Score: {pt.latest_score}/100  |  "
                     f"Stage: {pt.latest_stage}  |  "
                     f"Trend: {pt.trajectory}",
                     font_size=9, color=COLORS["grey"])

    # Overall trajectory callout
    traj_color = COLORS["green"] if trends.portfolio_trajectory == "Improving" \
        else COLORS["red"] if trends.portfolio_trajectory == "Deteriorating" \
        else COLORS["amber"]
    _add_rect(slide, 0.3, 5.2, 9.4, 0.65, COLORS["light"])
    _add_textbox(slide, 0.5, 5.3, 9.0, 0.45,
                 f"Portfolio Trajectory: {trends.portfolio_trajectory}",
                 font_size=13, bold=True, color=traj_color)


def _slide_schedule_velocity(prs: Presentation, trends: TrendSummary):
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["mid"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Schedule Velocity", font_size=22, bold=True,
                 color=COLORS["white"])
    _add_textbox(slide, 0.3, 0.55, 9.4, 0.3,
                 "Work completed vs timeline consumed per project",
                 font_size=10, color=COLORS["grey"])

    chart_img = _make_pace_chart(trends.projects)
    slide.shapes.add_picture(chart_img, Inches(0.4), Inches(1.1),
                              Inches(9.2), Inches(4.8))

    _add_textbox(slide, 0.4, 6.1, 9.2, 0.6,
                 "Projects below the 50% midline are behind pace and require attention.",
                 font_size=10, color=COLORS["grey"])


def _slide_root_causes(prs: Presentation, trends: TrendSummary):
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["mid"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Root Cause Analysis", font_size=22, bold=True,
                 color=COLORS["white"])
    _add_textbox(slide, 0.3, 0.55, 9.4, 0.3,
                 "Risk categories identified from project comments (LLM-classified)",
                 font_size=10, color=COLORS["grey"])

    chart_img = _make_risk_category_chart(trends.top_risk_categories)
    slide.shapes.add_picture(chart_img, Inches(0.4), Inches(1.1),
                              Inches(9.2), Inches(4.5))

    if trends.common_facts:
        _add_textbox(slide, 0.4, 5.85, 9.2, 0.3,
                     "Common pattern: " + trends.common_facts[0],
                     font_size=10, color=COLORS["grey"])


def _slide_emerging_risks(prs: Presentation,
                           trends: TrendSummary,
                           synthesis: ExecutiveSynthesis):
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["mid"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Emerging Risks & Trends", font_size=22, bold=True,
                 color=COLORS["white"])

    # Trend narrative
    _add_textbox(slide, 0.4, 1.05, 9.2, 1.4,
                 synthesis.trend_narrative, font_size=12,
                 color=COLORS["dark"])

    _add_rect(slide, 0.4, 2.6, 9.2, 0.04, COLORS["grey"])

    # Emerging risks list
    _add_textbox(slide, 0.4, 2.75, 9.2, 0.4,
                 "Emerging Risks This Period", font_size=13, bold=True,
                 color=COLORS["red"])
    _add_textbox(slide, 0.4, 3.2, 9.2, 1.4,
                 synthesis.emerging_risk_summary, font_size=12,
                 color=COLORS["dark"])

    if trends.emerging_risks:
        y = 4.75
        for risk in trends.emerging_risks[:3]:
            _add_rect(slide, 0.4, y, 0.12, 0.22, COLORS["red"])
            _add_textbox(slide, 0.65, y, 9.0, 0.28,
                         risk[:100], font_size=10, color=COLORS["dark"])
            y += 0.32


def _slide_recommendations(prs: Presentation, synthesis: ExecutiveSynthesis):
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["mid"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Portfolio Recommendations", font_size=22, bold=True,
                 color=COLORS["white"])
    _add_textbox(slide, 0.3, 0.55, 9.4, 0.3,
                 "Actions for the Portfolio Director and Delivery Leadership",
                 font_size=10, color=COLORS["grey"])

    recs = synthesis.portfolio_recommendations
    colors_cycle = [COLORS["red"], COLORS["amber"], COLORS["accent"]]
    y = 1.1
    for i, rec in enumerate(recs[:4]):
        c = colors_cycle[min(i, len(colors_cycle)-1)]
        _add_rect(slide, 0.4, y, 0.08, (0.55), c)
        num_box = slide.shapes.add_textbox(
            Inches(0.55), Inches(y), Inches(0.5), Inches(0.4)
        )
        num_tf = num_box.text_frame
        num_tf.paragraphs[0].runs
        run = num_tf.paragraphs[0].add_run()
        run.text = str(i + 1)
        run.font.size = Pt(16)
        run.font.bold = True
        run.font.color.rgb = c

        _add_textbox(slide, 1.1, y + 0.05, 8.5, 0.55,
                     rec, font_size=11, color=COLORS["dark"])
        y += 0.8

    _add_rect(slide, 0, 6.9, SLIDE_W, 0.6, COLORS["light"])
    _add_textbox(slide, 0.4, 6.95, 9.2, 0.45,
                 "Generated by Evidence-Based Project Health Agent  |  "
                 f"{datetime.now().strftime('%B %Y')}",
                 font_size=9, color=COLORS["grey"])


def _slide_appendix(prs: Presentation, trends: TrendSummary):
    """Appendix: per-project dimension breakdown."""
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)
    _add_rect(slide, 0, 0, SLIDE_W, 0.9, COLORS["dark"])
    _add_textbox(slide, 0.3, 0.15, 9.4, 0.6,
                 "Appendix — Project Detail", font_size=22, bold=True,
                 color=COLORS["white"])

    _add_textbox(slide, 0.4, 1.0, 9.2, 0.35,
                 "Latest score, trend and pace per project",
                 font_size=11, color=COLORS["grey"])

    col_headers = ["Project", "Overall", "Score", "Trend", "Pace gap", "Stage", "Confidence"]
    col_x       = [0.3, 2.9, 3.7, 4.4, 5.6, 6.5, 8.7]
    col_w       = [2.6, 0.8, 0.7, 1.2, 0.9, 2.2, 0.9]
    row_h       = 0.5

    # Header row
    _add_rect(slide, 0.3, 1.45, 9.4, 0.38, COLORS["accent"])
    for j, hdr in enumerate(col_headers):
        _add_textbox(slide, col_x[j], 1.48, col_w[j], 0.3,
                     hdr, font_size=9, bold=True, color=COLORS["white"])

    # Data rows — pull from latest report per project (from weekly_snapshots)
    # We only have TrendSummary here, so use latest_score and trajectory
    for i, pt in enumerate(trends.projects):
        y = 1.9 + i * row_h
        bg = COLORS["light"] if i % 2 == 0 else COLORS["white"]
        _add_rect(slide, 0.3, y, 9.4, row_h - 0.05, bg)

        rag_c = _RAG_COLOR.get(pt.latest_rag, COLORS["grey"])
        vals = [
            pt.project_name[:34],
            pt.latest_rag,
            f"{pt.latest_score}",
            pt.trajectory,
            f"{pt.pace_gap_history[-1]:+.0f}%" if pt.pace_gap_history else "—",
            (pt.latest_stage or "—")[:26],
            f"{pt.confidence_history[-1] if pt.confidence_history else '—'}%",
        ]
        for j, val in enumerate(vals):
            color = rag_c if j == 1 else COLORS["dark"]
            bold  = j == 1
            _add_textbox(slide, col_x[j], y + 0.08, col_w[j], 0.32,
                         val, font_size=9, bold=bold, color=color)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_presentation(
    trends:    TrendSummary,
    synthesis: ExecutiveSynthesis,
    output_path: Path,
) -> Path:
    prs = Presentation()
    prs.slide_width  = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    print("  Building slide 1/6: Cover")
    _slide_cover(prs, trends, synthesis)

    print("  Building slide 2/6: Portfolio Snapshot")
    _slide_portfolio_snapshot(prs, trends)

    print("  Building slide 3/6: Schedule Velocity")
    _slide_schedule_velocity(prs, trends)

    print("  Building slide 4/6: Root Cause Analysis")
    _slide_root_causes(prs, trends)

    print("  Building slide 5/6: Emerging Risks & Trends")
    _slide_emerging_risks(prs, trends, synthesis)

    print("  Building slide 6/6: Recommendations")
    _slide_recommendations(prs, synthesis)

    print("  Building appendix slide")
    _slide_appendix(prs, trends)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate monthly executive presentation"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .pptx path. Defaults to outputs/monthly/portfolio_YYYY-MM.pptx",
    )
    parser.add_argument(
        "--weekly-dir",
        default=str(WEEKLY_DIR),
        help="Directory containing weekly JSON reports",
    )
    args = parser.parse_args()

    weekly_dir = Path(args.weekly_dir)
    if not any(weekly_dir.glob("*.json")):
        print(f"[builder] No weekly reports found in {weekly_dir}")
        print("          Run agent.py first to generate weekly reports.")
        sys.exit(1)

    print("\n[builder] Loading weekly reports...")
    trends = compute_trends(weekly_dir)
    print(f"          {len(trends.data_sources)} report(s) loaded, "
          f"{len(trends.projects)} project(s)")

    print("[builder] Synthesizing executive narrative (Gemini)...")
    synthesis = synthesize(trends)

    month_slug = datetime.now().strftime("%Y-%m")
    out_path = Path(args.output) if args.output else MONTHLY_DIR / f"portfolio_{month_slug}.pptx"

    print(f"[builder] Building presentation → {out_path.name}")
    build_presentation(trends, synthesis, out_path)
    print(f"\n[builder] Done — {out_path}")


if __name__ == "__main__":
    main()

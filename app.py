"""
app.py  —  Streamlit UI for the Evidence-Based Project Health Agent.

Key changes from previous version:
  - One file can contain multiple projects (one per depth-0 row)
  - Phase breakdown table per project
  - Expandable task-level drill-down per phase
  - Portfolio tiles show counts across ALL projects from ALL files
  - PPTX built per file (covers all projects in that file)
  - History panel reads from report_archive.db
  - Gemini key is backend only (.env), never shown in UI

Run:
    python -m streamlit run app.py
"""
from __future__ import annotations
import io, json, os, sys, tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.agent import run_file
from agent.report import ProjectReport, render_markdown, report_to_dict, save_report_json
from database import get_all_reports, get_daily_metrics, get_project_names, get_reports_for_project

WEEKLY_DIR  = ROOT / "outputs" / "weekly"
MONTHLY_DIR = ROOT / "outputs" / "monthly"
_LLM_AVAILABLE = bool(os.getenv("GEMINI_API_KEY", "").strip())

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Project Health Agent",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.health-card {
    border-radius:12px; padding:18px 20px;
    margin-bottom:10px; border-left:7px solid;
}
.card-Red   { background:#fff5f5; border-color:#C0392B; }
.card-Amber { background:#fffbf0; border-color:#E67E22; }
.card-Green { background:#f0fff4; border-color:#27AE60; }
.card-grey  { background:#f8f9fa; border-color:#95A5A6; }
.big-score  { font-size:46px; font-weight:800; line-height:1; }
.score-Red   { color:#C0392B; }
.score-Amber { color:#E67E22; }
.score-Green { color:#27AE60; }
.conf-bar-bg { background:#e9ecef; border-radius:8px; height:10px; width:100%; margin-top:6px; }
.dim-pill { display:inline-block; border-radius:20px; padding:3px 12px;
            font-weight:600; font-size:12px; margin-top:4px; }
.pill-Red   { background:#fde8e8; color:#C0392B; }
.pill-Amber { background:#fef3e2; color:#E67E22; }
.pill-Green { background:#e6f9ee; color:#27AE60; }
.rec-card { background:#f8f9fa; border-radius:8px; padding:10px 14px;
            margin-bottom:8px; border-left:4px solid; }
.rec-High   { border-color:#C0392B; }
.rec-Medium { border-color:#E67E22; }
.section-title { font-size:15px; font-weight:700; color:#1a1a2e;
    margin-top:20px; margin-bottom:6px; padding-bottom:4px;
    border-bottom:2px solid #e9ecef; }
footer { visibility:hidden; }
#MainMenu { visibility:hidden; }
[data-testid="collapsedControl"] { display:none; }
</style>
""", unsafe_allow_html=True)

# ── Constants ───────────────────────────────────────────────────────────────
_RAG_HEX   = {"Red":"#C0392B","Amber":"#E67E22","Green":"#27AE60"}
_RAG_ICON  = {"Red":"🔴","Amber":"🟡","Green":"🟢"}
_RAG_CARD  = {"Red":"card-Red","Amber":"card-Amber","Green":"card-Green"}
_RAG_SCORE = {"Red":"score-Red","Amber":"score-Amber","Green":"score-Green"}
_RAG_PILL  = {"Red":"pill-Red","Amber":"pill-Amber","Green":"pill-Green"}

def _icon(rag:str)->str: return _RAG_ICON.get(rag,"⚪")
def _conf_color(s:int)->str:
    return "#27AE60" if s>=70 else "#E67E22" if s>=50 else "#C0392B"

def _sparkline_svg(scores:list, rag:str, w=100, h=28)->str:
    if len(scores)<2: return ""
    n=len(scores)
    xs=[int(i/(n-1)*w) for i in range(n)]
    ys=[int((1-s/100)*h) for s in scores]
    pts=" ".join(f"{x},{y}" for x,y in zip(xs,ys))
    c=_RAG_HEX.get(rag,"#95A5A6")
    dots="".join(f'<circle cx="{x}" cy="{y}" r="2.5" fill="{c}"/>'
                 for x,y in zip(xs,ys))
    return (f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{pts}" fill="none" stroke="{c}" '
            f'stroke-width="2" stroke-linejoin="round"/>{dots}</svg>')

def _scores_for_project(project_name:str)->list:
    return [r["overall_score"] for r in get_daily_metrics(project_name)]


def _generate_plain_reasoning(report: ProjectReport) -> str:
    """Generate plain-English explanation of WHY the project got its RAG status."""
    reasons = []
    
    # Overall status
    if report.overall_rag == "Green":
        reasons.append(f"✅ **Overall Status: Green** — The project scored **{report.overall_score}/100**, indicating healthy progress across all dimensions.")
    elif report.overall_rag == "Amber":
        reasons.append(f"⚠️ **Overall Status: Amber** — The project scored **{report.overall_score}/100**, indicating moderate concerns that need attention.")
    else:
        reasons.append(f"🚨 **Overall Status: Red** — The project scored **{report.overall_score}/100**, indicating significant issues requiring immediate intervention.")
    
    # Phase-level reasoning
    if report.phases:
        red_phases = [p for p in report.phases if p.rag == "Red"]
        amber_phases = [p for p in report.phases if p.rag == "Amber"]
        green_phases = [p for p in report.phases if p.rag == "Green"]
        
        reasons.append(f"\n**Phase Breakdown:** Of {len(report.phases)} phases:")
        reasons.append(f"• {len(green_phases)} are Green (performing well)")
        if amber_phases:
            reasons.append(f"• {len(amber_phases)} are Amber (showing warning signs): {', '.join(p.name for p in amber_phases[:3])}")
        if red_phases:
            reasons.append(f"• {len(red_phases)} are Red (require immediate attention): {', '.join(p.name for p in red_phases[:3])}")
    
    # Task distribution
    total = report.total_tasks
    if total > 0:
        reasons.append(f"\n**Task Distribution:**")
        reasons.append(f"• {report.green_tasks}/{total} tasks are Green ({report.green_tasks/total*100:.0f}%)")
        if report.amber_tasks > 0:
            reasons.append(f"• {report.amber_tasks}/{total} tasks are Amber ({report.amber_tasks/total*100:.0f}%)")
        if report.red_tasks > 0:
            reasons.append(f"• {report.red_tasks}/{total} tasks are Red ({report.red_tasks/total*100:.0f}%) — **These require immediate attention**")
    
    # Schedule pace
    if report.pct_time_elapsed > 0:
        reasons.append(f"\n**Schedule Pace:**")
        if report.pace_gap > 15:
            reasons.append(f"• Work is **{report.pace_gap:.1f}% ahead of schedule** — {report.pct_complete:.0f}% done with {report.pct_time_elapsed:.0f}% of time elapsed.")
        elif report.pace_gap < -15:
            reasons.append(f"• Work is **{abs(report.pace_gap):.1f}% behind schedule** — Only {report.pct_complete:.0f}% done with {report.pct_time_elapsed:.0f}% of time already elapsed.")
        else:
            reasons.append(f"• Project is **on pace** — {report.pct_complete:.0f}% done with {report.pct_time_elapsed:.0f}% of time elapsed.")
    
    # Status recommendation
    if report.overall_rag == "Green":
        reasons.append(f"\n**Status:** Project is on track. Continue monitoring for any changes in phase health.")
    elif report.overall_rag == "Amber":
        reasons.append(f"\n**Status:** Project needs attention. Focus on bringing Amber phases back to Green.")
    else:
        reasons.append(f"\n**Status:** Project is at risk. Immediate action required on Red phases.")
    
    # Data confidence
    if report.confidence < 70:
        reasons.append(f"\n⚠️ **Data Quality Note:** Confidence is {report.confidence}% — {report.confidence_note}")
    
    return "\n".join(reasons)


# ── PPTX builder (per file, covers all projects in that file) ──────────────
def _build_pptx_for_file(reports: list[ProjectReport]) -> bytes | None:
    try:
        from aggregator.synthesizer import synthesize
        from aggregator.trends import compute_trends
        from presentation.builder import build_presentation
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for r in reports:
                save_report_json(r, tmp)
            trends    = compute_trends(tmp)
            synthesis = synthesize(trends)
            out       = tmp / "presentation.pptx"
            build_presentation(trends, synthesis, out)
            return out.read_bytes()
    except Exception as e:
        st.warning(f"PPTX generation failed: {e}")
        return None

# ── Header ──────────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:2px'>🏥 Project Health Agent</h1>"
    "<p style='color:#666;font-size:15px;margin-top:0'>"
    "Evidence-based RAG — scoring engine decides, AI explains.</p>",
    unsafe_allow_html=True,
)
if _LLM_AVAILABLE:
    st.success("✅  AI narrative enabled — Gemini connected")
else:
    st.warning("⚠️  Offline mode. Add GEMINI_API_KEY to .env for narrative & recommendations.")
st.divider()

# ── Clear cache button for development ───────────────────────────────────────
if st.button("🔄 Clear Cache and Refresh", help="Clear cached results and reset the app"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ── Navigation ───────────────────────────────────────────────────────────────
nav = st.radio("nav", ["📤  Upload","📊  Analysis"],
               horizontal=True, label_visibility="collapsed")
st.markdown("<br>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS PANEL (renamed from History)
# ═══════════════════════════════════════════════════════════════════════════
if nav == "📊  Analysis":
    st.markdown("### Past Reports")
    names = get_project_names()
    if not names:
        st.info("No past reports found. Run an analysis first.")
        st.stop()

    sel = st.selectbox("Select project", names)
    daily = get_daily_metrics(sel)
    if len(daily) >= 2:
        scores = [r["overall_score"] for r in daily]
        latest_rag = daily[-1]["overall_rag"]
        st.markdown("**Score trajectory:**")
        st.markdown(_sparkline_svg(scores, latest_rag, w=300, h=50),
                    unsafe_allow_html=True)
        cols = st.columns(min(len(scores),6))
        for col, row in zip(cols, daily):
            col.metric(row["as_of"], f"{row['overall_score']}")

    st.markdown("<br>", unsafe_allow_html=True)
    proj_reports = list(reversed(get_reports_for_project(sel)))
    if not proj_reports:
        st.info("No reports for this project.")
        st.stop()

    labels = [f"{r['as_of']}  —  {r['overall_rag']}  ({r['overall_score']}/100)"
              for r in proj_reports]
    chosen = proj_reports[st.selectbox("Select report", range(len(labels)),
                                       format_func=lambda i: labels[i])]
    full = chosen.get("_full", {})
    st.divider()
    rag = chosen["overall_rag"]
    st.markdown(f"""
    <div class="health-card {_RAG_CARD.get(rag,'card-grey')}">
        <div class="big-score {_RAG_SCORE.get(rag,'')}">
            {_icon(rag)} {chosen['overall_score']}
        </div>
        <div style="font-weight:600;font-size:15px;margin-top:4px">{rag}</div>
        <div style="font-size:12px;color:#888">Confidence: {chosen['confidence']}%</div>
    </div>""", unsafe_allow_html=True)

    phases = full.get("phases", [])
    if phases:
        st.markdown('<div class="section-title">Phase Breakdown</div>',
                    unsafe_allow_html=True)
        rows = []
        for ph in phases:
            rows.append({"Phase": ph["name"], "Score": ph["score"],
                         "RAG": ph["rag"], "Tasks": ph["task_count"],
                         "🔴": ph["red_tasks"], "🟡": ph["amber_tasks"],
                         "🟢": ph["green_tasks"]})
        st.dataframe(rows, use_container_width=True)

    narrative = full.get("narrative","")
    if narrative:
        st.markdown('<div class="section-title">Narrative</div>',
                    unsafe_allow_html=True)
        st.info(narrative)

    st.download_button("⬇ Download JSON", data=chosen.get("full_report_json","{}"),
                       file_name=f"{sel[:30]}_{chosen['as_of']}.json",
                       mime="application/json")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD PANEL (renamed from Analyse)
# ═══════════════════════════════════════════════════════════════════════════
st.markdown("### 📂 Upload Project Plan Files")
st.caption("Upload one or more .xlsx, .xls, or .csv files. "
           "Each file is parsed automatically — multiple projects per file are supported.")

uploaded_files = st.file_uploader(
    "Drop files here or click to browse",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True,
)

if uploaded_files:
    chip_cols = st.columns(min(len(uploaded_files),4))
    for col, f in zip(chip_cols, uploaded_files):
        with col:
            st.markdown(
                f"<div style='background:#e8f4fd;border-radius:8px;"
                f"padding:8px 12px;font-size:13px;color:#1a5fa8'>📄 {f.name}</div>",
                unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
run_btn = st.button("▶  Run Analysis", type="primary", disabled=not uploaded_files)

if not uploaded_files and not st.session_state.get("results"):
    st.stop()

# ── Run pipeline ─────────────────────────────────────────────────────────────
if run_btn and uploaded_files:
    st.session_state["results"]    = []
    st.session_state["pptx_map"]   = {}   # {filename: pptx_bytes}
    st.session_state["overrides"]  = {}

    bar = st.progress(0, text="Starting…")
    all_reports: list[ProjectReport] = []
    # Group reports by source file for per-file PPTX
    file_reports: dict[str, list[ProjectReport]] = {}

    for i, uf in enumerate(uploaded_files):
        bar.progress(int(i/len(uploaded_files)*75),
                     text=f"Processing {uf.name}…")
        with tempfile.NamedTemporaryFile(
                suffix=Path(uf.name).suffix, delete=False) as tmp:
            tmp.write(uf.getbuffer())
            tmp_path = Path(tmp.name)
        try:
            reports = run_file(tmp_path, use_llm=_LLM_AVAILABLE)
            for r in reports:
                r.source_file = uf.name   # keep display name
            all_reports.extend(reports)
            file_reports[uf.name] = reports
        except Exception as e:
            st.error(f"❌  Could not process **{uf.name}**: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)

    # Build one PPTX per uploaded file
    pptx_map: dict[str, bytes] = {}
    for fname, reps in file_reports.items():
        bar.progress(80, text=f"Building PPTX for {fname}…")
        pptx_bytes = _build_pptx_for_file(reps)
        if pptx_bytes:
            pptx_map[fname] = pptx_bytes

    bar.progress(100, text="Done!")
    bar.empty()
    st.session_state["results"]  = all_reports
    st.session_state["pptx_map"] = pptx_map

# ── Results ───────────────────────────────────────────────────────────────────
results: list[ProjectReport] = st.session_state.get("results", [])
if not results:
    st.stop()

st.divider()
st.markdown("## Results")
st.caption(f"Analysis run · {datetime.now().strftime('%d %b %Y, %H:%M')}")

# ── Portfolio overview tiles ──────────────────────────────────────────────────
rag_counts   = {"Green":0, "Amber":0, "Red":0}
rag_projects = {"Green":[], "Amber":[], "Red":[]}
for r in results:
    rag = r.overall_rag
    if rag in rag_counts:
        rag_counts[rag] += 1
        
        # Generate concise summary
        phase_summary = ""
        if r.phases:
            red_phases = sum(1 for p in r.phases if p.rag == "Red")
            amber_phases = sum(1 for p in r.phases if p.rag == "Amber")
            total_phases = len(r.phases)
            
            if red_phases > 0 or amber_phases > 0:
                phase_summary = f" ({total_phases} phases: {red_phases} Red, {amber_phases} Amber)"
        
        rag_projects[rag].append(
            f"{r.project_name} — {r.overall_score}/100 (confidence: {r.confidence}%){phase_summary}")

tile_cfg = [
    ("Green","#27AE60","#f0fff4","🟢"),
    ("Amber","#E67E22","#fffbf0","🟡"),
    ("Red","#C0392B","#fff5f5","🔴"),
]
tile_cols = st.columns(3)
for col,(status,border,bg,icon) in zip(tile_cols, tile_cfg):
    count = rag_counts[status]
    projs = rag_projects[status]
    with col:
        st.markdown(f"""
        <div style="border-radius:12px;padding:20px 24px;background:{bg};
             border-left:7px solid {border};margin-bottom:8px">
            <div style="font-size:13px;font-weight:600;color:#555">{icon} {status}</div>
            <div style="font-size:52px;font-weight:800;color:{border};
                 line-height:1.1">{count}</div>
            <div style="font-size:12px;color:#888;margin-top:4px">
                project{"s" if count!=1 else ""}
            </div>
        </div>""", unsafe_allow_html=True)
        if projs:
            with st.expander(f"View {status} projects"):
                st.caption("Click on project tabs below to see detailed analysis with plain-English reasoning")
                for p in projs:
                    st.markdown(f"• {p}")

st.divider()

# ── Per-project tabs ──────────────────────────────────────────────────────────
st.markdown("### 📑 Project Details")
st.caption("Click on a project tab below to view detailed analysis with plain-English reasoning")
tabs = st.tabs([r.project_name[:35] for r in results]) \
       if len(results) > 1 else [st.container()]

for tab, report in zip(tabs, results):
  with tab:
    rag = report.overall_rag

    # Override banner
    overrides = st.session_state.get("overrides", {})
    override  = overrides.get(report.project_name)
    if override:
        st.markdown(
            f'<div style="border-radius:8px;padding:10px 16px;margin:8px 0;'
            f'border-left:5px solid #8E44AD;background:#f9f0ff;'
            f'font-size:13px;color:#5b2c8d">'
            f'⚠️ <strong>Override Active:</strong> System scored '
            f'<strong>{rag}</strong> ({report.overall_score}/100) — '
            f'overridden to <strong>{override["rag"]}</strong> '
            f'by {override["user"]} on {override["timestamp"]}.<br>'
            f'Reason: "{override["reason"]}"</div>',
            unsafe_allow_html=True)

    # Header row
    h1, h2 = st.columns([3,1])
    with h1:
        st.markdown(f"### {report.project_name}")
        st.caption(f"**PM:** {report.project_manager}  |  "
                   f"**Stage:** {report.project_stage}  |  "
                   f"**As of:** {report.as_of}  |  "
                   f"**Source:** {report.source_file}")
    with h2:
        pptx_map = st.session_state.get("pptx_map", {})
        pptx = pptx_map.get(report.source_file)
        if pptx:
            safe = "".join(c if c.isalnum() else "_"
                           for c in report.project_name[:40]).strip("_")
            st.download_button("⬇ Download PPTX", data=pptx,
                file_name=f"{safe}_{datetime.now().strftime('%B_%Y')}.pptx",
                mime="application/vnd.openxmlformats-officedocument"
                     ".presentationml.presentation",
                use_container_width=True, type="primary")

    st.divider()

    # ── Score card ───────────────────────────────────────────────────────────
    card_col1, card_col2 = st.columns([2,3])
    with card_col1:
        st.markdown(f"""
        <div class="health-card {_RAG_CARD.get(rag,'card-grey')}">
            <div class="big-score {_RAG_SCORE.get(rag,'')}">
                {_icon(rag)} {report.overall_score}
            </div>
            <div style="font-weight:600;font-size:18px;margin-top:8px">{rag}</div>
            <div style="font-size:13px;color:#888;margin-top:4px">
                Confidence: {report.confidence}%
            </div>
            <div class="conf-bar-bg">
                <div style="height:100%;width:{report.confidence}%;
                     background:{_conf_color(report.confidence)};
                     border-radius:8px;transition:width 0.3s"></div>
            </div>
        </div>""", unsafe_allow_html=True)
        
        if report.confidence_note:
            st.caption(f"⚠️ {report.confidence_note}")

    with card_col2:
        st.markdown('<div class="section-title">Phase Summary</div>',
                    unsafe_allow_html=True)
        # Display phase distribution instead of dimensions
        if report.phases:
            phase_rag_counts = {"Green": 0, "Amber": 0, "Red": 0}
            for phase in report.phases:
                phase_rag_counts[phase.rag] = phase_rag_counts.get(phase.rag, 0) + 1
            
            total_phases = len(report.phases)
            st.markdown(f"""
                <div style="font-size:13px;line-height:1.6;color:#1a1a2e">
                    • {phase_rag_counts['Green']} Green phases<br>
                    • {phase_rag_counts['Amber']} Amber phases<br>
                    • {phase_rag_counts['Red']} Red phases<br>
                    <strong>Total: {total_phases} phases</strong>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Plain-English Reasoning (DETERMINISTIC - always available) ────────────
    st.markdown('<div class="section-title">📋 Why This Status?</div>',
                unsafe_allow_html=True)
    reasoning = _generate_plain_reasoning(report)
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e9ecef;
         border-radius:8px;padding:16px 20px;margin-bottom:16px">
        <div style="font-size:13px;line-height:1.8;color:#1a1a2e">
            {reasoning}
        </div>
    </div>""", unsafe_allow_html=True)

    # ── LLM Narrative (PROMINENT DISPLAY) ────────────────────────────────────
    if report.narrative:
        st.markdown('<div class="section-title">📝 AI Analysis Explanation</div>',
                    unsafe_allow_html=True)
        st.markdown(f"""
        <div style="background:#f8f9fa;border-left:5px solid #0F3A6E;
             border-radius:8px;padding:18px 20px;margin-bottom:16px">
            <div style="font-size:14px;line-height:1.6;color:#1a1a2e">
                {report.narrative}
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.info("💡 AI-generated narrative not available (Gemini API quota exhausted). The plain-English reasoning above explains the status.")

    # ── Phase breakdown ───────────────────────────────────────────────────────
    if report.phases:
        st.markdown('<div class="section-title">Phase Breakdown</div>',
                    unsafe_allow_html=True)
        phase_rows = []
        for ph in report.phases:
            phase_rows.append({
                "Phase": ph.name[:50],
                "RAG": f"{_icon(ph.rag)} {ph.rag}",
                "Score": f"{ph.score}/100",
                "Tasks": ph.task_count,
                "🔴": ph.red_tasks,
                "🟡": ph.amber_tasks,
                "🟢": ph.green_tasks,
            })
        st.dataframe(phase_rows, use_container_width=True, hide_index=True)

        # Drill-down into phase tasks
        with st.expander("🔍 Task-level drill-down"):
            phase_names = [ph.name for ph in report.phases]
            sel_phase = st.selectbox("Select phase", phase_names, key=f"phase_{report.project_name}")
            phase_obj = next((p for p in report.phases if p.name==sel_phase), None)
            if phase_obj and phase_obj.tasks:
                task_rows = []
                for t in phase_obj.tasks:
                    task_rows.append({
                        "Task": t.name[:60],
                        "RAG": f"{_icon(t.rag)} {t.rag}",
                        "Score": f"{t.score}/100",
                        "% Done": f"{t.pct_complete}%",
                        "Baseline": t.baseline or "—",
                        "Start": t.start or "—",
                        "Finish": t.finish or "—",
                    })
                st.dataframe(task_rows, use_container_width=True, hide_index=True)

    # ── Recommendations ───────────────────────────────────────────────────────
    if report.recommendations:
        st.markdown('<div class="section-title">Recommendations</div>',
                    unsafe_allow_html=True)
        for rec in report.recommendations:
            priority = rec.get("priority", "Medium")
            st.markdown(f"""
            <div class="rec-card rec-{priority}">
                <div style="font-weight:700;font-size:13px;color:#1a1a2e;margin-bottom:4px">
                    {rec.get("risk", "Risk not specified")}
                </div>
                <div style="font-size:12px;color:#555">
                    <strong>Action:</strong> {rec.get("action", "—")}
                </div>
                <div style="font-size:11px;color:#888;margin-top:4px">
                    Priority: {priority}  |  Owner: {rec.get("owner", "TBD")}
                </div>
            </div>""", unsafe_allow_html=True)

    # ── Observed facts ────────────────────────────────────────────────────────
    if report.observed_facts:
        with st.expander("📋 Observed Facts (Evidence)"):
            for i, fact in enumerate(report.observed_facts, 1):
                st.markdown(f"{i}. {fact}")

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        report_dict = report_to_dict(report)
        json_str = json.dumps(report_dict, indent=2, ensure_ascii=False)
        st.download_button(
            "⬇ Download JSON Report",
            data=json_str,
            file_name=f"{report.project_name[:40]}_{report.as_of}.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl_col2:
        md_content = render_markdown(report)
        st.download_button(
            "⬇ Download Markdown Report",
            data=md_content,
            file_name=f"{report.project_name[:40]}_{report.as_of}.md",
            mime="text/markdown",
            use_container_width=True,
        )

# ═══════════════════════════════════════════════════════════════════════════
# PAST REPORTS SECTION (moved to Analysis page)
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## 📊 Past Reports")
st.caption("View historical analysis across all projects")

names = get_project_names()
if names:
    sel_project = st.selectbox("Select project for history", names, key="past_reports_selector")
    daily = get_daily_metrics(sel_project)
    
    if len(daily) >= 2:
        scores = [r["overall_score"] for r in daily]
        latest_rag = daily[-1]["overall_rag"]
        st.markdown("**Score trajectory:**")
        st.markdown(_sparkline_svg(scores, latest_rag, w=400, h=60),
                    unsafe_allow_html=True)
        cols = st.columns(min(len(scores),7))
        for col, row in zip(cols, daily):
            col.metric(row["as_of"], f"{row['overall_score']}")

    st.markdown("<br>", unsafe_allow_html=True)
    proj_reports = list(reversed(get_reports_for_project(sel_project)))
    if proj_reports:
        labels = [f"{r['as_of']}  —  {r['overall_rag']}  ({r['overall_score']}/100)"
                  for r in proj_reports]
        chosen = proj_reports[st.selectbox("Select report", range(len(labels)),
                                           format_func=lambda i: labels[i],
                                           key="past_report_choice")]
        full = chosen.get("_full", {})
        
        with st.expander("View detailed report"):
            rag = chosen["overall_rag"]
            st.markdown(f"""
            <div class="health-card {_RAG_CARD.get(rag,'card-grey')}">
                <div class="big-score {_RAG_SCORE.get(rag,'')}">
                    {_icon(rag)} {chosen['overall_score']}
                </div>
                <div style="font-weight:600;font-size:15px;margin-top:4px">{rag}</div>
                <div style="font-size:12px;color:#888">Confidence: {chosen['confidence']}%</div>
            </div>""", unsafe_allow_html=True)

            phases = full.get("phases", [])
            if phases:
                st.markdown('<div class="section-title">Phase Breakdown</div>',
                            unsafe_allow_html=True)
                rows = []
                for ph in phases:
                    rows.append({"Phase": ph["name"], "Score": ph["score"],
                                 "RAG": ph["rag"], "Tasks": ph["task_count"],
                                 "🔴": ph["red_tasks"], "🟡": ph["amber_tasks"],
                                 "🟢": ph["green_tasks"]})
                st.dataframe(rows, use_container_width=True, hide_index=True)

            narrative = full.get("narrative","")
            if narrative:
                st.markdown('<div class="section-title">AI Narrative</div>',
                            unsafe_allow_html=True)
                st.info(narrative)

            st.download_button("⬇ Download Historical JSON", 
                               data=chosen.get("full_report_json","{}"),
                               file_name=f"{sel_project[:30]}_{chosen['as_of']}.json",
                               mime="application/json")
else:
    st.info("No past reports available yet. Run an analysis first to build history.")

"""
synthesizer.py
--------------
Uses Gemini to generate executive-level narrative from the TrendSummary.

Produces slide copy for the monthly presentation:
    - Portfolio headline (1 sentence)
    - Trend narrative (2-3 sentences, insight-driven not summary)
    - Top 3 portfolio-level recommendations

Falls back to templated copy if Gemini is unavailable.
"""

from __future__ import annotations

import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from aggregator.trends import TrendSummary
from agent.llm_layer import _call_gemini


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class ExecutiveSynthesis:
    portfolio_headline:    str
    trend_narrative:       str
    emerging_risk_summary: str
    portfolio_recommendations: list[str]
    llm_available:         bool


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def synthesize(trends: TrendSummary) -> ExecutiveSynthesis:
    """
    Generate executive slide copy from portfolio trend data.
    LLM is used for insight-driven language; falls back gracefully.
    """
    # Build a structured context block for the LLM
    rag_dist_str = ", ".join(
        f"{rag}: {cnt}" for rag, cnt in trends.portfolio_rag_dist.items()
    )
    risk_cats_str = ", ".join(
        f"{r['category']} ({r['count']})" for r in trends.top_risk_categories[:4]
    )
    project_lines = "\n".join(
        f"  - {pt.project_name}: {pt.latest_rag} ({pt.latest_score}/100), "
        f"Stage={pt.latest_stage}, Trajectory={pt.trajectory}"
        for pt in trends.projects
    )
    emerging_str = "\n".join(f"  - {r}" for r in trends.emerging_risks[:4]) \
                   or "  - None identified"

    # ── Portfolio headline ──
    headline_prompt = textwrap.dedent(f"""
        You are writing an executive presentation for a VP of Professional Services
        presenting to a client. Write ONE sentence (max 20 words) that captures
        the overall portfolio health status for {trends.report_month}.

        Portfolio status:
        - Project distribution: {rag_dist_str}
        - Overall trajectory: {trends.portfolio_trajectory}
        - Projects:
        {project_lines}

        The sentence must be specific, factual, and executive-level.
        No bullet points. No preamble. Just the sentence.
    """).strip()

    headline = _call_gemini(headline_prompt) or _fallback_headline(trends)

    # ── Trend narrative ──
    narrative_prompt = textwrap.dedent(f"""
        Write 3 sentences for an executive slide on portfolio health trends.

        Data:
        - Month: {trends.report_month}
        - Distribution: {rag_dist_str}
        - Trajectory: {trends.portfolio_trajectory}
        - Top risk categories across projects: {risk_cats_str}
        - Projects: {project_lines}

        Requirements:
        - Focus on TRENDS and PATTERNS, not individual project summaries
        - Highlight what is improving, what is at risk, and why
        - Use executive language (concise, specific, confident)
        - Do NOT list projects one by one
        - No bullet points. Three connected sentences.
    """).strip()

    narrative = _call_gemini(narrative_prompt) or _fallback_narrative(trends)

    # ── Emerging risks ──
    risk_prompt = textwrap.dedent(f"""
        Write 2 sentences identifying emerging portfolio risks for a VP audience.

        Emerging risk signals this period:
        {emerging_str}

        Top risk categories: {risk_cats_str}

        Be specific about WHAT the risk is and WHY it matters to delivery.
        No bullet points. Two sentences maximum.
    """).strip()

    risk_summary = _call_gemini(risk_prompt) or _fallback_risks(trends)

    # ── Portfolio recommendations ──
    recs_prompt = textwrap.dedent(f"""
        Write 3 portfolio-level recommendations for a VP of Professional Services.

        Context:
        - Portfolio status: {rag_dist_str}
        - Top risks: {risk_cats_str}
        - Projects and trajectories:
        {project_lines}

        Each recommendation must:
        - Address a cross-project pattern (not one project's issue)
        - Specify an owner (e.g. Portfolio Director, Delivery Leads, PMO)
        - Include a timeframe
        - Be actionable, not vague

        Format as a JSON array of strings, one recommendation per string.
        Respond with ONLY the JSON array.
    """).strip()

    recs_raw = _call_gemini(recs_prompt, expect_json=True)
    portfolio_recs: list[str] = []
    if recs_raw:
        import json, re
        recs_raw = re.sub(r"^```(?:json)?\s*", "", recs_raw)
        recs_raw = re.sub(r"\s*```$", "", recs_raw)
        try:
            parsed = json.loads(recs_raw)
            if isinstance(parsed, list):
                portfolio_recs = [str(r) for r in parsed[:3]]
        except Exception:
            pass

    if not portfolio_recs:
        portfolio_recs = _fallback_recs(trends)

    return ExecutiveSynthesis(
        portfolio_headline         = headline,
        trend_narrative            = narrative,
        emerging_risk_summary      = risk_summary,
        portfolio_recommendations  = portfolio_recs,
        llm_available              = bool(os.getenv("GEMINI_API_KEY")),
    )


# ---------------------------------------------------------------------------
# Fallback copy (no LLM)
# ---------------------------------------------------------------------------

def _fallback_headline(t: TrendSummary) -> str:
    reds   = t.portfolio_rag_dist.get("Red", 0)
    greens = t.portfolio_rag_dist.get("Green", 0)
    total  = sum(t.portfolio_rag_dist.values())
    return (
        f"{t.report_month} portfolio: {greens}/{total} projects Green, "
        f"{reds}/{total} Red — overall trajectory is {t.portfolio_trajectory}."
    )


def _fallback_narrative(t: TrendSummary) -> str:
    cats = ", ".join(r["category"] for r in t.top_risk_categories[:3])
    return (
        f"The portfolio entered {t.report_month} with a {t.portfolio_trajectory} "
        f"trajectory across {len(t.projects)} active projects. "
        f"The dominant risk themes are {cats or 'under analysis'}. "
        f"Projects in later delivery phases show higher schedule exposure than those "
        f"in earlier configuration stages."
    )


def _fallback_risks(t: TrendSummary) -> str:
    risks = "; ".join(t.emerging_risks[:2]) if t.emerging_risks else "none identified"
    return (
        f"Emerging risks this period include: {risks}. "
        f"These patterns warrant escalation before the next milestone cycle."
    )


def _fallback_recs(t: TrendSummary) -> list[str]:
    return [
        "Portfolio Director to review all Red-status projects weekly until resolved.",
        "Delivery Leads to address vendor and client dependency blockers before next milestone.",
        "PMO to conduct a data quality audit on project plans with missing baseline dates.",
    ]

"""
llm_layer.py
------------
Layer 3a — LLM integration. Explanation and sentiment only.

The LLM has exactly three jobs in this system:

    1. classify_comment_sentiment()
       Called BEFORE scoring. Takes raw comment text for a task and
       returns "Positive", "Neutral", or "Negative". This feeds into
       the sentiment indicator in scorer.py.

    2. explain_scored_node()
       Called AFTER scoring. Receives a ScoredNode fact block and
       writes a plain-English explanation of why the score is what
       it is. The LLM is explicitly told the score and RAG are final.

    3. generate_recommendations()
       Called AFTER scoring at project level. Receives top risk signals
       and returns specific, actionable recommendations.

The LLM NEVER:
    - Assigns a score
    - Assigns a RAG colour
    - Changes or overrides any fact from the ScoredNode

All Gemini API calls are isolated here. If GEMINI_API_KEY is not set or
the API fails, every function returns a graceful fallback so the
pipeline continues without LLM output.
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Gemini client (lazy init)
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from google import genai
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                return None
            _client = genai.Client(api_key=api_key)
        except ImportError:
            return None
    return _client


MODEL_NAME = "gemini-2.0-flash"


def _call_gemini(prompt: str, expect_json: bool = False) -> str | None:
    """Send a prompt to Gemini. Returns text or None on failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = response.text.strip()
        if expect_json:
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text
    except Exception as e:
        print(f"[llm_layer] Gemini call failed: {e}")
        return None


def _parse_json(text: str | None) -> dict | list | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class SentimentResult:
    """Sentiment classification for one task's comments."""
    node_index:  int
    label:       str              # "Positive" | "Neutral" | "Negative"
    confidence:  str              # "High" | "Medium" | "Low"
    reason:      str              # one-line justification


@dataclass
class NodeExplanation:
    """Plain-English explanation for one ScoredNode."""
    narrative:          str       # 2-4 sentences explaining the score
    sentiment_note:     str       # explicit note when sentiment unavailable
    llm_available:      bool


@dataclass
class ProjectLLMOutput:
    """All LLM outputs for one project."""
    project_name:       str
    project_narrative:  str       # 3-4 sentences on overall project health
    recommendations:    list[dict]
    # {risk, action, priority, linked_phase}
    llm_available:      bool
    fallback_reason:    str = ""


# ---------------------------------------------------------------------------
# 1. Sentiment classification (PRE-SCORING)
# ---------------------------------------------------------------------------

def classify_comment_sentiment(
    comments_by_node: dict[int, list[str]],
) -> dict[int, SentimentResult]:
    """
    Classify sentiment for each node that has comments.

    Args:
        comments_by_node: {node_index: [comment_text, ...]}
                          Built by tree_builder.map_comments_to_nodes()

    Returns:
        {node_index: SentimentResult}

    Called BEFORE score_tree(). The results are passed as comment_map
    to score_tree() so the sentiment indicator can use them.
    """
    if not comments_by_node:
        return {}

    results: dict[int, SentimentResult] = {}

    # Build a batch prompt — classify all comments in one API call
    items = []
    for idx, texts in comments_by_node.items():
        combined = " | ".join(texts[:3])  # cap at 3 comments per task
        items.append({"index": idx, "text": combined})

    if not items:
        return {}

    numbered = "\n".join(
        f'{i+1}. [node_index={item["index"]}] {item["text"]}'
        for i, item in enumerate(items)
    )

    prompt = textwrap.dedent(f"""
        You are a project risk analyst reviewing comments from a project
        management system.

        Classify each comment as exactly one of:
            "Positive"  — progress confirmed, issue resolved, on track
            "Neutral"   — factual update, no clear positive or negative signal
            "Negative"  — blocker, delay, dependency issue, incomplete work

        Comments to classify:
        {numbered}

        Respond with a JSON array. Each element must have:
        {{
            "node_index": <integer from the comment>,
            "label": "Positive" | "Neutral" | "Negative",
            "confidence": "High" | "Medium" | "Low",
            "reason": "<one short phrase>"
        }}

        Respond with ONLY the JSON array. No other text.
    """).strip()

    raw = _call_gemini(prompt, expect_json=True)
    parsed = _parse_json(raw)

    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            idx = item.get("node_index")
            if idx is None:
                continue
            results[int(idx)] = SentimentResult(
                node_index = int(idx),
                label      = str(item.get("label", "Neutral")),
                confidence = str(item.get("confidence", "Low")),
                reason     = str(item.get("reason", "")),
            )

    # Fill in any missing nodes with fallback
    for idx in comments_by_node:
        if idx not in results:
            results[idx] = SentimentResult(
                node_index = idx,
                label      = "Neutral",
                confidence = "Low",
                reason     = "Could not classify — using neutral fallback",
            )

    return results


def build_comment_map(
    sentiment_results: dict[int, SentimentResult],
) -> dict[int, str | None]:
    """
    Convert SentimentResult dict into the simple {node_index: label}
    map that scorer.score_tree() expects.
    """
    return {idx: sr.label for idx, sr in sentiment_results.items()}


# ---------------------------------------------------------------------------
# 2. Node explanation (POST-SCORING)
# ---------------------------------------------------------------------------

def explain_scored_node(scored_node: Any) -> NodeExplanation:
    """
    Generate a plain-English explanation for a single ScoredNode.

    The LLM receives the full fact block and is told:
    "The score and RAG are final. Explain them — do not change them."

    Args:
        scored_node: ScoredNode from scorer.py

    Returns:
        NodeExplanation with narrative text
    """
    # Build fact summary for the prompt
    facts = _build_fact_summary(scored_node)
    sentiment_note = ""

    if not scored_node.sentiment_available:
        sentiment_note = (
            "No stakeholder comments were available for this task. "
            "Sentiment was excluded from the health calculation."
        )

    prompt = textwrap.dedent(f"""
        You are a project health analyst writing a status report.

        The scoring engine has already determined the following facts.
        Your job is to explain them in plain business English.
        DO NOT change the score or RAG. DO NOT add information not
        present in the facts below.

        Task / Phase: {scored_node.name}
        Health Score: {scored_node.score}/100
        RAG Status:   {scored_node.rag}

        Scoring facts:
        {facts}

        {"Sentiment note: " + sentiment_note if sentiment_note else ""}

        Write 2-4 sentences explaining WHY this task received this score.
        Be specific — reference the actual facts above.
        Use professional, plain English. No bullet points. No preamble.
        {"End with: '" + sentiment_note + "'" if sentiment_note else ""}
    """).strip()

    narrative = _call_gemini(prompt)

    if not narrative:
        # Fallback: build narrative from reason codes
        narrative = _fallback_narrative(scored_node, sentiment_note)

    return NodeExplanation(
        narrative      = narrative,
        sentiment_note = sentiment_note,
        llm_available  = _get_client() is not None,
    )


def _build_fact_summary(node: Any) -> str:
    """Convert ScoredNode fields into a readable fact list for the LLM."""
    lines = []

    lines.append(f"- Completion: {node.pct_complete*100:.0f}%")
    lines.append(f"- Schedule health flag: {node.schedule_health}")

    if node.overdue_days and node.overdue_days > 0:
        lines.append(f"- Overdue by: {node.overdue_days} days")
    elif node.end_date:
        lines.append(f"- Due date: {node.end_date.strftime('%d %b %Y')} (not yet overdue)")

    if node.is_on_hold:
        lines.append("- Status: On Hold (blocked)")
    if node.is_at_risk:
        lines.append("- Explicitly flagged: At Risk")
    if node.is_critical:
        lines.append("- On critical path: Yes")
    if not node.has_owner:
        lines.append("- Owner: Not assigned")

    if node.milestone_health:
        lines.append(f"- Containing phase status: {node.milestone_health}")

    # Indicator scores
    if hasattr(node, "indicator_scores") and node.indicator_scores:
        lines.append("- Indicator scores:")
        for k, v in node.indicator_scores.items():
            if v is not None:
                lines.append(f"    {k}: {v:.0f}/100")
            else:
                lines.append(f"    {k}: not available")

    if node.sentiment_available and node.sentiment_label:
        lines.append(f"- Stakeholder sentiment: {node.sentiment_label}")

    if node.reason_codes:
        lines.append(f"- Machine reason codes: {', '.join(node.reason_codes)}")

    return "\n".join(lines)


def _fallback_narrative(node: Any, sentiment_note: str) -> str:
    """Build a rule-based narrative when LLM is unavailable."""
    parts = []

    if node.rag == "Green":
        parts.append(
            f"{node.name} is in good health with a score of {node.score}/100."
        )
    elif node.rag == "Amber":
        parts.append(
            f"{node.name} requires attention — score of {node.score}/100 "
            f"indicates moderate risk."
        )
    else:
        parts.append(
            f"{node.name} is at high risk with a score of {node.score}/100."
        )

    for code in node.reason_codes[:3]:
        if "overdue" in code:
            days = re.search(r"\d+", code)
            parts.append(
                f"The task is {days.group()}d overdue."
                if days else "The task is overdue."
            )
        elif code == "on_hold":
            parts.append("Work is currently blocked (On Hold).")
        elif code == "at_risk":
            parts.append("The task is explicitly flagged as At Risk.")
        elif code == "no_owner":
            parts.append("No owner has been assigned.")

    if sentiment_note:
        parts.append(sentiment_note)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# 3. Project-level narrative and recommendations (POST-SCORING)
# ---------------------------------------------------------------------------

def generate_project_output(
    project_name:    str,
    overall_score:   float,
    overall_rag:     str,
    scored_roots:    list[Any],     # list[ScoredNode]
    observed_facts:  list[str],
    project_stage:   str,
) -> ProjectLLMOutput:
    """
    Generate project-level narrative and recommendations.

    Receives the fully scored tree — never decides RAG.
    """
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return _fallback_project_output(
            project_name, overall_score, overall_rag,
            scored_roots, "GEMINI_API_KEY not set"
        )

    # Build context from top Red/Amber phases
    phase_summary = []
    for root in scored_roots:
        if root.rag in ("Red", "Amber"):
            phase_summary.append(
                f"  - {root.name}: {root.rag} ({root.score}/100) "
                f"— {', '.join(root.reason_codes[:2]) or 'see detail'}"
            )

    phase_str = "\n".join(phase_summary[:6]) or "  - No Red/Amber phases"
    facts_str = "\n".join(f"  - {f}" for f in observed_facts[:8])

    # ── Project narrative ──
    narrative_prompt = textwrap.dedent(f"""
        You are a senior project delivery analyst writing an executive
        status summary.

        Project: {project_name}
        Stage: {project_stage}
        Overall Health: {overall_rag} (score: {overall_score}/100)

        The score and RAG are already determined. Do NOT change them.

        At-risk phases:
        {phase_str}

        Observed facts:
        {facts_str}

        Write 3-4 sentences explaining the project's current health.
        Be specific about what is driving the status.
        Use executive language — concise, factual, no jargon.
        Do not start with "The project".
        No bullet points.
    """).strip()

    narrative = _call_gemini(narrative_prompt) or _fallback_project_narrative(
        project_name, overall_score, overall_rag, scored_roots
    )

    # ── Recommendations ──
    red_amber_roots = [r for r in scored_roots if r.rag in ("Red", "Amber")]
    top_risks = []
    for root in red_amber_roots[:5]:
        codes = ", ".join(root.reason_codes[:2]) or root.rag
        top_risks.append(f"{root.name} ({root.rag}): {codes}")

    risks_str = "\n".join(f"  - {r}" for r in top_risks) or "  - None identified"

    rec_prompt = textwrap.dedent(f"""
        You are a project delivery consultant advising a VP of Professional Services.

        Project: {project_name}
        Stage: {project_stage}
        Overall Status: {overall_rag}

        Top risk signals:
        {risks_str}

        Generate 2-4 specific, actionable recommendations.
        Each must:
        - Target a SPECIFIC risk signal above
        - Name an owner (PM / Client / Vendor / Steering Committee)
        - Include a timeframe (this week / before next milestone / by sprint end)
        - Not be generic advice like "monitor closely"

        Return a JSON array only. Each element:
        {{
            "risk": "<specific risk>",
            "action": "<concrete action with owner and timeframe>",
            "priority": "High" or "Medium",
            "linked_phase": "<phase name or null>"
        }}
    """).strip()

    raw  = _call_gemini(rec_prompt, expect_json=True)
    recs = _parse_json(raw)

    if not isinstance(recs, list) or not recs:
        recs = _fallback_recommendations(project_name, overall_rag, red_amber_roots)
    else:
        clean = []
        for r in recs:
            if isinstance(r, dict) and "risk" in r and "action" in r:
                clean.append({
                    "risk":         str(r.get("risk", "")),
                    "action":       str(r.get("action", "")),
                    "priority":     str(r.get("priority", "Medium")),
                    "linked_phase": r.get("linked_phase"),
                })
        recs = clean if clean else _fallback_recommendations(
            project_name, overall_rag, red_amber_roots
        )

    return ProjectLLMOutput(
        project_name      = project_name,
        project_narrative = narrative,
        recommendations   = recs,
        llm_available     = True,
    )


def _fallback_project_narrative(
    name: str, score: float, rag: str, roots: list
) -> str:
    """Generate detailed plain-English reasoning when LLM is unavailable."""
    
    # Overall status
    if rag == "Green":
        status_intro = f"✅ **{name}** is classified as **Green** with a score of **{score}/100**, indicating healthy progress across most dimensions."
    elif rag == "Amber":
        status_intro = f"⚠️ **{name}** is classified as **Amber** with a score of **{score}/100**, indicating moderate concerns that require attention."
    else:
        status_intro = f"🚨 **{name}** is classified as **Red** with a score of **{score}/100**, indicating significant issues requiring immediate intervention."
    
    # Phase breakdown
    red_phases = [r for r in roots if r.rag == "Red"]
    amber_phases = [r for r in roots if r.rag == "Amber"]
    green_phases = [r for r in roots if r.rag == "Green"]
    total_phases = len(roots)
    
    phase_summary = f"\n\n**Phase Breakdown:** Of {total_phases} phases:"
    if len(green_phases) > 0:
        phase_summary += f"\n• {len(green_phases)} are Green (performing well)"
    if len(amber_phases) > 0:
        phase_summary += f"\n• {len(amber_phases)} are Amber (showing warning signs): {', '.join([p.name[:40] for p in amber_phases])}"
    if len(red_phases) > 0:
        phase_summary += f"\n• {len(red_phases)} are Red (require immediate attention): {', '.join([p.name[:40] for p in red_phases])}"
    
    # Key issues
    issues = []
    for phase in red_phases[:2]:  # Top 2 red phases
        reasons = []
        if phase.overdue_days and phase.overdue_days > 0:
            reasons.append(f"{phase.overdue_days} days overdue")
        if hasattr(phase, 'indicator_scores'):
            low_indicators = [k for k, v in phase.indicator_scores.items() if v is not None and v < 60]
            if low_indicators:
                reasons.append(f"low scores in {', '.join(low_indicators)}")
        if reasons:
            issues.append(f"• **{phase.name}**: {', '.join(reasons)}")
    
    for phase in amber_phases[:2]:  # Top 2 amber phases
        reasons = []
        if phase.overdue_days and phase.overdue_days > 0:
            reasons.append(f"{phase.overdue_days} days overdue")
        if hasattr(phase, 'indicator_scores'):
            med_indicators = [k for k, v in phase.indicator_scores.items() if v is not None and 60 <= v < 80]
            if med_indicators:
                reasons.append(f"moderate scores in {', '.join(med_indicators)}")
        if reasons:
            issues.append(f"• **{phase.name}**: {', '.join(reasons)}")
    
    issue_detail = ""
    if issues:
        issue_detail = "\n\n**Key Issues:**\n" + "\n".join(issues)
    
    # Recommendation
    if rag == "Red":
        recommendation = "\n\n**Immediate Action Required:** Review the Red phases listed above, escalate blockers, and establish recovery plans."
    elif rag == "Amber":
        recommendation = "\n\n**Recommended Action:** Monitor the Amber phases closely and address warning signs before they escalate to Red."
    else:
        recommendation = "\n\n**Status:** Project is on track. Continue monitoring for any changes in phase health."
    
    return status_intro + phase_summary + issue_detail + recommendation



def _fallback_recommendations(
    name: str, rag: str, red_amber: list
) -> list[dict]:
    recs = []
    for r in red_amber[:2]:
        recs.append({
            "risk":         f"{r.name} is {r.rag}",
            "action":       f"PM to review {r.name} and escalate blockers this week.",
            "priority":     "High" if r.rag == "Red" else "Medium",
            "linked_phase": r.name,
        })
    if not recs:
        recs.append({
            "risk":         f"{name} overall health",
            "action":       "PM to review all at-risk phases before next steering committee.",
            "priority":     "High" if rag == "Red" else "Medium",
            "linked_phase": None,
        })
    return recs


def _fallback_project_output(
    name: str, score: float, rag: str,
    roots: list, reason: str
) -> ProjectLLMOutput:
    return ProjectLLMOutput(
        project_name      = name,
        project_narrative = _fallback_project_narrative(name, score, rag, roots),
        recommendations   = _fallback_recommendations(
            name, rag, [r for r in roots if r.rag in ("Red", "Amber")]
        ),
        llm_available     = False,
        fallback_reason   = reason,
    )

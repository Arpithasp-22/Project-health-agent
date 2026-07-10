# RAG Methodology — Evidence-Based Project Health Framework

**Version:** 1.0  
**Author:** Project Health Agent  
**Purpose:** Phase 1 deliverable — defines how RAG status is determined

---

## Philosophy

This framework is **evidence-based**, not opinion-based. Every RAG
classification is produced by a deterministic scoring engine from structured
data. The LLM is used only to explain the output — never to produce it.

This means:

> "Why is this project Red?"  
> → "The scoring engine assigned a score of 31/100. Schedule is 19% behind
>    pace, 8 critical tasks are Red, and 6 In Progress tasks have passed
>    their end dates."

Not: "GPT said so."

---

## RAG Definition

| Status | Score Range | Meaning |
|--------|-------------|---------|
| 🟢 Green | 65–100 | Delivery is broadly on track. Minor issues exist but are manageable. |
| 🟡 Amber | 40–64  | Meaningful risk present. Requires active management and escalation if unresolved within one sprint. |
| 🔴 Red   | 0–39   | Significant risk to delivery. Immediate intervention required. |

---

## Four Health Dimensions

Each dimension is scored 0–100 independently, then combined into an overall
score using documented weights.

---

### 1. Schedule Health (weight: 35%)

The most predictive indicator of delivery risk.

| Signal | Measurement | Penalty |
|--------|-------------|---------|
| Pace gap | (% work done) − (% timeline elapsed). Each 1% behind = −1.2 pts | Max −40 |
| Red task density | % of active tasks flagged Red. Each 1% = −0.6 pts | Max −30 |
| Amber task density | % of active tasks flagged Yellow. Each 1% = −0.25 pts | Max −10 |
| Critical path reds | Each critical task that is Red = −3 pts | Max −20 |

**Assumption:** % complete and task-level schedule health flags are set
accurately by the PM in the project plan.

---

### 2. Execution Health (weight: 30%)

Reflects the team's actual throughput vs plan.

| Signal | Measurement | Penalty |
|--------|-------------|---------|
| Overdue In Progress | Tasks past end date, not complete. Each = −2.5 pts | Max −35 |
| Late to start | Not-started tasks whose start date passed. Each = −1.5 pts | Max −25 |
| On Hold tasks | Blocked work. Each = −3 pts | Max −15 |
| Critical overdue | Each critical overdue task = extra −4 pts | Max −20 |

---

### 3. Milestone Health (weight: 20%)

Stakeholder-visible progress markers (phase/milestone rows at depth 0–1
in the task hierarchy).

| Signal | Measurement | Penalty |
|--------|-------------|---------|
| Overdue milestones | Past end date, not complete. Each = −8 pts | Max −40 |
| Red milestones | Each = −6 pts | Max −30 |
| Amber milestones | Each = −3 pts | Max −15 |

---

### 4. Blocker Health (weight: 15%)

Operational friction that is most visible in comments and flags.

| Signal | Measurement | Penalty |
|--------|-------------|---------|
| At Risk flags | Each explicitly flagged task = −4 pts | Max −25 |
| On Hold tasks | Each = −3 pts | Max −20 |
| Critical on hold | Each = extra −5 pts | Max −20 |
| Unassigned active tasks | Each = −0.5 pts | Max −15 |
| Project-level High Risk | −10 pts (flat) | — |

---

## Overall Score Aggregation

```
Overall Score = (Schedule × 0.35) + (Execution × 0.30)
              + (Milestones × 0.20) + (Blockers × 0.15)
```

All dimension scores are clamped to [0, 100] before aggregation.

---

## Confidence Score

The confidence score (0–100%) reflects **data completeness**, not
analytical certainty. A classification at 60% confidence means some signals
were absent — the score is based on what was available.

| Missing Data | Confidence Deduction |
|---|---|
| Budget data | −15% (never present in these files) |
| No project comments | −10% |
| Baseline dates missing for >50% of tasks | −12% |
| Schedule variance field unparseable | −8% |
| High unparseable cell ratio (>10%) | −8% |
| No project end date | −10% |
| No project start date | −5% |
| >30% of active tasks have no owner | −5% |

**Floor:** 20% (even minimal data gives some signal)

---

## Role of the LLM

Gemini is invoked **after** the deterministic scoring is complete. It does
three tasks:

1. **Comment categorisation** — classifies each raw project comment into
   a risk category (Vendor Dependency, Client Dependency, Technical Risk,
   Data Quality, Scope Change, Resource/Capacity, Integration Risk, Resolved)

2. **Narrative generation** — writes 3–4 sentences explaining the already-
   determined RAG status. It is explicitly instructed not to re-classify.

3. **Recommendations** — generates 2–4 actionable recommendations, each
   linked to a specific risk signal with an owner and timeframe.

The LLM receives: project name, overall RAG, per-dimension scores, and the
list of observed facts. It does not have access to the raw task data.

---

## Assumptions

1. **Date accuracy:** Start, end, and baseline dates in the project plan
   are set and maintained by the PM. Stale dates will skew execution scores.

2. **Schedule health flags:** The Red/Yellow/Green flags at task level are
   set by the PM's project management tool (Asana / SmartSheet / similar)
   and exported to Excel. We treat them as ground truth.

3. **No budget data:** Budget burn is not present in these files. This is
   tracked as a −15% confidence deduction and an explicit gap in reporting.

4. **'Today' reference:** Each file's Summary sheet contains a "Today's Date"
   field. All time-elapsed calculations use this date for consistency,
   ensuring reports are reproducible at any point in time.

5. **Critical flag:** The "Critical?" column identifies critical-path tasks.
   If this column is empty (all False), critical-path penalties are zero —
   this is flagged in the report but does not invalidate the classification.

---

## Limitations

- Stakeholder sentiment is inferred from comments only. Direct stakeholder
  surveys would significantly improve this dimension.
- Budget health cannot be assessed without financial data.
- The scoring weights are calibrated for Zycus S2P implementation projects.
  Different project types may require retuning.

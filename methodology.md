# RAG Methodology

How a project's Red / Amber / Green status is produced. This document describes what `agent/scorer.py` and `agent/confidence.py` actually do.

## Principle

The status comes from a **deterministic scoring engine**. The LLM never produces or changes a score or a colour. It only writes the narrative, classifies comments and suggests actions, after scoring is finished.

> "Why is this project Red?"
> The engine scored it 51.2 / 100: 10 of 15 tasks are Red, and 27% of the work is done against 85.5% of the timeline elapsed.

## RAG bands

| Status | Score | Meaning |
| --- | --- | --- |
| Green | 80 to 100 | On track. |
| Amber | 60 to under 80 | Meaningful risk; needs active management. |
| Red | under 60 | Significant risk to delivery; intervene. |
| No Data | none | Header or summary row with no executable tasks beneath it. It is not scored. |

## Five indicators per task

Every leaf task gets five indicators, each 0 to 100:

| Indicator | Weight | How it is scored |
| --- | --- | --- |
| Schedule health | 35% | The plan's own flag: Green 100, Yellow or Amber 60, Red 20, Unknown 50. |
| Milestone health | 25% | Status of the task's nearest phase (parent) row. Completed 100; In Progress 70, or 30 if the phase end date has passed; Not Started 80, or 20 if overdue; On Hold 10; anything else 50. |
| Task progress | 20% | Actual % complete against the share of the task's time window already elapsed. On or ahead of schedule is 100; each 1% behind costs 1.5 points. Completed is 100. With no dates, % complete is used directly. A not-yet-started future task scores 90. |
| Blockers and risks | 10% | Starts at 100. On Hold sets it to 0. At Risk is -30. No owner is -20. A critical task past its end date is -40. |
| Stakeholder sentiment | 10% | From the LLM's reading of comments: Positive 100, Neutral 60, Negative 20. |

**Missing sentiment.** If a task has no comments, sentiment is dropped and the other four weights are rescaled to sum to 1 (35/25/20/10 become 38.9/27.8/22.2/11.1). With `--no-llm` there is no sentiment for any task.

## Rolling up

A phase or project score is the weighted average of its children, recursively. A critical child counts 1.5 times, any other child once. Task scores are never averaged with their parent's own status, so a long list of easy tasks can hide a few late critical ones; the report therefore also shows red-task counts per phase.

## Confidence

Confidence (0 to 100%) reports how complete the input data was. It is not a statement about how certain the analysis is. Each missing item deducts points from 100, with a floor of 20.

| Condition | Deduction |
| --- | --- |
| Budget data (never present in these files) | 15 |
| No comments in the file | 10 |
| More than 50% of tasks lack baseline dates | 12 |
| Summary schedule-variance field missing or unparseable | 8 |
| More than 10% of task cells unparseable | 8 |
| Project end date missing | 10 |
| Project start date missing | 5 |
| More than 30% of active tasks have no owner | 5 |

## Schedule pace

Shown on every report: percent of work done, percent of the project timeline elapsed, and the gap between them (negative means behind). "Today" is taken from the file's Summary sheet when present, so a report is reproducible for a given file.

## Role of the LLM (Gemini)

1. Classify each comment into a risk category and a sentiment label (this feeds the sentiment indicator).
2. Write a short narrative explaining the already-computed result.
3. Suggest actions tied to specific risk signals.

Without an API key, the engine still produces every score, RAG status and confidence value, with a templated narrative and recommendations.

## Assumptions

- Dates, % complete and the Red/Yellow/Green flags in the plan are set accurately by the project manager. The schedule indicator (35%) trusts that flag directly.
- The Critical column marks critical-path tasks. If it is empty, critical-path penalties are zero.
- The weights and thresholds are judgement calls tuned for software-implementation plans, not fitted to outcome data. Retune them for other project types.

## Limitations

- Budget and cost cannot be assessed from these files.
- Sentiment is inferred from comment text only.
- Task progress uses a straight-line expectation (work is spread evenly across the task's dates), which understates back-loaded tasks.
- Averaging can dilute a few severe tasks inside a large phase; read the red-task counts alongside the score.

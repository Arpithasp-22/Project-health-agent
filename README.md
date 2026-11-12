# Evidence-Based Project Health Agent

Turns a project plan exported to Excel into a Red / Amber / Green health report. A **deterministic scoring engine** decides the status; an LLM (Gemini, optional) only explains it. Every score traces back to specific rows in the plan, and every report states how complete the input data was.

Most "AI project health" tools ask a model what colour a project is. This one computes the colour from the data first, so the answer is reproducible and auditable, then has the model write it up.

## Sample output

The repo ships three **fictional** projects (`samples/`) chosen to land in different bands. Scored offline, as of 2 July 2026:

| Project | Score | Status | Work done vs timeline elapsed | Red tasks |
| --- | --- | --- | --- | --- |
| Orion Retail - S2P Implementation | 91.7 | Green | 44.6% vs 57.5% | 0 of 14 |
| Harbor Foods - Procure-to-Pay Rollout | 78.5 | Amber | 40.7% vs 72.5% | 5 of 15 |
| Summit Energy - Sourcing Rollout | 51.2 | Red | 27.0% vs 85.5% | 10 of 15 |

Look at `docs/sample_output/`: one Markdown and JSON report per project, plus `sample_portfolio.pptx`, the monthly executive deck.

## How it works

```
Excel / CSV plan
   -> parser.py        flat rows + Summary and Comments sheets (handles several projects per file)
   -> tree_builder.py  rebuilds the hierarchy from the depth column
   -> scorer.py        five indicators per task, weighted roll-up (no AI, no I/O)
   -> confidence.py    what data was missing, and how much that matters
   -> llm_layer.py     optional: classify comments, write narrative and actions
   -> report.py        JSON + Markdown report
   -> trends.py        portfolio trends across weeks
   -> builder.py       monthly PowerPoint deck
```

Each task is scored on schedule health, milestone health, task progress, blockers and stakeholder sentiment, then averaged up the tree, with critical tasks weighted 1.5x. Green is 80 and above, Amber 60 to 79, Red below 60. The full rules are in [`methodology.md`](methodology.md).

## Quickstart

```bash
pip install -r requirements.txt

python samples/make_sample_data.py                 # writes three sample workbooks
python agent/agent.py samples/*.xlsx --no-llm      # scores them offline, no API key needed
python presentation/builder.py                     # builds the monthly deck from outputs/weekly
streamlit run app.py                               # optional: the web UI
```

Reports are written to `outputs/weekly/` and each run is also logged to local SQLite files in `data/`. Both folders are git-ignored because they hold your own project information.

To use your own plan, point `agent.py` at an `.xlsx`, `.xls` or `.csv` file. Task columns it reads include Task Name, Status, % Complete, Start/End Date, Schedule Health, Critical, On Hold, At Risk, Assigned To and a depth column (Ancestors, Level or Outline Level). See `samples/make_sample_data.py` for a complete example of the layout.

### Optional: LLM narrative

```bash
cp .env.example .env     # then set GEMINI_API_KEY
python agent/agent.py "YourPlan.xlsx"
```

With a key, Gemini classifies comments into risk categories (which feeds the sentiment indicator), writes the narrative and suggests actions. It never changes a score or a colour. Without a key, scores, status and confidence are identical and the narrative falls back to a template.

### Weekly schedule

```bash
python scheduler/run_weekly.py --help
```

## Tests

```bash
pip install pytest
python -m pytest
```

The 15 tests cover the weights and thresholds, that the three sample projects land in Green, Amber and Red in the right order, that scoring is deterministic, the confidence bounds, and a regression test for the portfolio trend calculation.

## Project structure

```
agent/          parser, tree builder, scorer, confidence, LLM layer, report, orchestrator
aggregator/     cross-week trends and the executive synthesis
presentation/   monthly PowerPoint builder
scheduler/      weekly runner
samples/        generator for three fictional project plans
docs/           sample reports and deck
tests/
app.py          Streamlit UI
methodology.md  the scoring rules
```

## Limitations

- **The weights and thresholds are judgement calls.** They are documented and tunable but are not fitted to real project outcomes.
- **It trusts the plan.** The largest indicator (35%) is the project manager's own Red/Yellow/Green flag, so stale flags or dates produce stale scores.
- **No budget data.** Cost cannot be assessed, and every report loses 15 confidence points for it.
- **Averaging can hide a few severe tasks** inside a large phase, so read the red-task counts next to the score.
- **Offline mode is limited.** Without Gemini there is no sentiment indicator, no comment categories and only a templated narrative; the root-cause slide of the deck is empty.

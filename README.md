# Evidence-Based Project Health Agent

An AI-powered project health reporting system for Zycus S2P implementation
projects. Classifies projects as Red / Amber / Green using a **deterministic
scoring engine** — the LLM explains the result, it does not produce it.

---

## Design Philosophy

Most project health tools ask: "GPT, what colour is this project?"  
This system asks: "What does the data say?" — then has Gemini explain it.

```
Excel Input
    ↓
Data Parser         (structured extraction, handles both file formats)
    ↓
Scoring Engine      (4 dimensions, fully deterministic, no AI)
    ↓
Confidence Engine   (tracks missing data, reports uncertainty)
    ↓
LLM Layer           (Gemini: categorise comments, write narrative, recommend)
    ↓
Weekly Report       (JSON + Markdown, timestamped)
    ↓
Aggregator          (trends across projects and weeks)
    ↓
Presentation        (6-slide executive PowerPoint)
```

---

## Project Structure

```
health_agent/
├── agent/
│   ├── parser.py       # Excel → structured data
│   ├── scorer.py       # Deterministic 4-dimension scoring
│   ├── confidence.py   # Missing data tracker
│   ├── llm_layer.py    # Gemini integration
│   ├── report.py       # Weekly report builder
│   └── agent.py        # Main orchestrator (entry point)
├── scheduler/
│   └── run_weekly.py   # Weekly scheduler
├── aggregator/
│   ├── trends.py       # Cross-project trend analysis
│   └── synthesizer.py  # Gemini executive narrative
├── presentation/
│   └── builder.py      # PowerPoint generator
├── outputs/
│   ├── weekly/         # Timestamped JSON + Markdown reports
│   └── monthly/        # Executive .pptx files
├── methodology.md      # RAG framework documentation
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your Gemini API key

```bash
copy .env.example .env
```

Edit `.env` and add your key:

```
GEMINI_API_KEY=your_key_here
```

Get a free key at: https://aistudio.google.com/app/apikey

### 3. Place project files

Copy your `.xlsx` project plan files into the `health_agent/` folder, or use the Streamlit UI to upload them directly.

**Supported file formats:**
- Excel 2007+ (`.xlsx`)
- Excel 97-2003 (`.xls`)
- CSV (`.csv`)

**Note:** The sample files (`Project Plan B.xlsx` and `S2P Project.xlsx`) have been removed. You'll need to provide your own project plan files.

---

## Running the Agent

### Generate a weekly report (upload your own files)

Place your project plan files (`.xlsx`, `.xls`, or `.csv`) in the `health_agent/` folder, then run:

```bash
python agent/agent.py
```

Or analyze a specific file:

```bash
python agent/agent.py "YourProject.xlsx"
```

### Offline mode (no Gemini API, deterministic output only)

```bash
python agent/agent.py --no-llm
```

Reports are saved to `outputs/weekly/` as both `.json` and `.md`.

---

## Weekly Scheduler (Bonus Feature - Implemented)

The scheduler enables automated weekly project health reporting without manual intervention.

### Run once immediately (for testing)

```bash
python scheduler/run_weekly.py --now
```

### Start the weekly schedule (every Monday at 08:00)

```bash
python scheduler/run_weekly.py
```

### Change day/time

```bash
python scheduler/run_weekly.py --day friday --time 09:00
```

The scheduler logs all runs to `outputs/weekly/run_log.txt`.

**For production:** Use Windows Task Scheduler instead of the Python loop.  
Set the trigger to weekly on Monday, action: `python agent/agent.py`

---

## Monthly Presentation (Phase 3 - Implemented)

After running the agent at least once (weekly reports must exist), generate a 6-slide executive presentation:

```bash
python presentation/builder.py
```

Output: `outputs/monthly/portfolio_YYYY-MM.pptx`

Custom output path:

```bash
python presentation/builder.py --output my_report.pptx
```

The presentation includes:
- **Slide 1:** Cover with portfolio headline
- **Slide 2:** Portfolio Snapshot (RAG distribution + project health grid)
- **Slide 3:** Schedule Velocity (work done vs timeline elapsed)
- **Slide 4:** Root Cause Analysis (top risk categories from comments)
- **Slide 5:** Emerging Risks & Trends (insight-driven narrative)
- **Slide 6:** Portfolio Recommendations (executive-level actions)
- **Appendix:** Per-project dimension breakdown table

---

## Understanding the Output

### Weekly JSON report

```json
{
  "project_name": "Zycus - UniSan S2P Implementation",
  "overall_rag": "Red",
  "overall_score": 31.4,
  "confidence": 57,
  "confidence_note": "Budget data not available (-15%); ...",
  "dimensions": {
    "schedule":   {"rag": "Red",   "score": 22.0, "key_findings": [...]},
    "execution":  {"rag": "Red",   "score": 32.5, "key_findings": [...]},
    "milestones": {"rag": "Amber", "score": 52.0, "key_findings": [...]},
    "blockers":   {"rag": "Green", "score": 80.0, "key_findings": [...]}
  },
  "observed_facts": ["...deterministic facts..."],
  "narrative": "...Gemini explanation...",
  "recommendations": [{"risk": "...", "action": "...", "priority": "High"}]
}
```

### Answering "Why Red?"

> "The scoring engine assigned 31.4/100. Schedule scored 22 (Red): the project
> is 19% behind pace and has 8 critical Red tasks. Execution scored 32 (Red):
> 6 In Progress tasks are past their end date. The LLM narrative explains this
> in plain English in the report."

---

## Key Design Decisions

| Decision | Reason |
|----------|--------|
| Deterministic RAG scoring | Auditability — any classification can be reproduced and explained without LLM |
| Confidence score | Acknowledges data gaps instead of silently ignoring them |
| LLM role is explain, not decide | Interviewers can ask "why Amber?" and get a real answer |
| 4 independent dimensions | Like a medical report — shows WHERE the problem is, not just that one exists |
| Comment categorisation via LLM | Turns unstructured text into quantified risk signal |
| Fallback at every LLM call | Pipeline works fully offline; LLM adds value but isn't a dependency |

---

## Extending the System

- **Add budget data:** Add a `budget` column to the Excel; add a new dimension
  in `scorer.py`; update confidence deductions in `confidence.py`
- **New project files:** Drop any `.xlsx` with the same column structure into
  `health_agent/` — the parser resolves columns automatically
- **Different LLM:** All Gemini calls are in `llm_layer.py` — swap the
  `_call_gemini` function to use any API
- **Adjust scoring weights:** Edit `DIMENSION_WEIGHTS` in `scorer.py`
- **Adjust RAG thresholds:** Edit `RAG_GREEN_THRESHOLD` / `RAG_AMBER_THRESHOLD`
  in `scorer.py`

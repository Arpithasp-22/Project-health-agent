# 📊 Sample Weekly Outputs

This folder contains **sample weekly health reports** generated from real project plan data.

## 📁 What's Included

### **Project Reports (4 Projects)**

1. **Phase 1- S2C** (Green - 90.3/100)
   - `phase-1--s2c_2026-07-02.json`
   - `phase-1--s2c_2026-07-02.md`

2. **Phase 2- P2P** (Green - 88.8/100)
   - `phase-2---p2p_2026-07-02.json`
   - `phase-2---p2p_2026-07-02.md`

3. **Zycus - UniSan S2P Implementation** (Green - 92.7/100)
   - `zycus---unisan-s2p-implementation_2026-07-02.json`
   - `zycus---unisan-s2p-implementation_2026-07-02.md`
   - `zycus---unisan-s2p-implementation_2026-07-09.json`
   - `zycus---unisan-s2p-implementation_2026-07-09.md`
   - `zycus---unisan-s2p-implementation_2026-07-10.json` (latest)

4. **Zycus - Titan S2P Implementation** (Red - No Data)
   - `zycus---titan-s2p-implementation_2026-07-02.json`
   - `zycus---titan-s2p-implementation_2026-07-02.md`
   - `zycus---titan-s2p-implementation_2026-07-09.json`
   - `zycus---titan-s2p-implementation_2026-07-09.md`
   - `zycus---titan-s2p-implementation_2026-07-10.json` (latest)

**Total:** 14 report files (7 JSON + 7 Markdown)

---

## 📄 File Formats

### **JSON Format** (`.json`)
**Purpose:** Machine-readable structured data for programmatic access

**Contents:**
- Project metadata (name, PM, stage, date)
- Overall RAG status and score
- Confidence percentage and notes
- Dimension scores (schedule, execution, milestones, blockers)
- Complete phase breakdown
- Task-level details with RAG status
- Plain-English narrative
- Prioritized recommendations array
- Ignored metrics (data quality tracking)

**Use case:** 
- Feeding into dashboards
- API integrations
- Database storage
- Trend analysis

---

### **Markdown Format** (`.md`)
**Purpose:** Human-readable formatted report

**Contents:**
- Executive summary with overall RAG status
- Confidence score with data quality notes
- Schedule pace analysis (work done vs timeline)
- Phase breakdown table
- **Plain-English narrative** explaining WHY the project got its status
- Actionable recommendations with priority levels

**Use case:**
- Quick review by project managers
- Email attachments
- Converting to PDF
- Printing for meetings

---

## 🎯 Sample Report Structure

### Example: `phase-1--s2c_2026-07-02.md`

```markdown
# Weekly Health Report — Phase 1- S2C
**Date:** 2026-07-02  |  **PM:** Aftab Hashambhai

## 🟢 Overall Status: Green  (90.3/100)
**Confidence:** 72%

## Schedule Pace
- Work done: 92%  |  Timeline elapsed: 57%
- **35% ahead of pace**

## Phase Breakdown
| Phase | Score | Status | Tasks |
|-------|-------|--------|-------|
| Configuration and Build | 98.5 | 🟢 Green | 103 |
| Production & Cutover | 79.9 | 🟡 Amber | 17 |
| Hyper Care | 45.5 | 🔴 Red | 3 |

## Narrative (Plain-English Reasoning)
✅ Phase 1- S2C is classified as Green with a score of 90.3/100,
indicating healthy progress across most dimensions.

**Phase Breakdown:** Of 9 phases:
• 7 are Green (performing well)
• 1 are Amber (showing warning signs): Production & Cutover
• 1 are Red (require immediate attention): Hyper Care

**Status:** Project is on track. Continue monitoring for changes.

## Recommendations
1. [High] Review Hyper Care phase - escalate blockers
2. [Medium] Monitor Production & Cutover - address warnings
```

---

## 🔍 Key Features Demonstrated

### 1. **Evidence-Based Scoring**
Every RAG classification has a numeric score and detailed breakdown:
- Overall score (0-100)
- Per-phase scores
- Per-dimension scores
- Task-level scores

### 2. **Plain-English Reasoning**
Not just "Red" or "Green" — explains WHY:
- What dimensions are problematic
- Which phases need attention
- How tasks are distributed (Green/Amber/Red)
- Schedule pace vs baseline

### 3. **Confidence Scoring**
Acknowledges data quality issues:
```
Confidence: 42%
Note: "Budget data not available (-15%); 
       Schedule variance unparseable (-8%)"
```

### 4. **Handles Different Scenarios**

**Scenario 1: Healthy Project** (Phase 1- S2C)
- Green status with high score
- Most phases Green
- Few Red tasks needing attention

**Scenario 2: At-Risk Project** (Production & Cutover)
- Amber status
- Some warning signs
- Moderate recommendations

**Scenario 3: No Data** (Titan root node)
- Special "No Data" classification
- Indicates structural issue (no tasks)
- Not counted in portfolio statistics

---

## 📊 How These Were Generated

```bash
# Command used:
python agent/agent.py "S2P Project.xlsx"

# Output location:
outputs/weekly/

# Formats generated:
- JSON (structured data)
- Markdown (human-readable)
```

---

## 🎯 Demonstrates Assignment Requirements

✅ **"Sample weekly outputs for each project plan"**
- 4 different projects covered
- Multiple dates showing history/trends
- Both JSON and Markdown formats
- Real data from actual project plans

✅ **"Provides clear, plain-English reasoning"**
- Every report has detailed narrative
- Explains WHY project got its RAG status
- Not just colors — actual analysis

✅ **"Handles incomplete or messy data gracefully"**
- Confidence scores acknowledge gaps
- Notes which metrics are missing
- Continues analysis with available data
- "No Data" classification for edge cases

---

## 📖 How to View

**Markdown files** (`.md`):
- Open in any text editor (Notepad, VS Code, etc.)
- Or use Markdown viewer (Typora, MarkText)
- Or view on GitHub (auto-renders)

**JSON files** (`.json`):
- Open in text editor with JSON syntax highlighting
- Or use JSON viewer (jsonviewer.stack.hu)
- Or load programmatically in Python/JavaScript

---

## 💡 Next Steps

1. **Review sample reports** to understand output format
2. **Run agent on your own files** using `python agent/agent.py "YourFile.xlsx"`
3. **New reports will appear** in this folder with current date
4. **Use JSON for automation**, Markdown for human review

---

**Status:** ✅ All sample outputs included and documented

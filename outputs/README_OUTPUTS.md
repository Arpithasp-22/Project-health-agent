# 📊 Outputs Folder - Assignment Deliverables

This folder contains all the **sample outputs** required for the assignment submission.

---

## 📁 Folder Structure

```
outputs/
├── weekly/                          ← Sample Weekly Outputs
│   ├── README_WEEKLY_OUTPUTS.md    ← Documentation
│   ├── *.json                      ← Structured data (7 files)
│   ├── *.md                        ← Human-readable reports (7 files)
│   └── run_log.txt                 ← Execution log
│
└── monthly/                         ← Final Monthly Presentation
    ├── README_MONTHLY_PRESENTATION.md  ← Documentation
    └── portfolio_2026-07.pptx      ← 7-slide executive deck
```

---

## ✅ Deliverable 3: Sample Weekly Outputs

**Location:** `weekly/`

### **What's Included**

**4 different projects** with **14 report files total**:

1. **Phase 1- S2C** (Green - 90.3/100)
2. **Phase 2- P2P** (Green - 88.8/100)  
3. **Zycus - UniSan S2P** (Green - 92.7/100)
4. **Zycus - Titan S2P** (Red - No Data)

### **File Formats**

- **JSON** (`.json`) — Machine-readable structured data
- **Markdown** (`.md`) — Human-readable formatted reports

### **Contents of Each Report**

✅ Overall RAG status with score (e.g., Green 90.3/100)  
✅ Confidence level and data quality notes  
✅ Schedule pace analysis (work done vs timeline)  
✅ Phase breakdown table with RAG status  
✅ **Plain-English narrative** explaining WHY the status  
✅ Prioritized recommendations with action items  

### **Key Features Demonstrated**

- Evidence-based deterministic scoring
- Plain-English reasoning (always available)
- Confidence scoring (acknowledges data gaps)
- Handles multiple scenarios (Green/Amber/Red/No Data)
- Both structured and human-readable formats

📖 **Full documentation:** `weekly/README_WEEKLY_OUTPUTS.md`

---

## ✅ Deliverable 4: Final Monthly Presentation

**Location:** `monthly/portfolio_2026-07.pptx`

### **Presentation Details**

- **Format:** Microsoft PowerPoint
- **Slides:** 7 slides (within 5-7 requirement)
- **Status:** Executive-ready, minimal edits needed

### **Slide Breakdown**

1. **Cover** — Portfolio headline and reporting month
2. **Portfolio Snapshot** — RAG distribution + project grid
3. **Schedule Velocity** — Work vs timeline (bar chart)
4. **Root Cause Analysis** — Risk categories across projects
5. **Emerging Risks & Trends** — Portfolio insights (not summaries!)
6. **Recommendations** — Prioritized actions with owners
7. **Appendix** — Detailed dimension breakdown table

### **Phase 3 Requirements Met**

✅ Identifies trends across projects (not just summaries)  
✅ Highlights emerging risks (week-over-week analysis)  
✅ Provides executive-level insights and recommendations  
✅ 5-7 slides (has 7)  
✅ VP can present with minimal edits  

📖 **Full documentation:** `monthly/README_MONTHLY_PRESENTATION.md`

---

## 🎯 Quick Access

### **To Review Sample Weekly Reports**

```bash
# View human-readable format
notepad outputs/weekly/phase-1--s2c_2026-07-02.md

# View structured data
notepad outputs/weekly/phase-1--s2c_2026-07-02.json
```

### **To Open Monthly Presentation**

```bash
# Windows
start outputs/monthly/portfolio_2026-07.pptx

# Mac
open outputs/monthly/portfolio_2026-07.pptx

# Linux
libreoffice outputs/monthly/portfolio_2026-07.pptx
```

---

## 🔄 How These Were Generated

### **Weekly Reports**

```bash
# Command used:
python agent/agent.py "S2P Project.xlsx"

# Output generated in: outputs/weekly/
# Formats: JSON + Markdown for each project
```

### **Monthly Presentation**

```bash
# Command used:
python presentation/builder.py

# Output generated in: outputs/monthly/
# Aggregates all weekly reports → PowerPoint
```

---

## 📊 Coverage Summary

### **Project Plans Analyzed**

| Project Plan File | Projects Inside | Reports Generated |
|-------------------|-----------------|-------------------|
| S2P Project.xlsx | 3 (Titan, Phase 1, Phase 2) | 6 files |
| Project Plan B.xlsx | 1 (UniSan) | 8 files |
| **Total** | **4 projects** | **14 files** |

### **Scenarios Covered**

✅ **Healthy project** (Phase 1- S2C: Green 90.3)  
✅ **At-risk phases** (Production & Cutover: Amber 79.9)  
✅ **Critical issues** (Hyper Care: Red 45.5)  
✅ **No data** (Titan root: Red 0.0 - No Data)  
✅ **High confidence** (UniSan: 92.7 @ 42% confidence)  
✅ **Low confidence** (Titan: 0.0 @ 77% confidence)  

---

## 🎯 Demonstrates Assignment Requirements

### ✅ **"Sample weekly outputs for each project plan"**

- Multiple projects covered (4 total)
- Multiple dates showing history (3 dates: July 2, 9, 10)
- Both structured (JSON) and readable (Markdown) formats
- Real data from actual project plan files

### ✅ **"Provides clear, plain-English reasoning"**

Every report includes detailed narrative explaining:
- WHY the project got its RAG status
- Which dimensions/phases are problematic
- What the task distribution looks like
- Schedule pace vs baseline
- Specific recommendations with priorities

### ✅ **"Handles incomplete or messy data gracefully"**

Demonstrated through:
- Confidence scores acknowledging data gaps
- Notes about which columns are missing
- Continues analysis with available data
- "No Data" classification for edge cases

### ✅ **"Final monthly presentation (5–7 slides)"**

- 7 slides (within requirement)
- Identifies trends (not just project summaries)
- Highlights emerging risks
- Executive-level insights and recommendations
- VP-ready format

---

## 💡 For Reviewers

### **Start Here**

1. **Quick overview:** Read this file (you're here!)
2. **Sample weekly report:** Open `weekly/phase-1--s2c_2026-07-02.md`
3. **Monthly presentation:** Open `monthly/portfolio_2026-07.pptx`
4. **Detailed docs:**
   - `weekly/README_WEEKLY_OUTPUTS.md`
   - `monthly/README_MONTHLY_PRESENTATION.md`

### **What to Look For**

In **weekly reports**:
- Plain-English explanation of RAG status
- Detailed phase breakdown
- Confidence scoring
- Actionable recommendations

In **monthly presentation**:
- Cross-project trend analysis (not just summaries)
- Data-driven charts
- Executive-level insights
- Professional design

---

## 🚀 Regenerate Outputs

To create new outputs with your own data:

```bash
# Step 1: Analyze your project file
python agent/agent.py "YourProject.xlsx"

# Step 2: Generate monthly presentation
python presentation/builder.py

# New files will appear in:
# - outputs/weekly/*.json and *.md
# - outputs/monthly/portfolio_YYYY-MM.pptx
```

---

## ✨ Summary

**Weekly Outputs:** ✅ Complete (14 files, 4 projects, 2 formats)  
**Monthly Presentation:** ✅ Complete (7 slides, executive-ready)  
**Documentation:** ✅ Complete (3 README files)  

**All assignment deliverables ready for submission!** 🎉

---

**Last Updated:** July 10, 2026  
**Assignment:** Professional Services Project Health Reporting Agent  
**Status:** Ready for review

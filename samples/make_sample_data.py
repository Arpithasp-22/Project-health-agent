"""Generate fictional sample project plans for the Project Health Agent.

Everything here is invented: company names, people, tasks and dates. The
three projects are built to land in different health bands so the demo shows
the full range of the scoring engine:

    Orion Retail  - mostly on track          (expected: Green)
    Harbor Foods  - slipping in places       (expected: Amber)
    Summit Energy - late, blocked, unowned   (expected: Red)

Usage:
    python samples/make_sample_data.py          # writes samples/*.xlsx
"""
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl

OUT_DIR = Path(__file__).resolve().parent
TODAY = datetime(2026, 7, 2)  # fixed so reports are reproducible

TASK_HEADERS = [
    "Task Name", "Status", "% Complete", "Start Date", "End Date",
    "Baseline Start", "Baseline Finish", "Variance", "Schedule Health",
    "Critical ?", "On Hold?", "Not Applicable?", "At Risk?", "Ancestors",
    "Phase/Milestone", "Area", "Duration", "Total Float", "Status Comment",
    "Assigned To", "Priority",
]

# Task tuple: (name, status, pct, start_offset_days, end_offset_days, health, flags)
# Offsets are relative to TODAY. Flags: C=critical, H=on hold, R=at risk, N=no owner.
PROJECTS = [
    {
        "file": "Orion_Retail_S2P.xlsx",
        "name": "Orion Retail - S2P Implementation",
        "pm": "Alex Morgan",
        "start": datetime(2026, 3, 2),
        "end": datetime(2026, 9, 30),
        "stage": "Configuration and Build",
        "owners": ["Dana Lee", "Marcus Webb", "Sofia Alvarez"],
        "phases": [
            ("Discovery & Design", [
                ("Kick-off and governance setup", "Completed", 1.0, -120, -112, "Green", ""),
                ("Requirements workshops", "Completed", 1.0, -110, -85, "Green", "C"),
                ("Solution design sign-off", "Completed", 1.0, -84, -70, "Green", "C"),
            ]),
            ("Configuration & Build", [
                ("Supplier master data load", "Completed", 1.0, -68, -40, "Green", ""),
                ("Approval workflow configuration", "In Progress", 0.8, -45, 8, "Green", "C"),
                ("Catalog and punch-out setup", "In Progress", 0.6, -30, 14, "Green", ""),
                ("Invoice matching rules", "In Progress", 0.5, -20, 20, "Yellow", ""),
            ]),
            ("Integration & Testing", [
                ("ERP integration build", "In Progress", 0.35, -15, 30, "Green", "C"),
                ("Integration test cycle 1", "Not Started", 0.0, 28, 45, "Green", ""),
                ("User acceptance testing", "Not Started", 0.0, 50, 70, "Green", "C"),
            ]),
            ("Training & Cutover", [
                ("Training material preparation", "Not Started", 0.0, 40, 65, "Green", ""),
                ("Cutover rehearsal", "Not Started", 0.0, 75, 85, "Green", "C"),
            ]),
            ("Go-live & Hypercare", [
                ("Go-live", "Not Started", 0.0, 90, 90, "Green", "C"),
                ("Hypercare support", "Not Started", 0.0, 91, 120, "Green", ""),
            ]),
        ],
        "comments": [
            ("Approval workflow configuration", "Workshops went well and the client team is engaged and responsive.", "Alex Morgan", "2026-06-24"),
            ("Invoice matching rules", "Tolerance thresholds still being agreed with finance, small delay expected.", "Dana Lee", "2026-06-26"),
            ("ERP integration build", "Interface specs approved. Build progressing on plan.", "Marcus Webb", "2026-06-30"),
        ],
    },
    {
        "file": "Harbor_Foods_P2P.xlsx",
        "name": "Harbor Foods - Procure-to-Pay Rollout",
        "pm": "Priya Nair",
        "start": datetime(2026, 2, 2),
        "end": datetime(2026, 8, 28),
        "stage": "Integration and Testing",
        "owners": ["Ravi Shah", "Elena Petrova", "Tom Becker"],
        "phases": [
            ("Discovery & Design", [
                ("Kick-off and governance setup", "Completed", 1.0, -150, -142, "Green", ""),
                ("Requirements workshops", "Completed", 1.0, -140, -110, "Green", "C"),
                ("Solution design sign-off", "Completed", 1.0, -108, -92, "Yellow", "C"),
            ]),
            ("Configuration & Build", [
                ("Supplier master data load", "Completed", 1.0, -90, -60, "Green", ""),
                ("Approval workflow configuration", "In Progress", 0.85, -70, -5, "Red", "C"),
                ("Catalog and punch-out setup", "In Progress", 0.55, -50, -2, "Yellow", ""),
                ("Invoice matching rules", "In Progress", 0.4, -40, -1, "Red", "RN"),
                ("Purchase order templates", "Not Started", 0.0, -14, -1, "Yellow", ""),
            ]),
            ("Integration & Testing", [
                ("ERP integration build", "In Progress", 0.3, -25, 18, "Red", "C"),
                ("Integration test cycle 1", "Not Started", 0.0, 10, 30, "Yellow", ""),
                ("User acceptance testing", "Not Started", 0.0, 32, 52, "Green", "C"),
            ]),
            ("Training & Cutover", [
                ("Training material preparation", "Not Started", 0.0, 25, 50, "Green", "N"),
                ("Cutover rehearsal", "Not Started", 0.0, 55, 65, "Green", "C"),
            ]),
            ("Go-live & Hypercare", [
                ("Go-live", "Not Started", 0.0, 57, 57, "Green", "C"),
                ("Hypercare support", "Not Started", 0.0, 58, 85, "Green", ""),
            ]),
        ],
        "comments": [
            ("Invoice matching rules", "Business owner has not signed off the rules and the team is blocked waiting on a decision.", "Priya Nair", "2026-06-25"),
            ("Approval workflow configuration", "Good progress, but two approval levels were added late which affects the timeline.", "Ravi Shah", "2026-06-27"),
            ("ERP integration build", "Environment access delayed by a week, now resolved.", "Elena Petrova", "2026-06-30"),
        ],
    },
    {
        "file": "Summit_Energy_Sourcing.xlsx",
        "name": "Summit Energy - Sourcing Rollout",
        "pm": "Sam Carter",
        "start": datetime(2026, 1, 12),
        "end": datetime(2026, 7, 31),
        "stage": "Configuration and Build",
        "owners": ["Nina Okafor", "Luis Romero"],
        "phases": [
            ("Discovery & Design", [
                ("Kick-off and governance setup", "Completed", 1.0, -170, -162, "Green", ""),
                ("Requirements workshops", "Completed", 1.0, -160, -120, "Yellow", "C"),
                ("Solution design sign-off", "In Progress", 0.9, -118, -40, "Red", "CR"),
            ]),
            ("Configuration & Build", [
                ("Supplier master data load", "In Progress", 0.6, -100, -30, "Red", "CN"),
                ("Sourcing event templates", "In Progress", 0.3, -80, -20, "Red", "CR"),
                ("Contract repository setup", "On Hold", 0.1, -70, -15, "Red", "CHN"),
                ("Approval workflow configuration", "Not Started", 0.0, -45, -10, "Red", "CN"),
                ("Catalog and punch-out setup", "Not Started", 0.0, -30, -5, "Red", "N"),
            ]),
            ("Integration & Testing", [
                ("ERP integration build", "In Progress", 0.15, -60, -8, "Red", "CRN"),
                ("Integration test cycle 1", "Not Started", 0.0, -30, -2, "Red", "N"),
                ("User acceptance testing", "Not Started", 0.0, -12, -1, "Red", "C"),
            ]),
            ("Training & Cutover", [
                ("Training material preparation", "Not Started", 0.0, 5, 20, "Yellow", "N"),
                ("Cutover rehearsal", "Not Started", 0.0, 22, 28, "Green", "C"),
            ]),
            ("Go-live & Hypercare", [
                ("Go-live", "Not Started", 0.0, 29, 29, "Red", "CR"),
                ("Hypercare support", "Not Started", 0.0, 30, 55, "Green", "N"),
            ]),
        ],
        "comments": [
            ("Solution design sign-off", "Sign-off has been delayed repeatedly and the sponsor is frustrated with the lack of progress.", "Sam Carter", "2026-06-20"),
            ("Contract repository setup", "Work paused. Legal has not released the contract templates and we cannot proceed.", "Nina Okafor", "2026-06-23"),
            ("ERP integration build", "Resource shortage on the client IT side, build is well behind and at risk of missing go-live.", "Luis Romero", "2026-06-29"),
        ],
    },
]


def _worst_health(healths):
    if "Red" in healths:
        return "Red"
    if "Yellow" in healths:
        return "Yellow"
    return "Green"


def _row(name, status, pct, start, end, health, flags, depth, owner, milestone=None):
    variance_days = -3 if health == "Red" else (-1 if health == "Yellow" else 0)
    baseline_finish = end - timedelta(days=variance_days) if end else None
    return [
        name, status, pct, start, end,
        start, baseline_finish, f"{variance_days}d", health,
        "C" in flags, "H" in flags, False, "R" in flags, depth,
        milestone, None, None, None, None, owner, None,
    ]


def build_project(spec):
    wb = openpyxl.Workbook()

    # ---- Summary sheet (two-column key/value) ----
    ws = wb.active
    ws.title = "Summary"
    all_tasks = [t for _, tasks in spec["phases"] for t in tasks]
    count = lambda s: sum(1 for t in all_tasks if t[1] == s)
    done_pct = sum(t[2] for t in all_tasks) / len(all_tasks)
    health = _worst_health([t[5] for t in all_tasks])
    summary = [
        ("Project Manager", spec["pm"]),
        ("Project Start Date", spec["start"]),
        ("Project End Date", spec["end"]),
        ("Today's Date", TODAY),
        ("% Complete", round(done_pct, 3)),
        ("Schedule Health", health),
        ("Project Stage", spec["stage"]),
        ("Project Status", "In Progress"),
        ("At Risk", "Yes" if any("R" in t[6] for t in all_tasks) else "No"),
        ("Not Started", count("Not Started")),
        ("In Progress", count("In Progress")),
        ("Completed", count("Completed")),
        ("On Hold", count("On Hold")),
        ("Duration", (spec["end"] - spec["start"]).days),
    ]
    for key, value in summary:
        ws.append([key, value])

    # ---- Project plan sheet ----
    plan = wb.create_sheet("Project Plan")
    plan.append(TASK_HEADERS)

    plan.append(_row(
        spec["name"], "In Progress", round(done_pct, 3), spec["start"], spec["end"],
        health, "", 0, spec["pm"],
    ))

    owners = spec["owners"]
    task_counter = 0
    row_numbers = {}
    for phase_name, tasks in spec["phases"]:
        statuses = {t[1] for t in tasks}
        phase_status = (
            "Completed" if statuses == {"Completed"}
            else "Not Started" if statuses == {"Not Started"}
            else "In Progress"
        )
        phase_start = TODAY + timedelta(days=min(t[3] for t in tasks))
        phase_end = TODAY + timedelta(days=max(t[4] for t in tasks))
        plan.append(_row(
            phase_name, phase_status, round(sum(t[2] for t in tasks) / len(tasks), 3),
            phase_start, phase_end, _worst_health([t[5] for t in tasks]), "", 1,
            spec["pm"], milestone="Milestone",
        ))
        for name, status, pct, s_off, e_off, task_health, flags in tasks:
            owner = None if "N" in flags else owners[task_counter % len(owners)]
            task_counter += 1
            plan.append(_row(
                name, status, pct, TODAY + timedelta(days=s_off),
                TODAY + timedelta(days=e_off), task_health, flags, 2, owner,
            ))
            row_numbers[name] = plan.max_row

    # ---- Comments sheet ----
    cs = wb.create_sheet("Comments")
    for task_name, text, author, ts in spec["comments"]:
        cs.append([f"Row {row_numbers.get(task_name, '')}", text, author, ts])

    path = OUT_DIR / spec["file"]
    wb.save(path)
    return path


if __name__ == "__main__":
    for spec in PROJECTS:
        print("wrote", build_project(spec).relative_to(OUT_DIR.parent))

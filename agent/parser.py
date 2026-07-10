"""
parser.py
---------
Ingests project plan files and normalises them into a consistent
internal data structure regardless of column layout differences between files.

Supported formats:
    - .xlsx  (Excel 2007+)
    - .xls   (Excel 97-2003, via xlrd)
    - .csv   (single flat task sheet, no Summary/Comments sheets)

Output schema (ProjectData dataclass):
    - meta        : high-level summary fields from the Summary sheet
    - tasks       : list of TaskRow dicts (one per task row)
    - comments    : list of CommentEntry dicts from the Comments sheet
    - data_quality: dict flagging which fields were missing / unparseable
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNPARSEABLE = "#UNPARSEABLE"

# Canonical column names we want, mapped from possible aliases found across
# the two file formats.  The parser resolves aliases at load time.
COLUMN_ALIASES: dict[str, list[str]] = {
    "task_name":        ["Task Name"],
    "status":           ["Status"],
    "pct_complete":     ["% Complete"],
    "start_date":       ["Start Date", "Start"],
    "end_date":         ["End Date", "Finish"],
    "baseline_start":   ["Baseline Start", "Baseline Start Date", "Baseline Start2"],
    "baseline_finish":  ["Baseline Finish", "Baseline End Date", "Baseline Finish2"],
    "variance":         ["Variance", "Variance2"],
    "schedule_health":  ["Schedule Health", "RAG"],
    "critical":         ["Critical ?"],
    "on_hold":          ["On Hold?"],
    "not_applicable":   ["Not Applicable?"],
    "at_risk":          ["At Risk?"],
    "ancestors":        ["Ancestors"],
    "phase_milestone":  ["Phase/Milestone"],
    "area":             ["Area"],
    "duration":         ["Duration"],
    "total_float":      ["Total Float"],
    "status_comment":   ["Status Comment"],
    "assigned_to":      ["Assigned To"],
    "priority":         ["Priority"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProjectMeta:
    """High-level project summary extracted from the Summary sheet."""
    project_name:   str   = "Unknown"
    project_manager: str  = "Unknown"
    start_date:     datetime | None = None
    end_date:       datetime | None = None
    today:          datetime | None = None
    pct_complete:   float = 0.0
    schedule_health: str  = "Unknown"
    project_stage:  str   = "Unknown"
    project_status: str   = "Unknown"
    at_risk:        str   = "Unknown"
    count_not_started: int = 0
    count_in_progress: int = 0
    count_completed:   int = 0
    count_on_hold:     int = 0
    duration_days:  int   = 0
    # These are often #UNPARSEABLE in the raw files
    schedule_delta:    str | None = None
    schedule_variance: str | None = None


@dataclass
class TaskRow:
    """One normalised task row."""
    task_name:      str
    status:         str   = "Unknown"
    pct_complete:   float = 0.0
    start_date:     datetime | None = None
    end_date:       datetime | None = None
    baseline_start: datetime | None = None
    baseline_finish: datetime | None = None
    variance_days:  int | None = None   # numeric days, parsed from string like "-12d"
    schedule_health: str = "Unknown"
    is_critical:    bool = False
    is_on_hold:     bool = False
    is_not_applicable: bool = False
    is_at_risk:     bool = False
    ancestors:      int  = 0            # depth / indent level
    phase_milestone: str | None = None
    area:           str | None = None
    duration:       str | None = None
    total_float:    float | None = None
    status_comment: str | None = None
    assigned_to:    str | None = None
    priority:       str | None = None


@dataclass
class CommentEntry:
    """One row from the Comments sheet."""
    row_ref:   str
    text:      str
    author:    str | None = None
    timestamp: str | None = None


@dataclass
class ProjectData:
    """Full parsed representation of one project plan file."""
    source_file:   str
    meta:          ProjectMeta = field(default_factory=ProjectMeta)
    tasks:         list[TaskRow] = field(default_factory=list)
    comments:      list[CommentEntry] = field(default_factory=list)
    data_quality:  dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_str(v: Any) -> str | None:
    """Return stripped string or None for blank / UNPARSEABLE values."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s == UNPARSEABLE:
        return None
    return s


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f
    except (ValueError, TypeError):
        return None


def _safe_bool(v: Any) -> bool:
    """Treat True / 'yes' / 'true' / 1 as True, everything else False."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return False


def _parse_variance(v: Any) -> int | None:
    """
    Variance is stored as strings like '-12d', '5d', '0', or as a raw int/float.
    Returns integer days (negative = behind schedule).
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower()
    if s in ("", UNPARSEABLE.lower()):
        return None
    # strip trailing 'd' and parse
    m = re.match(r"^(-?\d+(?:\.\d+)?)d?$", s)
    if m:
        return int(float(m.group(1)))
    return None


def _parse_date(v: Any) -> datetime | None:
    """Accept datetime objects or common date strings."""
    if isinstance(v, datetime):
        return v
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", UNPARSEABLE):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _build_col_index(headers: list[Any]) -> dict[str, int]:
    """
    Given a header row, return a mapping from canonical field name to
    column index, using the COLUMN_ALIASES lookup.
    """
    # First, build a raw name→index map
    raw: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h is not None:
            raw[str(h).strip()] = i

    index: dict[str, int] = {}
    for canon, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                # Only take the first match (earliest alias wins)
                if canon not in index:
                    index[canon] = raw[alias]
    return index


def _get(row: tuple, idx: dict[str, int], key: str) -> Any:
    """Safely get a value from a row tuple by canonical key."""
    i = idx.get(key)
    if i is None or i >= len(row):
        return None
    return row[i]


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _parse_summary_sheet(ws) -> tuple[ProjectMeta, dict]:
    """Extract the Summary sheet into a ProjectMeta object."""
    meta = ProjectMeta()
    missing_fields: list[str] = []

    # The Summary sheet is a two-column key-value layout
    kv: dict[str, Any] = {}
    for row in ws.iter_rows(values_only=True):
        if row[0] is not None:
            key = str(row[0]).strip()
            val = row[1] if len(row) > 1 else None
            kv[key] = val

    def get_kv(k: str) -> Any:
        v = kv.get(k)
        if v is None or str(v).strip() == UNPARSEABLE:
            return None
        return v

    meta.project_manager  = _safe_str(get_kv("Project Manager")) or "Unknown"
    meta.start_date       = _parse_date(get_kv("Project Start Date"))
    meta.end_date         = _parse_date(get_kv("Project End Date"))
    meta.today            = _parse_date(get_kv("Today's Date"))
    meta.pct_complete     = _safe_float(get_kv("% Complete")) or 0.0
    meta.schedule_health  = _safe_str(get_kv("Schedule Health")) or "Unknown"
    meta.project_stage    = _safe_str(get_kv("Project Stage")) or "Unknown"
    meta.project_status   = _safe_str(get_kv("Project Status")) or "Unknown"
    meta.at_risk          = _safe_str(get_kv("At Risk")) or "Unknown"
    meta.count_not_started = int(_safe_float(get_kv("Not Started")) or 0)
    meta.count_in_progress = int(_safe_float(get_kv("In Progress")) or 0)
    meta.count_completed   = int(_safe_float(get_kv("Completed")) or 0)
    meta.count_on_hold     = int(_safe_float(get_kv("On Hold")) or 0)
    meta.duration_days     = int(_safe_float(get_kv("Duration")) or 0)
    meta.schedule_delta    = _safe_str(get_kv("Schedule Delta"))
    meta.schedule_variance = _safe_str(get_kv("Schedule Variance"))

    # Track what was missing
    if meta.start_date is None:
        missing_fields.append("project_start_date")
    if meta.end_date is None:
        missing_fields.append("project_end_date")
    if meta.today is None:
        missing_fields.append("today_date")
    if meta.schedule_delta is None:
        missing_fields.append("schedule_delta")
    if meta.schedule_variance is None:
        missing_fields.append("schedule_variance")

    quality = {"missing_summary_fields": missing_fields}
    return meta, quality


def _parse_task_sheet(ws) -> tuple[list[TaskRow], dict]:
    """Extract all task rows from the main project plan sheet."""
    rows_iter = ws.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if header_row is None:
        return [], {"error": "Empty task sheet"}

    idx = _build_col_index(list(header_row))

    tasks: list[TaskRow] = []
    missing_baseline_count = 0
    unparseable_count = 0
    total_rows = 0

    for raw_row in rows_iter:
        # Skip truly empty rows
        if not any(v is not None for v in raw_row):
            continue

        task_name = _safe_str(_get(raw_row, idx, "task_name"))
        if task_name is None:
            continue  # skip rows without a task name

        total_rows += 1

        # Count UNPARSEABLE values in this row
        unparseable_count += sum(
            1 for v in raw_row if str(v).strip() == UNPARSEABLE
        )

        b_start = _parse_date(_get(raw_row, idx, "baseline_start"))
        b_finish = _parse_date(_get(raw_row, idx, "baseline_finish"))
        if b_start is None and b_finish is None:
            missing_baseline_count += 1

        task = TaskRow(
            task_name       = task_name,
            status          = _safe_str(_get(raw_row, idx, "status")) or "Unknown",
            pct_complete    = _safe_float(_get(raw_row, idx, "pct_complete")) or 0.0,
            start_date      = _parse_date(_get(raw_row, idx, "start_date")),
            end_date        = _parse_date(_get(raw_row, idx, "end_date")),
            baseline_start  = b_start,
            baseline_finish = b_finish,
            variance_days   = _parse_variance(_get(raw_row, idx, "variance")),
            schedule_health = _safe_str(_get(raw_row, idx, "schedule_health")) or "Unknown",
            is_critical     = _safe_bool(_get(raw_row, idx, "critical")),
            is_on_hold      = _safe_bool(_get(raw_row, idx, "on_hold")),
            is_not_applicable = _safe_bool(_get(raw_row, idx, "not_applicable")),
            is_at_risk      = _safe_bool(_get(raw_row, idx, "at_risk")),
            ancestors       = int(_safe_float(_get(raw_row, idx, "ancestors")) or 0),
            phase_milestone = _safe_str(_get(raw_row, idx, "phase_milestone")),
            area            = _safe_str(_get(raw_row, idx, "area")),
            duration        = _safe_str(_get(raw_row, idx, "duration")),
            total_float     = _safe_float(_get(raw_row, idx, "total_float")),
            status_comment  = _safe_str(_get(raw_row, idx, "status_comment")),
            assigned_to     = _safe_str(_get(raw_row, idx, "assigned_to")),
            priority        = _safe_str(_get(raw_row, idx, "priority")),
        )
        tasks.append(task)

    quality = {
        "total_task_rows":         total_rows,
        "missing_baseline_count":  missing_baseline_count,
        "missing_baseline_pct":    round(missing_baseline_count / total_rows * 100, 1) if total_rows else 0,
        "unparseable_cell_count":  unparseable_count,
        "columns_mapped":          list(idx.keys()),
        "columns_unmapped":        [
            canon for canon in COLUMN_ALIASES if canon not in idx
        ],
    }
    return tasks, quality


def _parse_comments_sheet(ws) -> list[CommentEntry]:
    """Extract the Comments sheet (row_ref, text, author, timestamp)."""
    comments: list[CommentEntry] = []
    for row in ws.iter_rows(values_only=True):
        if not any(v is not None for v in row):
            continue
        row_ref   = _safe_str(row[0]) or ""
        text      = _safe_str(row[1]) if len(row) > 1 else None
        author    = _safe_str(row[2]) if len(row) > 2 else None
        timestamp = _safe_str(row[3]) if len(row) > 3 else None

        if text:  # only keep rows that have actual comment text
            comments.append(CommentEntry(
                row_ref   = row_ref,
                text      = text,
                author    = author,
                timestamp = timestamp,
            ))
    return comments


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _open_workbook_xls(filepath: Path):
    """
    Open a legacy .xls file using xlrd and return a duck-typed object
    that exposes the same interface as openpyxl workbooks:
        .sheetnames  -> list[str]
        wb[name]     -> sheet with .iter_rows(values_only=True)
    """
    try:
        import xlrd
    except ImportError:
        raise ImportError(
            "xlrd is required for .xls files. "
            "Install it with: pip install xlrd"
        )

    book = xlrd.open_workbook(str(filepath))

    class _XlsSheet:
        def __init__(self, sheet, datemode):
            self._sheet    = sheet
            self._datemode = datemode

        def iter_rows(self, min_row=1, max_row=None, values_only=True):
            nrows = self._sheet.nrows
            end   = nrows if max_row is None else min(max_row, nrows)
            for r in range(min_row - 1, end):
                row = []
                for c in range(self._sheet.ncols):
                    cell = self._sheet.cell(r, c)
                    val  = cell.value
                    # Convert xlrd date serial to datetime
                    if cell.ctype == 3 and val:
                        try:
                            import xlrd as _xlrd
                            tup = _xlrd.xldate_as_tuple(val, self._datemode)
                            val = datetime(*tup) if tup[0] else None
                        except Exception:
                            pass
                    elif cell.ctype == 0:   # empty
                        val = None
                    row.append(val)
                yield tuple(row)

        @property
        def max_row(self):
            return self._sheet.nrows

        @property
        def max_column(self):
            return self._sheet.ncols

    class _XlsWorkbook:
        def __init__(self, book):
            self._book      = book
            self.sheetnames = book.sheet_names()

        def __getitem__(self, name):
            return _XlsSheet(self._book.sheet_by_name(name),
                             self._book.datemode)

    return _XlsWorkbook(book)


def _open_workbook_csv(filepath: Path):
    """
    Wrap a CSV file as a minimal workbook with one sheet called 'Sheet1'.
    The CSV is expected to have a header row matching the standard column names.
    No Summary or Comments sheets — meta will use defaults.
    """
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader   = csv.reader(f)
        all_rows = [tuple(row) for row in reader]

    class _CsvSheet:
        def __init__(self, rows):
            self._rows = rows

        def iter_rows(self, min_row=1, max_row=None, values_only=True):
            end = len(self._rows) if max_row is None else min(max_row, len(self._rows))
            for row in self._rows[min_row - 1 : end]:
                yield row

        @property
        def max_row(self):    return len(self._rows)
        @property
        def max_column(self): return max((len(r) for r in self._rows), default=0)

    class _CsvWorkbook:
        def __init__(self, rows):
            self._sheet     = _CsvSheet(rows)
            self.sheetnames = ["Sheet1"]
        def __getitem__(self, name):
            return self._sheet

    return _CsvWorkbook(all_rows)


def parse_project_file(filepath: str | Path) -> ProjectData:
    """
    Parse a project plan file into a single ProjectData object.
    Uses the first depth=0 task row as the project.

    For files containing multiple projects (multiple depth=0 rows),
    use parse_projects_from_file() instead.
    """
    projects = parse_projects_from_file(filepath)
    if not projects:
        raise ValueError(f"No projects found in {filepath}")
    return projects[0]


def parse_projects_from_file(filepath: str | Path) -> list[ProjectData]:
    """
    Parse a project plan file and return ONE ProjectData per depth=0 row.

    A single Excel file can contain multiple projects stacked vertically,
    each starting with a depth=0 row (Ancestors=0 or Level=0) followed by
    its child tasks at deeper levels.

    Example — S2P Project.xlsx yields 3 ProjectData objects:
        1. Zycus - Titan S2P Implementation  (depth=0)
        2. Phase 1 - S2C                     (depth=0)
        3. Phase 2 - P2P                     (depth=0)

    All three share the same Summary and Comments sheets, but each gets
    its own task slice, its own scores, and its own report.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Project file not found: {filepath}")

    ext = filepath.suffix.lower()
    if ext == ".xlsx":
        wb = openpyxl.load_workbook(str(filepath), data_only=True)
    elif ext == ".xls":
        wb = _open_workbook_xls(filepath)
    elif ext == ".csv":
        wb = _open_workbook_csv(filepath)
    else:
        raise ValueError(
            f"Unsupported file format '{ext}'. "
            "Supported formats: .xlsx, .xls, .csv"
        )

    sheet_names = wb.sheetnames

    # ── Shared: Summary sheet (same for all projects in this file) ──
    shared_meta = ProjectMeta()
    shared_dq: dict = {}
    for name in sheet_names:
        if "summary" in name.lower():
            shared_meta, shared_dq = _parse_summary_sheet(wb[name])
            break

    # ── Shared: Comments sheet ──
    shared_comments: list[CommentEntry] = []
    for name in sheet_names:
        if "comment" in name.lower():
            shared_comments = _parse_comments_sheet(wb[name])
            break

    # ── Task sheet ──
    task_sheet = None
    for name in sheet_names:
        lower = name.lower()
        if "summary" not in lower and "comment" not in lower:
            task_sheet = wb[name]
            break

    if task_sheet is None:
        # No task sheet — return one empty project
        p = ProjectData(source_file=str(filepath))
        p.meta     = shared_meta
        p.comments = shared_comments
        p.data_quality = {**shared_dq, "task_sheet_error": "No task sheet found"}
        return [p]

    # Parse ALL rows once
    all_tasks, tq = _parse_task_sheet(task_sheet)

    if not all_tasks:
        p = ProjectData(source_file=str(filepath))
        p.meta     = shared_meta
        p.comments = shared_comments
        p.data_quality = {**shared_dq, **tq}
        return [p]

    # ── Split by depth=0 rows ──
    # Find positions of all depth=0 rows
    root_indices = [i for i, t in enumerate(all_tasks) if t.ancestors == 0]

    if not root_indices:
        # No depth=0 rows — treat all tasks as one project
        root_indices = [0]

    projects: list[ProjectData] = []

    for pos, root_idx in enumerate(root_indices):
        root_task = all_tasks[root_idx]

        # Child rows = everything up to the next depth=0 row (exclusive)
        next_root = root_indices[pos + 1] if pos + 1 < len(root_indices) else len(all_tasks)
        child_tasks = all_tasks[root_idx + 1 : next_root]

        # Build per-project meta — start from shared summary then override
        # with what we can derive from the root task row
        import copy
        meta = copy.deepcopy(shared_meta)
        meta.project_name    = root_task.task_name
        meta.schedule_health = root_task.schedule_health
        meta.pct_complete    = root_task.pct_complete
        meta.project_status  = root_task.status

        # Derive start/end dates from child tasks if not in summary
        if meta.start_date is None:
            dates = [t.start_date for t in child_tasks if t.start_date]
            if dates:
                meta.start_date = min(dates)
        if meta.end_date is None:
            dates = [t.end_date for t in child_tasks if t.end_date]
            if dates:
                meta.end_date = max(dates)

        # Task counts from child rows
        meta.count_not_started = sum(1 for t in child_tasks if t.status == "Not Started")
        meta.count_in_progress = sum(1 for t in child_tasks if t.status == "In Progress")
        meta.count_completed   = sum(1 for t in child_tasks if t.status == "Completed")
        meta.count_on_hold     = sum(1 for t in child_tasks
                                     if t.is_on_hold or t.status == "On Hold")

        # Data quality for this slice
        n = len(child_tasks)
        missing_bl = sum(
            1 for t in child_tasks
            if t.baseline_start is None and t.baseline_finish is None
        )
        dq = {
            **shared_dq,
            "total_task_rows":        n,
            "missing_baseline_count": missing_bl,
            "missing_baseline_pct":   round(missing_bl / n * 100, 1) if n else 0,
            "unparseable_cell_count": tq.get("unparseable_cell_count", 0),
            "columns_mapped":         tq.get("columns_mapped", []),
            "columns_unmapped":       tq.get("columns_unmapped", []),
            "comment_count":          len(shared_comments),
            "has_comments":           len(shared_comments) > 0,
            "source_file":            filepath.name,
        }

        p = ProjectData(source_file=str(filepath))
        p.meta         = meta
        p.tasks        = child_tasks
        p.comments     = shared_comments   # all projects in file share comments
        p.data_quality = dq
        projects.append(p)

    return projects


def load_all_projects(folder: str | Path) -> list[ProjectData]:
    """
    Load all supported project plan files from a folder.
    Supported: .xlsx, .xls, .csv
    Skips temp files (starting with ~$).
    Each file may yield multiple ProjectData objects (one per depth=0 row).
    """
    folder = Path(folder)
    projects = []
    for ext in ("*.xlsx", "*.xls", "*.csv"):
        for f in sorted(folder.glob(ext)):
            if f.name.startswith("~$"):
                continue
            try:
                projects.extend(parse_projects_from_file(f))
            except Exception as e:
                print(f"[parser] Warning: could not load {f.name}: {e}")
    return projects


# ---------------------------------------------------------------------------
# Quick smoke-test (run this file directly to verify parsing)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from pathlib import Path

    data_dir = Path(__file__).parent.parent  # up to 'health_agent' folder
    projects = load_all_projects(data_dir)

    for p in projects:
        print(f"\n{'='*60}")
        print(f"Project : {p.meta.project_name}")
        print(f"PM      : {p.meta.project_manager}")
        print(f"Stage   : {p.meta.project_stage}")
        print(f"Health  : {p.meta.schedule_health}")
        print(f"Complete: {p.meta.pct_complete*100:.0f}%")
        print(f"Tasks   : {len(p.tasks)} rows parsed")
        print(f"Comments: {len(p.comments)}")
        print(f"Quality : {p.data_quality}")

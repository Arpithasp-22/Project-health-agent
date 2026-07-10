"""
database.py
-----------
Two SQLite databases for the Project Health Agent.

Database 1 — report_archive.db
    Table: reports
    One row per analysis run. Stores the full report as JSON plus
    key fields as indexed columns for fast querying.

Database 2 — daily_tracking.db
    Table: daily_metrics
    One row per project per day. Stores only the key health numbers.
    This is what powers sparkline charts and trend queries.

Both databases live in health_agent/data/ and are created automatically
on first use — no setup required.

Public API
----------
    save_report(report_dict)           -> int (row id)
    get_all_reports()                  -> list[dict]
    get_reports_for_project(name)      -> list[dict]
    get_report_by_id(id)               -> dict | None

    save_daily_metric(metric_dict)     -> int (row id)
    get_daily_metrics(project_name)    -> list[dict]   (chronological)
    get_all_daily_metrics()            -> list[dict]
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

ARCHIVE_DB  = DATA_DIR / "report_archive.db"
TRACKING_DB = DATA_DIR / "daily_tracking.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name     TEXT    NOT NULL,
    project_manager  TEXT,
    project_stage    TEXT,
    source_file      TEXT,
    as_of            TEXT    NOT NULL,
    run_timestamp    TEXT    NOT NULL,
    overall_rag      TEXT    NOT NULL,
    overall_score    REAL    NOT NULL,
    confidence       INTEGER NOT NULL,
    confidence_note  TEXT,
    pace_gap         REAL,
    pct_work_done    REAL,
    pct_time_elapsed REAL,
    llm_available    INTEGER,
    full_report_json TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_project
    ON reports (project_name);
CREATE INDEX IF NOT EXISTS idx_reports_as_of
    ON reports (as_of);
"""

_TRACKING_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name     TEXT    NOT NULL,
    as_of            TEXT    NOT NULL,
    run_timestamp    TEXT    NOT NULL,
    overall_rag      TEXT    NOT NULL,
    overall_score    REAL    NOT NULL,
    confidence       INTEGER NOT NULL,
    pace_gap         REAL,
    pct_work_done    REAL,
    pct_time_elapsed REAL,
    schedule_rag     TEXT,
    schedule_score   REAL,
    execution_rag    TEXT,
    execution_score  REAL,
    milestones_rag   TEXT,
    milestones_score REAL,
    blockers_rag     TEXT,
    blockers_score   REAL,
    UNIQUE (project_name, as_of)   -- one row per project per day
        ON CONFLICT REPLACE        -- re-running on the same day updates the row
);

CREATE INDEX IF NOT EXISTS idx_daily_project
    ON daily_metrics (project_name);
CREATE INDEX IF NOT EXISTS idx_daily_as_of
    ON daily_metrics (as_of);
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_archive_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(ARCHIVE_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(_ARCHIVE_SCHEMA)
    conn.commit()
    return conn


def _get_tracking_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TRACKING_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(_TRACKING_SCHEMA)
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Database 1 — Report Archive
# ---------------------------------------------------------------------------

def save_report(report_dict: dict) -> int:
    """
    Save a full report to report_archive.db.
    report_dict is the output of vars(WeeklyReport).
    Returns the new row id.
    """
    now = datetime.now().isoformat(timespec="seconds")

    # Extract dimension scores for indexed columns
    dims = report_dict.get("dimensions", {})

    conn = _get_archive_conn()
    try:
        cursor = conn.execute(
            """
            INSERT INTO reports (
                project_name, project_manager, project_stage, source_file,
                as_of, run_timestamp,
                overall_rag, overall_score, confidence, confidence_note,
                pace_gap, pct_work_done, pct_time_elapsed, llm_available,
                full_report_json
            ) VALUES (
                :project_name, :project_manager, :project_stage, :source_file,
                :as_of, :run_timestamp,
                :overall_rag, :overall_score, :confidence, :confidence_note,
                :pace_gap, :pct_work_done, :pct_time_elapsed, :llm_available,
                :full_report_json
            )
            """,
            {
                "project_name":     report_dict.get("project_name", "Unknown"),
                "project_manager":  report_dict.get("project_manager", ""),
                "project_stage":    report_dict.get("project_stage", ""),
                "source_file":      report_dict.get("source_file", ""),
                "as_of":            report_dict.get("as_of", ""),
                "run_timestamp":    now,
                "overall_rag":      report_dict.get("overall_rag", ""),
                "overall_score":    report_dict.get("overall_score", 0),
                "confidence":       report_dict.get("confidence", 0),
                "confidence_note":  report_dict.get("confidence_note", ""),
                "pace_gap":         report_dict.get("pace_gap", 0),
                "pct_work_done":    report_dict.get("pct_work_done", 0),
                "pct_time_elapsed": report_dict.get("pct_time_elapsed", 0),
                "llm_available":    int(report_dict.get("llm_available", False)),
                "full_report_json": json.dumps(report_dict, default=str),
            },
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_reports() -> list[dict]:
    """Return all reports, newest first."""
    conn = _get_archive_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY run_timestamp DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = _row_to_dict(row)
            # Parse the full JSON back for callers that need it
            try:
                d["_full"] = json.loads(d["full_report_json"])
            except Exception:
                d["_full"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def get_reports_for_project(project_name: str) -> list[dict]:
    """Return all reports for one project, oldest first (for trend charts)."""
    conn = _get_archive_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM reports WHERE project_name = ? ORDER BY as_of ASC",
            (project_name,),
        ).fetchall()
        result = []
        for row in rows:
            d = _row_to_dict(row)
            try:
                d["_full"] = json.loads(d["full_report_json"])
            except Exception:
                d["_full"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def get_report_by_id(report_id: int) -> dict | None:
    """Return a single report by its id."""
    conn = _get_archive_conn()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        d = _row_to_dict(row)
        try:
            d["_full"] = json.loads(d["full_report_json"])
        except Exception:
            d["_full"] = {}
        return d
    finally:
        conn.close()


def get_project_names() -> list[str]:
    """Return all distinct project names in the archive, sorted."""
    conn = _get_archive_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT project_name FROM reports ORDER BY project_name"
        ).fetchall()
        return [r["project_name"] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Database 2 — Daily Tracking
# ---------------------------------------------------------------------------

def save_daily_metric(report_dict: dict) -> int:
    """
    Save / update today's metric row for a project in daily_tracking.db.
    If a row for (project_name, as_of) already exists it is replaced
    (UNIQUE ON CONFLICT REPLACE), so re-running on the same day is safe.
    Returns the row id.
    """
    now  = datetime.now().isoformat(timespec="seconds")
    dims = report_dict.get("dimensions", {})

    def _dim(name: str, field: str):
        return dims.get(name, {}).get(field)

    conn = _get_tracking_conn()
    try:
        cursor = conn.execute(
            """
            INSERT INTO daily_metrics (
                project_name, as_of, run_timestamp,
                overall_rag, overall_score, confidence,
                pace_gap, pct_work_done, pct_time_elapsed,
                schedule_rag,   schedule_score,
                execution_rag,  execution_score,
                milestones_rag, milestones_score,
                blockers_rag,   blockers_score
            ) VALUES (
                :project_name, :as_of, :run_timestamp,
                :overall_rag, :overall_score, :confidence,
                :pace_gap, :pct_work_done, :pct_time_elapsed,
                :schedule_rag,   :schedule_score,
                :execution_rag,  :execution_score,
                :milestones_rag, :milestones_score,
                :blockers_rag,   :blockers_score
            )
            """,
            {
                "project_name":    report_dict.get("project_name", "Unknown"),
                "as_of":           report_dict.get("as_of", ""),
                "run_timestamp":   now,
                "overall_rag":     report_dict.get("overall_rag", ""),
                "overall_score":   report_dict.get("overall_score", 0),
                "confidence":      report_dict.get("confidence", 0),
                "pace_gap":        report_dict.get("pace_gap", 0),
                "pct_work_done":   report_dict.get("pct_work_done", 0),
                "pct_time_elapsed":report_dict.get("pct_time_elapsed", 0),
                "schedule_rag":    _dim("schedule",   "rag"),
                "schedule_score":  _dim("schedule",   "score"),
                "execution_rag":   _dim("execution",  "rag"),
                "execution_score": _dim("execution",  "score"),
                "milestones_rag":  _dim("milestones", "rag"),
                "milestones_score":_dim("milestones", "score"),
                "blockers_rag":    _dim("blockers",   "rag"),
                "blockers_score":  _dim("blockers",   "score"),
            },
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_daily_metrics(project_name: str) -> list[dict]:
    """
    Return all daily metric rows for one project, oldest first.
    Used for sparklines and trend charts.
    """
    conn = _get_tracking_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM daily_metrics
            WHERE project_name = ?
            ORDER BY as_of ASC
            """,
            (project_name,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_all_daily_metrics() -> list[dict]:
    """Return all daily metric rows across all projects, newest first."""
    conn = _get_tracking_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM daily_metrics ORDER BY as_of DESC, project_name"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

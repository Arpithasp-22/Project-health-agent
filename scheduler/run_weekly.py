"""
run_weekly.py
-------------
Schedules the health agent to run every Monday at 08:00.

Two modes:
    python scheduler/run_weekly.py          # start the scheduler loop
    python scheduler/run_weekly.py --now    # run immediately (for testing)

The scheduler uses the 'schedule' library (lightweight, no system config
needed). For production use, Windows Task Scheduler or a cron job is
recommended instead — see README.md for instructions.

Each weekly run:
    1. Processes all .xlsx files in the health_agent folder
    2. Writes timestamped JSON + Markdown reports to outputs/weekly/
    3. Logs run start/end to outputs/weekly/run_log.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import schedule

from agent.agent import OUTPUT_DIR, main as run_agent
from agent.parser import load_all_projects


LOG_FILE = OUTPUT_DIR / "run_log.txt"


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def weekly_job() -> None:
    """The job that runs every Monday."""
    _log("=== Weekly health agent run started ===")
    try:
        # Temporarily set sys.argv to pass no files (uses folder default)
        original_argv = sys.argv
        sys.argv = ["agent.py"]   # no --no-llm so LLM is active
        run_agent()
        sys.argv = original_argv
        _log("=== Run completed successfully ===")
    except Exception as e:
        _log(f"=== Run FAILED: {e} ===")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly health agent scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run the agent immediately instead of waiting for the schedule.",
    )
    parser.add_argument(
        "--day",
        default="monday",
        choices=["monday", "tuesday", "wednesday", "thursday", "friday"],
        help="Day of week to run (default: monday)",
    )
    parser.add_argument(
        "--time",
        default="08:00",
        help="Time to run in HH:MM format (default: 08:00)",
    )
    args = parser.parse_args()

    if args.now:
        _log("Running agent immediately (--now flag)")
        weekly_job()
        return

    # Set up the recurring schedule
    day_fn = getattr(schedule.every(), args.day)
    day_fn.at(args.time).do(weekly_job)

    _log(f"Scheduler started — will run every {args.day.title()} at {args.time}")
    _log("Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)   # check every minute
    except KeyboardInterrupt:
        _log("Scheduler stopped by user.")


if __name__ == "__main__":
    main()

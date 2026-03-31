"""Query audit log - JSONL format with daily rotation and retention cleanup."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR


LOGS_DIR = CONFIG_DIR / "logs"


def _today_log_file() -> Path:
    return LOGS_DIR / f"queries-{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def log_query(
    connection: str,
    sql: str,
    query_type: str,
    permission: str,
    status: str,
    rows_affected: int,
    execution_ms: float,
    error: str | None = None,
) -> None:
    """Append a query log entry to today's JSONL file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "connection": connection,
        "sql": sql,
        "query_type": query_type,
        "permission": permission,
        "status": status,
        "rows_affected": rows_affected,
        "execution_ms": execution_ms,
        "error": error,
    }

    with open(_today_log_file(), "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_logs(
    connection: str | None = None,
    limit: int = 50,
    date: str | None = None,
) -> list[dict[str, Any]]:
    """Read log entries, optionally filtered by connection and date.

    If date is None, reads from all available log files (most recent first).
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if date:
        files = [LOGS_DIR / f"queries-{date}.jsonl"]
    else:
        files = sorted(LOGS_DIR.glob("queries-*.jsonl"), reverse=True)

    entries: list[dict[str, Any]] = []
    for log_file in files:
        if not log_file.exists():
            continue

        file_entries: list[dict[str, Any]] = []
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if connection and entry.get("connection") != connection:
                        continue
                    file_entries.append(entry)
                except json.JSONDecodeError:
                    continue

        # Reverse to get most recent first within each file
        entries.extend(reversed(file_entries))
        if len(entries) >= limit:
            break

    return entries[:limit]


def cleanup_old_logs(retention_days: int = 30) -> int:
    """Delete log files older than retention_days. Returns count of deleted files."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = 0

    for log_file in LOGS_DIR.glob("queries-*.jsonl"):
        try:
            # Extract date from filename
            date_str = log_file.stem.replace("queries-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                log_file.unlink()
                deleted += 1
        except (ValueError, OSError):
            continue

    return deleted

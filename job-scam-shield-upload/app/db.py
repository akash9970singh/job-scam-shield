"""SQLite store for scam reports, colleges, placement-officer accounts and login sessions.

SQLite keeps setup free for a single server. Move to PostgreSQL before running the network for
many colleges (concurrent writes, backups).
"""

import os
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS colleges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    college_id INTEGER REFERENCES colleges(id),
    role TEXT NOT NULL CHECK (role IN ('officer', 'admin')),
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_kind_value ON reports (kind, value);
"""

# Columns added to `reports` after Phase 1. Older databases are upgraded in place.
# Old reports were never reviewed, so they become 'pending'.
REPORT_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "scam_type": "TEXT NOT NULL DEFAULT 'other'",
    "college_id": "INTEGER REFERENCES colleges(id)",
    "reviewed_by": "INTEGER REFERENCES users(id)",
    "reviewed_at": "TEXT",
}


def get_db_path() -> Path:
    return Path(os.environ.get("SHIELD_DB_PATH", PROJECT_ROOT / "data" / "shield.db"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(reports)")}
    for column, definition in REPORT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE reports ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports (status, college_id)")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and always closes."""
    with closing(_open()) as conn, conn:
        yield conn


def normalize(kind: str, value: str) -> str:
    value = value.strip().lower()
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        # Keep the last 10 digits so +91 98765 43210 and 9876543210 match.
        return digits[-10:]
    if kind == "domain":
        value = re.sub(r"^https?://", "", value).split("/")[0]
        return value.removeprefix("www.")
    return value


def add_report(
    kind: str,
    value: str,
    note: str | None = None,
    scam_type: str = "other",
    college_id: int | None = None,
    status: str = "pending",
) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO reports (kind, value, note, scam_type, college_id, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, normalize(kind, value), note, scam_type, college_id, status, now()),
        )
        return cur.lastrowid


@dataclass
class ReportSummary:
    verified: int = 0
    pending: int = 0
    colleges: int = 0  # distinct colleges that verified it

    @property
    def any(self) -> bool:
        return bool(self.verified or self.pending)


def report_summary(kind: str, value: str) -> ReportSummary:
    with connect() as conn:
        row = conn.execute(
            """SELECT
                   SUM(status = 'verified') AS verified,
                   SUM(status = 'pending') AS pending,
                   COUNT(DISTINCT CASE WHEN status = 'verified' THEN college_id END) AS colleges
               FROM reports WHERE kind = ? AND value = ?""",
            (kind, normalize(kind, value)),
        ).fetchone()
    return ReportSummary(row["verified"] or 0, row["pending"] or 0, row["colleges"] or 0)

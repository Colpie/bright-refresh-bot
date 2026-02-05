"""State management for job processing"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from ..utils.logging import get_logger


# --------------------------------------------------------------------------- #
#  Data classes
# --------------------------------------------------------------------------- #


@dataclass
class ProcessingRecord:
    """Record of a single vacancy processing attempt"""

    original_vacancy_id: str
    run_id: str
    status: str = "pending"  # pending, duplicated, closed, completed, failed, skipped
    new_vacancy_id: Optional[str] = None
    error_message: Optional[str] = None
    duplicated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RunSummary:
    """Summary of a processing run"""

    run_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    total_jobs: int
    successful: int
    failed: int
    skipped: int

    @property
    def success_rate(self) -> float:
        if self.total_jobs == 0:
            return 0.0
        return (self.successful / self.total_jobs) * 100

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()


# --------------------------------------------------------------------------- #
#  SQL schema
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processing_runs (
    run_id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    total_jobs INTEGER DEFAULT 0,
    successful INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS processing_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    original_vacancy_id TEXT NOT NULL,
    new_vacancy_id TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    duplicated_at TIMESTAMP,
    closed_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES processing_runs(run_id),
    UNIQUE(run_id, original_vacancy_id)
);

CREATE INDEX IF NOT EXISTS idx_records_run_status
ON processing_records(run_id, status);

CREATE INDEX IF NOT EXISTS idx_records_vacancy
ON processing_records(original_vacancy_id);
"""


# --------------------------------------------------------------------------- #
#  Row parsing helpers
# --------------------------------------------------------------------------- #


def _parse_optional_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string or return None."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def _record_from_row(row: tuple) -> ProcessingRecord:
    """Convert a SELECT row into a ProcessingRecord.

    Expected column order:
        original_vacancy_id, run_id, status, new_vacancy_id,
        error_message, duplicated_at, closed_at, completed_at, created_at
    """
    return ProcessingRecord(
        original_vacancy_id=row[0],
        run_id=row[1],
        status=row[2],
        new_vacancy_id=row[3],
        error_message=row[4],
        duplicated_at=_parse_optional_dt(row[5]),
        closed_at=_parse_optional_dt(row[6]),
        completed_at=_parse_optional_dt(row[7]),
        created_at=_parse_optional_dt(row[8]) or datetime.utcnow(),
    )


_RECORD_COLUMNS = (
    "original_vacancy_id, run_id, status, new_vacancy_id, "
    "error_message, duplicated_at, closed_at, completed_at, created_at"
)


def _summary_from_row(row: tuple) -> RunSummary:
    """Convert a SELECT row into a RunSummary.

    Expected column order:
        run_id, started_at, completed_at, total_jobs,
        successful, failed, skipped, status
    """
    return RunSummary(
        run_id=row[0],
        started_at=datetime.fromisoformat(row[1]),
        completed_at=_parse_optional_dt(row[2]),
        total_jobs=row[3],
        successful=row[4],
        failed=row[5],
        skipped=row[6],
        status=row[7],
    )


_SUMMARY_COLUMNS = (
    "run_id, started_at, completed_at, total_jobs, "
    "successful, failed, skipped, status"
)


# --------------------------------------------------------------------------- #
#  Status-update column mapping
# --------------------------------------------------------------------------- #

_STATUS_EXTRA_COLS: dict[str, list[str]] = {
    "duplicated": ["new_vacancy_id", "duplicated_at"],
    "closed": ["closed_at"],
    "completed": ["completed_at", "error_message"],
    "failed": ["completed_at", "error_message"],
    "skipped": ["completed_at", "error_message"],
}


# --------------------------------------------------------------------------- #
#  StateManager
# --------------------------------------------------------------------------- #


class StateManager:
    """
    Manages processing state in SQLite database.

    Uses a persistent connection opened via ``connect()`` and closed via
    ``close()``.  Supports ``async with`` for automatic lifecycle management.
    Falls back to per-call connections when no persistent connection exists
    (e.g. in tests).
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._logger = get_logger("state_manager")
        self._conn: Optional[aiosqlite.Connection] = None
        self._ensure_db_directory()

    # -- lifecycle --------------------------------------------------------- #

    def _ensure_db_directory(self) -> None:
        if self.db_path == ":memory:":
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> None:
        """Open a persistent database connection."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self.db_path)

    async def close(self) -> None:
        """Close the persistent database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "StateManager":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _get_db(self) -> aiosqlite.Connection:
        """Return the persistent connection, or open a one-shot one."""
        if self._conn is not None:
            return self._conn
        # Fallback for callers that didn't call connect() (tests, scripts)
        self._conn = await aiosqlite.connect(self.db_path)
        return self._conn

    # -- schema ------------------------------------------------------------ #

    async def initialize(self) -> None:
        """Create tables and indices if they don't exist."""
        db = await self._get_db()
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
        self._logger.info("database_initialized", db_path=self.db_path)

    # -- run operations ---------------------------------------------------- #

    async def start_run(self, run_id: str, total_jobs: int) -> None:
        db = await self._get_db()
        await db.execute(
            "INSERT INTO processing_runs (run_id, started_at, total_jobs, status) "
            "VALUES (?, ?, ?, 'running')",
            (run_id, datetime.utcnow().isoformat(), total_jobs),
        )
        await db.commit()
        self._logger.info("run_started", run_id=run_id, total_jobs=total_jobs)

    async def complete_run(
        self, run_id: str, successful: int, failed: int, skipped: int,
    ) -> None:
        status = "completed" if failed == 0 else "completed_with_errors"
        db = await self._get_db()
        await db.execute(
            "UPDATE processing_runs "
            "SET completed_at = ?, successful = ?, failed = ?, skipped = ?, status = ? "
            "WHERE run_id = ?",
            (datetime.utcnow().isoformat(), successful, failed, skipped, status, run_id),
        )
        await db.commit()
        self._logger.info(
            "run_completed", run_id=run_id,
            successful=successful, failed=failed, skipped=skipped, status=status,
        )

    async def fail_run(self, run_id: str, error_message: str) -> None:
        db = await self._get_db()
        await db.execute(
            "UPDATE processing_runs SET completed_at = ?, status = 'failed' WHERE run_id = ?",
            (datetime.utcnow().isoformat(), run_id),
        )
        await db.commit()
        self._logger.error("run_failed", run_id=run_id, error=error_message)

    # -- record operations ------------------------------------------------- #

    async def add_vacancy_record(self, run_id: str, vacancy_id: str) -> None:
        db = await self._get_db()
        await db.execute(
            "INSERT OR IGNORE INTO processing_records (run_id, original_vacancy_id, status) "
            "VALUES (?, ?, 'pending')",
            (run_id, vacancy_id),
        )
        await db.commit()

    async def update_vacancy_status(
        self,
        run_id: str,
        vacancy_id: str,
        status: str,
        new_vacancy_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        extra_cols = _STATUS_EXTRA_COLS.get(status, [])

        # Build SET clause dynamically
        set_parts = ["status = ?"]
        params: list = [status]

        col_values = {
            "new_vacancy_id": new_vacancy_id,
            "duplicated_at": now,
            "closed_at": now,
            "completed_at": now,
            "error_message": error_message,
        }
        for col in extra_cols:
            set_parts.append(f"{col} = ?")
            params.append(col_values[col])

        params.extend([run_id, vacancy_id])

        db = await self._get_db()
        await db.execute(
            f"UPDATE processing_records SET {', '.join(set_parts)} "
            f"WHERE run_id = ? AND original_vacancy_id = ?",
            params,
        )
        await db.commit()

    # -- query operations -------------------------------------------------- #

    async def get_pending_vacancies(self, run_id: str) -> list[str]:
        db = await self._get_db()
        cursor = await db.execute(
            "SELECT original_vacancy_id FROM processing_records "
            "WHERE run_id = ? AND status IN ('pending', 'duplicated') "
            "ORDER BY created_at",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_run_summary(self, run_id: str) -> Optional[RunSummary]:
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM processing_runs WHERE run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        return _summary_from_row(row) if row else None

    async def get_processing_record(
        self, run_id: str, vacancy_id: str,
    ) -> Optional[ProcessingRecord]:
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {_RECORD_COLUMNS} FROM processing_records "
            f"WHERE run_id = ? AND original_vacancy_id = ?",
            (run_id, vacancy_id),
        )
        row = await cursor.fetchone()
        return _record_from_row(row) if row else None

    async def get_failed_records(self, run_id: str) -> list[ProcessingRecord]:
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {_RECORD_COLUMNS} FROM processing_records "
            f"WHERE run_id = ? AND status = 'failed' ORDER BY created_at",
            (run_id,),
        )
        return [_record_from_row(row) for row in await cursor.fetchall()]

    async def get_rollback_records(self, run_id: str) -> list[ProcessingRecord]:
        """Get records that have actions to rollback (duplicated, closed, completed, failed,
        or any record that created a new vacancy)."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {_RECORD_COLUMNS} FROM processing_records "
            f"WHERE run_id = ? AND ("
            f"  status IN ('duplicated', 'closed', 'completed', 'failed') "
            f"  OR new_vacancy_id IS NOT NULL"
            f") ORDER BY created_at",
            (run_id,),
        )
        return [_record_from_row(row) for row in await cursor.fetchall()]

    async def get_recent_runs(self, limit: int = 10) -> list[RunSummary]:
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM processing_runs "
            f"ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [_summary_from_row(row) for row in await cursor.fetchall()]

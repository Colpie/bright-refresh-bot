"""Rollback service for recovering from failed job refresh operations"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from ..api.client import BrightStaffingClient
from ..api.vacancy import VacancyService
from ..utils.logging import get_logger
from .state import StateManager, ProcessingRecord


# --------------------------------------------------------------------------- #
#  Result types
# --------------------------------------------------------------------------- #


@dataclass
class RollbackResult:
    """Result of a rollback operation"""

    vacancy_id: str
    action: str  # 'reopened', 'closed_new', 'skipped', 'failed'
    success: bool
    message: str
    new_vacancy_id: Optional[str] = None


@dataclass
class RollbackSummary:
    """Summary of rollback operation"""

    run_id: str
    total_records: int
    reopened: int
    closed_new: int
    skipped: int
    failed: int
    results: list[RollbackResult] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Service
# --------------------------------------------------------------------------- #


class RollbackService:
    """
    Service to rollback failed job refresh operations.

    Handles:
    - Reopening original vacancies that were closed
    - Closing duplicate vacancies that were created
    - Cleaning up partial failures
    """

    def __init__(
        self,
        client: BrightStaffingClient,
        state_manager: StateManager,
        dry_run: bool = False,
    ):
        self.client = client
        self.vacancy_service = VacancyService(client)
        self.state_manager = state_manager
        self.dry_run = dry_run
        self._logger = get_logger("rollback_service")

    async def rollback_run(
        self,
        run_id: str,
        reopen_closed: bool = True,
        close_duplicates: bool = True,
    ) -> RollbackSummary:
        """Rollback all changes from a processing run."""
        self._logger.info(
            "rollback_started",
            run_id=run_id,
            reopen_closed=reopen_closed,
            close_duplicates=close_duplicates,
            dry_run=self.dry_run,
        )

        summary = await self.state_manager.get_run_summary(run_id)
        if not summary:
            self._logger.error("run_not_found", run_id=run_id)
            return RollbackSummary(
                run_id=run_id, total_records=0,
                reopened=0, closed_new=0, skipped=0, failed=0,
            )

        records = await self.state_manager.get_rollback_records(run_id)
        results: list[RollbackResult] = []

        for record in records:
            result = await self._rollback_record(record, reopen_closed, close_duplicates)
            results.append(result)

        counts = Counter(r.action for r in results)

        self._logger.info(
            "rollback_completed", run_id=run_id, total=len(records),
            reopened=counts.get("reopened", 0),
            closed_new=counts.get("closed_new", 0),
            skipped=counts.get("skipped", 0),
            failed=counts.get("failed", 0),
        )

        return RollbackSummary(
            run_id=run_id,
            total_records=len(records),
            reopened=counts.get("reopened", 0),
            closed_new=counts.get("closed_new", 0),
            skipped=counts.get("skipped", 0),
            failed=counts.get("failed", 0),
            results=results,
        )

    async def rollback_single(
        self,
        run_id: str,
        vacancy_id: str,
        reopen_closed: bool = True,
        close_duplicates: bool = True,
    ) -> RollbackResult:
        """Rollback a single vacancy."""
        record = await self.state_manager.get_processing_record(run_id, vacancy_id)

        if not record:
            return RollbackResult(
                vacancy_id=vacancy_id,
                action="failed",
                success=False,
                message="Record not found",
            )

        return await self._rollback_record(record, reopen_closed, close_duplicates)

    # -- internal ---------------------------------------------------------- #

    async def _rollback_record(
        self,
        record: ProcessingRecord,
        reopen_closed: bool,
        close_duplicates: bool,
    ) -> RollbackResult:
        vacancy_id = record.original_vacancy_id

        if record.status == "pending":
            return RollbackResult(
                vacancy_id=vacancy_id, action="skipped",
                success=True, message="Nothing to rollback (pending)",
            )

        actions_taken: list[str] = []

        # Close the duplicate first (order matters for safety)
        if close_duplicates and record.new_vacancy_id:
            ok = await self._close_duplicate(record.new_vacancy_id)
            if not ok:
                return RollbackResult(
                    vacancy_id=vacancy_id, action="failed", success=False,
                    message=f"Failed to close duplicate {record.new_vacancy_id}",
                    new_vacancy_id=record.new_vacancy_id,
                )
            actions_taken.append(f"closed duplicate {record.new_vacancy_id}")

        # Reopen the original
        if reopen_closed and record.closed_at:
            ok = await self._reopen_original(vacancy_id)
            if not ok:
                return RollbackResult(
                    vacancy_id=vacancy_id, action="failed", success=False,
                    message=f"Failed to reopen original {vacancy_id}",
                    new_vacancy_id=record.new_vacancy_id,
                )
            actions_taken.append(f"reopened original {vacancy_id}")

        if not actions_taken:
            return RollbackResult(
                vacancy_id=vacancy_id, action="skipped",
                success=True, message="No rollback actions needed",
                new_vacancy_id=record.new_vacancy_id,
            )

        action = "reopened" if any("reopened" in a for a in actions_taken) else "closed_new"
        return RollbackResult(
            vacancy_id=vacancy_id, action=action, success=True,
            message="; ".join(actions_taken),
            new_vacancy_id=record.new_vacancy_id,
        )

    async def _close_duplicate(self, vacancy_id: str) -> bool:
        self._logger.info("closing_duplicate", vacancy_id=vacancy_id, dry_run=self.dry_run)
        if self.dry_run:
            return True
        try:
            return await self.vacancy_service.close_vacancy(vacancy_id, close_reason="rollback")
        except Exception as e:
            self._logger.error("close_duplicate_failed", vacancy_id=vacancy_id, error=str(e))
            return False

    async def _reopen_original(self, vacancy_id: str) -> bool:
        self._logger.info("reopening_original", vacancy_id=vacancy_id, dry_run=self.dry_run)
        if self.dry_run:
            return True
        try:
            response = await self.client.open_vacancy(vacancy_id)
            return response.success
        except Exception as e:
            self._logger.error("reopen_original_failed", vacancy_id=vacancy_id, error=str(e))
            return False

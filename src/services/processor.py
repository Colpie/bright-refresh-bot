"""Main job processing logic"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

from ..api.client import BrightStaffingClient, CircuitBreakerOpen
from ..api.models import ApiError, Vacancy, CompleteVacancy
from ..api.vacancy import VacancyService
from ..config import ProcessorConfig
from ..utils.logging import get_logger, JobLogger
from .state import StateManager


# --------------------------------------------------------------------------- #
#  Result data classes
# --------------------------------------------------------------------------- #


@dataclass
class ProcessingResult:
    """Result of processing a single vacancy."""

    original_vacancy_id: str
    success: bool
    new_vacancy_id: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int = 0
    steps_completed: list[str] = field(default_factory=list)


@dataclass
class BatchResult:
    """Aggregate result of a processing run."""

    total: int
    successful: int
    failed: int
    skipped: int
    results: list[ProcessingResult] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Processor
# --------------------------------------------------------------------------- #


class JobProcessor:
    """
    Orchestrates the vacancy refresh workflow:

      1. Fetch all open vacancies
      2. For each: duplicate -> close original
      3. Track state for resume capability
    """

    def __init__(
        self,
        client: BrightStaffingClient,
        config: ProcessorConfig,
        state_manager: StateManager,
        dry_run: bool = False,
        office_id: Optional[str] = None,
    ):
        self.client = client
        self.config = config
        self.state_manager = state_manager
        self.dry_run = dry_run
        self.office_id = office_id

        self.vacancy_service = VacancyService(client)
        self._logger = get_logger("job_processor")
        self._run_id: Optional[str] = None
        self._job_logger: Optional[JobLogger] = None

    @property
    def run_id(self) -> Optional[str]:
        return self._run_id

    # ------------------------------------------------------------------ #
    #  Public entry point
    # ------------------------------------------------------------------ #

    async def run(
        self,
        run_id: Optional[str] = None,
        resume: bool = False,
        limit: Optional[int] = None,
    ) -> BatchResult:
        """Execute the job refresh process."""
        self._run_id = run_id or self._generate_run_id()
        self._job_logger = JobLogger(self._run_id)
        self._limit = limit

        self._logger.info(
            "processing_run_starting",
            run_id=self._run_id,
            dry_run=self.dry_run,
            resume=resume,
            limit=limit,
        )

        try:
            return await (self._resume_run() if resume and run_id else self._fresh_run())

        except CircuitBreakerOpen as exc:
            self._logger.error("circuit_breaker_triggered", run_id=self._run_id, error=str(exc))
            await self.state_manager.fail_run(self._run_id, str(exc))
            raise

        except Exception as exc:
            self._logger.error(
                "processing_run_failed",
                run_id=self._run_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self.state_manager.fail_run(self._run_id, str(exc))
            raise

    # ------------------------------------------------------------------ #
    #  Web session (for multiposting)
    # ------------------------------------------------------------------ #

    async def _ensure_web_session(self) -> None:
        """Log in to BrightStaffing web app for multiposting access."""
        username = self.client.config.web_username
        password = self.client.config.web_password

        if not username or not password:
            self._logger.warning(
                "web_login_skipped",
                reason="BRIGHT_WEB_USERNAME / BRIGHT_WEB_PASSWORD not set, multiposting will be skipped",
            )
            return

        self._logger.info("web_login_attempt", username=username)
        ok = await self.client.web_login(username, password)
        if ok:
            self._logger.info("web_login_success", username=username)
        else:
            self._logger.error("web_login_failed", username=username)

    # ------------------------------------------------------------------ #
    #  Run modes
    # ------------------------------------------------------------------ #

    async def _fresh_run(self) -> BatchResult:
        # Log in to web app for multiposting (non-fatal if credentials missing)
        await self._ensure_web_session()

        self._logger.info("fetching_open_vacancies", run_id=self._run_id)

        # Handle "all" offices: discover all offices, then fetch vacancies
        if self.office_id and self.office_id.strip().lower() == "all":
            offices = await self.vacancy_service.get_all_offices()
            office_ids = ",".join(o.get("uid", "") for o in offices if o.get("uid"))
            self._logger.info(
                "discovered_offices",
                run_id=self._run_id,
                count=len(offices),
                ids=office_ids,
            )
            vacancies = await self.vacancy_service.get_all_open_vacancies(
                office_id=office_ids,
            )
        else:
            vacancies = await self.vacancy_service.get_all_open_vacancies(
                office_id=self.office_id,
            )

        if not vacancies:
            self._logger.warning("no_vacancies_found", run_id=self._run_id)
            return BatchResult(total=0, successful=0, failed=0, skipped=0)

        # Apply limit if specified
        if self._limit and self._limit < len(vacancies):
            self._logger.info(
                "applying_limit",
                run_id=self._run_id,
                total_available=len(vacancies),
                processing=self._limit,
            )
            vacancies = vacancies[:self._limit]

        self._job_logger.log_run_start(len(vacancies))
        await self.state_manager.start_run(self._run_id, len(vacancies))

        for v in vacancies:
            await self.state_manager.add_vacancy_record(self._run_id, v.id)

        return await self._process_vacancies(vacancies)

    async def _resume_run(self) -> BatchResult:
        pending_ids = await self.state_manager.get_pending_vacancies(self._run_id)

        if not pending_ids:
            self._logger.info("no_pending_vacancies", run_id=self._run_id)
            summary = await self.state_manager.get_run_summary(self._run_id)
            if summary:
                return BatchResult(
                    total=summary.total_jobs,
                    successful=summary.successful,
                    failed=summary.failed,
                    skipped=summary.skipped,
                )
            return BatchResult(total=0, successful=0, failed=0, skipped=0)

        self._logger.info("resuming_run", run_id=self._run_id, pending=len(pending_ids))

        vacancies: list[Vacancy] = []
        for vid in pending_ids:
            try:
                complete = await self.vacancy_service.get_complete_vacancy(vid)
                vacancies.append(complete.vacancy)
            except ApiError as exc:
                self._logger.warning("resume_fetch_failed", vacancy_id=vid, error=str(exc))

        return await self._process_vacancies(vacancies)

    # ------------------------------------------------------------------ #
    #  Processing loop
    # ------------------------------------------------------------------ #

    async def _process_vacancies(self, vacancies: list[Vacancy]) -> BatchResult:
        """
        Process vacancies with concurrent execution controlled by batch_size.

        Uses asyncio.Semaphore to limit concurrency while still benefiting from
        parallelism (e.g., 50 vacancies can process in parallel, rate-limited by
        the API client).
        """
        results: list[ProcessingResult] = []
        semaphore = asyncio.Semaphore(self.config.batch_size)
        stop_flag = asyncio.Event()

        async def process_with_semaphore(vacancy: Vacancy, index: int) -> ProcessingResult:
            if stop_flag.is_set():
                return ProcessingResult(
                    original_vacancy_id=vacancy.id,
                    success=False,
                    error_message="Stopped due to previous error",
                )

            async with semaphore:
                if stop_flag.is_set():
                    return ProcessingResult(
                        original_vacancy_id=vacancy.id,
                        success=False,
                        error_message="Stopped due to previous error",
                    )

                self._logger.info(
                    "processing_vacancy",
                    run_id=self._run_id,
                    vacancy_id=vacancy.id,
                    progress=f"{index + 1}/{len(vacancies)}",
                )

                try:
                    result = await self._process_single(vacancy)
                    if not result.success and not self.config.continue_on_error:
                        self._logger.warning("stopping_on_error", vacancy_id=vacancy.id)
                        stop_flag.set()
                    return result
                except CircuitBreakerOpen:
                    stop_flag.set()
                    raise
                except Exception as exc:
                    self._logger.error(
                        "unexpected_processing_error",
                        run_id=self._run_id,
                        vacancy_id=vacancy.id,
                        error=str(exc),
                    )
                    result = ProcessingResult(
                        original_vacancy_id=vacancy.id,
                        success=False,
                        error_message=str(exc),
                    )
                    if not self.config.continue_on_error:
                        stop_flag.set()
                    return result

        # Process all vacancies concurrently with semaphore limiting batch size
        tasks = [process_with_semaphore(v, i) for i, v in enumerate(vacancies)]
        results = []

        for task in tasks:
            results.append(await task)

        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        skipped = 0

        await self.state_manager.complete_run(self._run_id, successful, failed, skipped)

        self._job_logger.log_run_complete(
            total=len(vacancies),
            successful=successful,
            failed=failed,
            skipped=skipped,
            duration_seconds=sum(r.duration_ms for r in results) / 1000,
        )

        return BatchResult(
            total=len(vacancies),
            successful=successful,
            failed=failed,
            skipped=skipped,
            results=results,
        )

    # ------------------------------------------------------------------ #
    #  Single vacancy pipeline
    # ------------------------------------------------------------------ #

    async def _process_single(self, vacancy: Vacancy) -> ProcessingResult:
        """Run the full pipeline for one vacancy.

        Pipeline order:
          1. fetch       - Get complete vacancy data
          2. backup_docs - Download documents locally
          3. duplicate   - Create new vacancy (vacancy_id=0)
          4. open        - Open the new vacancy
          5. province    - Update province_id (non-fatal)
          6. close       - Close the ORIGINAL vacancy
          7. multipost   - Post to Website + VDAB (only after close succeeds)

        Close is done BEFORE multipost so that if close fails we can
        cleanly roll back by closing the new vacancy.  This guarantees
        requirement #5: no duplicate active jobs.
        """
        start = time.monotonic()
        steps: list[str] = []
        new_vacancy_id: Optional[str] = None

        self._job_logger.log_vacancy_start(vacancy.id, vacancy.title)

        try:
            # 1 - Fetch complete data
            complete = await self._step_fetch(vacancy)
            steps.append("fetch")

            # 2 - Backup documents (if any)
            await self._step_backup_documents(vacancy, complete)
            steps.append("backup_docs")

            # 3 - Duplicate
            new_vacancy_id = await self._step_duplicate(vacancy, complete)
            steps.append("duplicate")

            await self.state_manager.update_vacancy_status(
                self._run_id, vacancy.id, "duplicated", new_vacancy_id=new_vacancy_id,
            )

            # 4 - Open new vacancy
            await self._step_open(new_vacancy_id)
            steps.append("open")

            # 5 - Update province (API ignores province_id during creation)
            await self._step_update_province(new_vacancy_id, complete)
            steps.append("province")

            # 6 - Close original (BEFORE multipost for safe rollback)
            closed = await self._step_close(vacancy)
            steps.append("close")

            if not closed:
                # Close failed -> rollback: close the NEW vacancy to prevent duplicates
                await self._step_rollback_new(new_vacancy_id, vacancy.id)
                steps.append("rollback")

                duration_ms = self._elapsed_ms(start)
                await self.state_manager.update_vacancy_status(
                    self._run_id, vacancy.id, "failed",
                    new_vacancy_id=new_vacancy_id,
                    error_message="Close original failed - rolled back new vacancy",
                )
                self._job_logger.log_vacancy_complete(vacancy.id, new_vacancy_id, "failed", duration_ms)

                return ProcessingResult(
                    original_vacancy_id=vacancy.id,
                    success=False,
                    new_vacancy_id=new_vacancy_id,
                    error_message="Close original failed - rolled back new vacancy",
                    duration_ms=duration_ms,
                    steps_completed=steps,
                )

            await self.state_manager.update_vacancy_status(self._run_id, vacancy.id, "closed")

            # 7 - Multipost to Website + VDAB (only after close succeeded)
            try:
                await self._step_multipost(new_vacancy_id)
            except Exception as exc:
                self._logger.error(
                    "multipost_failed",
                    vacancy_id=new_vacancy_id,
                    error=str(exc),
                )
            steps.append("multipost")

            # Done
            duration_ms = self._elapsed_ms(start)
            await self.state_manager.update_vacancy_status(self._run_id, vacancy.id, "completed")
            self._job_logger.log_vacancy_complete(vacancy.id, new_vacancy_id, "success", duration_ms)

            return ProcessingResult(
                original_vacancy_id=vacancy.id,
                success=True,
                new_vacancy_id=new_vacancy_id,
                duration_ms=duration_ms,
                steps_completed=steps,
            )

        except Exception as exc:
            duration_ms = self._elapsed_ms(start)
            last_step = steps[-1] if steps else "init"

            self._job_logger.log_vacancy_error(vacancy.id, exc, last_step)
            await self.state_manager.update_vacancy_status(
                self._run_id, vacancy.id, "failed",
                new_vacancy_id=new_vacancy_id,
                error_message=str(exc),
            )
            self._job_logger.log_vacancy_complete(vacancy.id, new_vacancy_id, "failed", duration_ms)

            return ProcessingResult(
                original_vacancy_id=vacancy.id,
                success=False,
                new_vacancy_id=new_vacancy_id,
                error_message=str(exc),
                duration_ms=duration_ms,
                steps_completed=steps,
            )

    # -- pipeline steps ------------------------------------------------------ #

    async def _step_fetch(self, vacancy: Vacancy) -> CompleteVacancy:
        self._job_logger.log_vacancy_step(vacancy.id, "fetch", "in_progress")

        if self.dry_run:
            self._job_logger.log_dry_run(
                "fetch_complete_vacancy",
                {"vacancy_id": vacancy.id, "title": vacancy.title},
            )
            complete = CompleteVacancy(vacancy=vacancy)
        else:
            # Vacancy already has full data from extraData=true listing.
            # get_complete_vacancy fetches custom fields + VDAB competences.
            complete = await self.vacancy_service.get_complete_vacancy(vacancy)

        self._job_logger.log_vacancy_step(vacancy.id, "fetch", "success")
        return complete

    async def _step_backup_documents(self, vacancy: Vacancy, complete: CompleteVacancy) -> None:
        """Download and save documents from the vacancy before closing it."""
        if not complete.documents:
            return

        self._job_logger.log_vacancy_step(vacancy.id, "backup_docs", "in_progress")

        if self.dry_run:
            self._job_logger.log_dry_run(
                "backup_documents",
                {
                    "vacancy_id": vacancy.id,
                    "document_count": len(complete.documents),
                    "filenames": [d.filename for d in complete.documents],
                },
            )
        else:
            results = await self.vacancy_service.backup_vacancy_documents(
                vacancy.id, complete.documents,
            )
            saved = sum(1 for r in results if r.get("saved"))
            self._job_logger.log_vacancy_step(
                vacancy.id, "backup_docs", "success",
                {"saved": saved, "total": len(complete.documents)},
            )
            return

        self._job_logger.log_vacancy_step(vacancy.id, "backup_docs", "success")

    async def _step_duplicate(self, vacancy: Vacancy, complete: CompleteVacancy) -> str:
        self._job_logger.log_vacancy_step(vacancy.id, "duplicate", "in_progress")

        if self.dry_run:
            self._job_logger.log_dry_run(
                "duplicate_vacancy",
                {"vacancy_id": vacancy.id, "title": vacancy.title, "channels": self.config.multipost_channels},
            )
            new_id = f"DRY_RUN_{vacancy.id}_NEW"
        else:
            new_id = await self.vacancy_service.duplicate_vacancy(
                complete, channels=self.config.multipost_channels,
            )

            if not new_id:
                raise ApiError(
                    status_code=400,
                    message="Duplicate vacancy failed - invalid ID",
                    endpoint="/vacancy/addVacancy",
                )

        self._job_logger.log_vacancy_step(
            vacancy.id, "duplicate", "success", {"new_vacancy_id": new_id},
        )
        return new_id

    async def _step_open(self, new_vacancy_id: str) -> None:
        self._job_logger.log_vacancy_step(new_vacancy_id, "open", "in_progress")

        if self.dry_run:
            self._job_logger.log_dry_run(
                "open_vacancy",
                {"vacancy_id": new_vacancy_id},
            )
        else:
            ok = await self.vacancy_service.open_vacancy(new_vacancy_id)
            if not ok:
                self._job_logger.log_vacancy_step(
                    new_vacancy_id, "open", "failed", {"error": "Open returned false"},
                )
                raise ApiError(
                    status_code=400,
                    message=f"Failed to open vacancy {new_vacancy_id}",
                    endpoint="/vacancy/openVacancy",
                )

        self._job_logger.log_vacancy_step(new_vacancy_id, "open", "success")

    async def _step_update_province(self, new_vacancy_id: str, complete: CompleteVacancy) -> None:
        """Update province_id on the new vacancy after opening.

        The API silently ignores province_id during creation (vacancy_id=0).
        We must send a separate update (vacancy_id=<new_id>) after opening.
        Failures here are non-fatal - they don't prevent closing the original.
        """
        province_id = complete.vacancy.raw_data.get("province_id")
        if not province_id or str(province_id) == "0":
            return

        if self.dry_run:
            self._job_logger.log_dry_run(
                "update_province",
                {"vacancy_id": new_vacancy_id, "province_id": province_id},
            )
            return

        try:
            province_int = int(province_id)
            raw = complete.vacancy.raw_data
            update_payload = {
                "vacancy_id": int(new_vacancy_id),
                "office_id": int(raw.get("office_id", 0)),
                "enterprise_id": int(raw.get("enterprise_id", 0)),
                "function": raw.get("function", ""),
                "jobdomain_id": int(raw.get("jobdomain_id", 0)),
                "language": complete.vacancy.language or "nl",
                "province_id": province_int,
            }

            self._logger.info(
                "province_update_attempt",
                vacancy_id=new_vacancy_id,
                province_id=province_int,
            )

            response = await self.vacancy_service.client.add_vacancy(update_payload)
            self._logger.info(
                "province_update_result",
                vacancy_id=new_vacancy_id,
                province_id=province_int,
                success=response.success,
                response=str(response.data)[:300],
            )

        except CircuitBreakerOpen:
            raise  # Must propagate to stop the run
        except Exception as exc:
            # Non-fatal: log but don't crash the pipeline
            self._logger.error(
                "province_update_error",
                vacancy_id=new_vacancy_id,
                province_id=province_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _step_multipost(self, new_vacancy_id: str) -> None:
        """Trigger multiposting to configured channels (Website, VDAB).

        Uses the internal web endpoint /multiposting/addVacancy which
        requires session-based auth. Failures are non-fatal.
        """
        if not self.config.multipost_channels:
            return

        if self.dry_run:
            self._job_logger.log_dry_run(
                "multipost",
                {"vacancy_id": new_vacancy_id, "channels": self.config.multipost_channels},
            )
            return

        if not self.client._web_session_cookies:
            self._logger.warning(
                "multipost_skipped_no_session",
                vacancy_id=new_vacancy_id,
                reason="No web session - set BRIGHT_WEB_USERNAME and BRIGHT_WEB_PASSWORD",
            )
            return

        channel_names = {1: "Website", 3: "VDAB"}

        for jobboard_id in self.config.multipost_channels:
            channel_name = channel_names.get(jobboard_id, f"channel_{jobboard_id}")
            try:
                response = await self.client.multipost_vacancy(new_vacancy_id, jobboard_id)

                # If "Access denied", session may have expired -> re-login and retry once
                if (not response.success
                        and isinstance(response.data, dict)
                        and response.data.get("status") == "error"):
                    self._logger.warning(
                        "multipost_session_expired",
                        vacancy_id=new_vacancy_id,
                        channel=channel_name,
                    )
                    await self._ensure_web_session()
                    if self.client._web_session_cookies:
                        response = await self.client.multipost_vacancy(
                            new_vacancy_id, jobboard_id,
                        )

                if response.success:
                    self._logger.info(
                        "multipost_success",
                        vacancy_id=new_vacancy_id,
                        channel=channel_name,
                        jobboard_id=jobboard_id,
                    )
                else:
                    self._logger.warning(
                        "multipost_rejected",
                        vacancy_id=new_vacancy_id,
                        channel=channel_name,
                        jobboard_id=jobboard_id,
                        data=str(response.data)[:300],
                    )
            except CircuitBreakerOpen:
                raise
            except Exception as exc:
                self._logger.error(
                    "multipost_error",
                    vacancy_id=new_vacancy_id,
                    channel=channel_name,
                    jobboard_id=jobboard_id,
                    error=str(exc),
                )

    async def _step_close(self, vacancy: Vacancy) -> bool:
        """Close the original vacancy.

        Returns True on success, False on failure.
        On failure the caller should rollback (close the new vacancy).
        """
        self._job_logger.log_vacancy_step(vacancy.id, "close", "in_progress")

        # close_reason should be an integer (closereason_id from API)
        # Default: 3 = "Dubbele vacature" for refresh workflow
        closereason_id = self.config.close_reason
        if isinstance(closereason_id, str):
            closereason_id = int(closereason_id) if closereason_id.isdigit() else 3

        if self.dry_run:
            self._job_logger.log_dry_run(
                "close_vacancy",
                {"vacancy_id": vacancy.id, "closereason_id": closereason_id},
            )
            self._job_logger.log_vacancy_step(vacancy.id, "close", "success")
            return True

        try:
            ok = await self.vacancy_service.close_vacancy(vacancy.id, closereason_id)
            if not ok:
                self._logger.error(
                    "close_vacancy_failed",
                    vacancy_id=vacancy.id,
                    closereason_id=closereason_id,
                )
                self._job_logger.log_vacancy_step(
                    vacancy.id, "close", "failed", {"error": "Close returned false"},
                )
                return False
        except CircuitBreakerOpen:
            raise  # Must propagate to stop the run
        except Exception as exc:
            self._logger.error(
                "close_vacancy_error",
                vacancy_id=vacancy.id,
                closereason_id=closereason_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self._job_logger.log_vacancy_step(
                vacancy.id, "close", "failed", {"error": str(exc)},
            )
            return False

        self._job_logger.log_vacancy_step(vacancy.id, "close", "success")
        return True

    async def _step_rollback_new(self, new_vacancy_id: str, original_id: str) -> None:
        """Rollback: close the NEW vacancy because closing the original failed.

        This ensures no duplicate active jobs remain (requirement #5).
        """
        self._logger.warning(
            "rollback_closing_new_vacancy",
            new_vacancy_id=new_vacancy_id,
            original_id=original_id,
            reason="Could not close original - closing new duplicate to prevent duplicates",
        )

        if self.dry_run:
            self._job_logger.log_dry_run(
                "rollback_close_new",
                {"new_vacancy_id": new_vacancy_id, "original_id": original_id},
            )
            return

        closereason_id = self.config.close_reason
        if isinstance(closereason_id, str):
            closereason_id = int(closereason_id) if closereason_id.isdigit() else 3

        try:
            ok = await self.vacancy_service.close_vacancy(new_vacancy_id, closereason_id)
            if ok:
                self._logger.info(
                    "rollback_success",
                    new_vacancy_id=new_vacancy_id,
                    original_id=original_id,
                )
            else:
                self._logger.error(
                    "rollback_close_failed",
                    new_vacancy_id=new_vacancy_id,
                    original_id=original_id,
                    reason="Both original and new vacancy remain open - manual intervention needed",
                )
        except CircuitBreakerOpen:
            raise
        except Exception as exc:
            self._logger.error(
                "rollback_close_error",
                new_vacancy_id=new_vacancy_id,
                original_id=original_id,
                error=str(exc),
                reason="Both original and new vacancy remain open - manual intervention needed",
            )

    # -- helpers ------------------------------------------------------------- #

    @staticmethod
    def _generate_run_id() -> str:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"run_{ts}_{uuid4().hex[:8]}"

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

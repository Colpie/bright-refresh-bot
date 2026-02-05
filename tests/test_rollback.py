"""Tests for rollback service"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.api.models import ApiResponse
from src.services.rollback import RollbackService, RollbackResult, RollbackSummary


@pytest.mark.asyncio
class TestRollbackService:
    """Tests for RollbackService"""

    @pytest.fixture
    def rollback_service(self, mock_client, state_manager):
        """Create rollback service"""
        return RollbackService(
            client=mock_client,
            state_manager=state_manager,
            dry_run=True,
        )

    async def test_rollback_empty_run(self, rollback_service):
        """Test rollback with no records"""
        result = await rollback_service.rollback_run("nonexistent_run")

        assert result.total_records == 0
        assert result.reopened == 0
        assert result.failed == 0

    async def test_rollback_run_with_completed_records(
        self, rollback_service, state_manager
    ):
        """Test rollback of completed records"""
        run_id = "rollback_test_001"
        await state_manager.start_run(run_id, total_jobs=2)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V002")

        await state_manager.update_vacancy_status(
            run_id, "V001", "duplicated", new_vacancy_id="V101"
        )
        await state_manager.update_vacancy_status(run_id, "V001", "closed")
        await state_manager.update_vacancy_status(run_id, "V001", "completed")

        await state_manager.update_vacancy_status(
            run_id, "V002", "duplicated", new_vacancy_id="V102"
        )
        await state_manager.update_vacancy_status(run_id, "V002", "closed")
        await state_manager.update_vacancy_status(run_id, "V002", "completed")

        await state_manager.complete_run(run_id, successful=2, failed=0, skipped=0)

        result = await rollback_service.rollback_run(run_id)

        assert result.total_records == 2
        assert result.reopened == 2 or result.closed_new == 2

    async def test_rollback_single_vacancy(self, rollback_service, state_manager):
        """Test rollback of single vacancy"""
        run_id = "rollback_test_002"
        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.update_vacancy_status(
            run_id, "V001", "duplicated", new_vacancy_id="V101"
        )
        await state_manager.update_vacancy_status(run_id, "V001", "completed")

        result = await rollback_service.rollback_single(run_id, "V001")

        assert result.success is True
        assert result.vacancy_id == "V001"

    async def test_rollback_single_not_found(self, rollback_service, state_manager):
        """Test rollback of nonexistent vacancy"""
        result = await rollback_service.rollback_single("any_run", "NONEXISTENT")

        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_rollback_pending_skipped(self, rollback_service, state_manager):
        """Test that pending records are skipped"""
        run_id = "rollback_test_003"
        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")

        result = await rollback_service.rollback_single(run_id, "V001")

        assert result.action == "skipped"
        assert result.success is True

    async def test_rollback_with_no_reopen(self, rollback_service, state_manager):
        """Test rollback without reopening"""
        run_id = "rollback_test_004"
        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.update_vacancy_status(
            run_id, "V001", "duplicated", new_vacancy_id="V101"
        )
        await state_manager.update_vacancy_status(run_id, "V001", "closed")
        await state_manager.update_vacancy_status(run_id, "V001", "completed")

        result = await rollback_service.rollback_run(
            run_id,
            reopen_closed=False,
            close_duplicates=True,
        )

        assert result.total_records == 1

    async def test_rollback_with_no_close_duplicates(
        self, rollback_service, state_manager
    ):
        """Test rollback without closing duplicates"""
        run_id = "rollback_test_005"
        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.update_vacancy_status(
            run_id, "V001", "duplicated", new_vacancy_id="V101"
        )
        await state_manager.update_vacancy_status(run_id, "V001", "closed")
        await state_manager.update_vacancy_status(run_id, "V001", "completed")

        result = await rollback_service.rollback_run(
            run_id,
            reopen_closed=True,
            close_duplicates=False,
        )

        assert result.total_records == 1


class TestRollbackResult:
    """Tests for RollbackResult"""

    def test_success_result(self):
        """Test successful rollback result"""
        result = RollbackResult(
            vacancy_id="V001",
            action="reopened",
            success=True,
            message="Reopened successfully",
            new_vacancy_id="V101",
        )

        assert result.success is True
        assert result.action == "reopened"

    def test_failure_result(self):
        """Test failed rollback result"""
        result = RollbackResult(
            vacancy_id="V001",
            action="failed",
            success=False,
            message="API error",
        )

        assert result.success is False
        assert result.action == "failed"


class TestRollbackSummary:
    """Tests for RollbackSummary"""

    def test_summary_counts(self):
        """Test summary with various counts"""
        summary = RollbackSummary(
            run_id="test_run",
            total_records=10,
            reopened=5,
            closed_new=3,
            skipped=1,
            failed=1,
            results=[],
        )

        assert summary.total_records == 10
        assert summary.reopened == 5
        assert summary.closed_new == 3
        assert summary.skipped == 1
        assert summary.failed == 1

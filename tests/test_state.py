"""Tests for state management"""

import pytest
from datetime import datetime, timedelta

from src.services.state import StateManager, ProcessingRecord, RunSummary


@pytest.mark.asyncio
class TestStateManager:
    """Tests for StateManager"""

    async def test_initialize_creates_tables(self, state_manager):
        """Test database initialization"""
        assert state_manager is not None

    async def test_start_run(self, state_manager):
        """Test starting a processing run"""
        run_id = "test_run_001"

        await state_manager.start_run(run_id, total_jobs=100)

        summary = await state_manager.get_run_summary(run_id)
        assert summary is not None
        assert summary.run_id == run_id
        assert summary.total_jobs == 100
        assert summary.status == "running"

    async def test_complete_run(self, state_manager):
        """Test completing a processing run"""
        run_id = "test_run_002"

        await state_manager.start_run(run_id, total_jobs=50)
        await state_manager.complete_run(run_id, successful=45, failed=3, skipped=2)

        summary = await state_manager.get_run_summary(run_id)
        assert summary.successful == 45
        assert summary.failed == 3
        assert summary.skipped == 2
        assert summary.status == "completed_with_errors"

    async def test_complete_run_no_errors(self, state_manager):
        """Test completing a run with no errors"""
        run_id = "test_run_003"

        await state_manager.start_run(run_id, total_jobs=50)
        await state_manager.complete_run(run_id, successful=50, failed=0, skipped=0)

        summary = await state_manager.get_run_summary(run_id)
        assert summary.status == "completed"

    async def test_fail_run(self, state_manager):
        """Test marking a run as failed"""
        run_id = "test_run_004"

        await state_manager.start_run(run_id, total_jobs=50)
        await state_manager.fail_run(run_id, "Circuit breaker triggered")

        summary = await state_manager.get_run_summary(run_id)
        assert summary.status == "failed"

    async def test_add_vacancy_record(self, state_manager):
        """Test adding vacancy records"""
        run_id = "test_run_005"

        await state_manager.start_run(run_id, total_jobs=3)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V002")
        await state_manager.add_vacancy_record(run_id, "V003")

        pending = await state_manager.get_pending_vacancies(run_id)
        assert len(pending) == 3
        assert "V001" in pending
        assert "V002" in pending
        assert "V003" in pending

    async def test_update_vacancy_status_duplicated(self, state_manager):
        """Test updating vacancy to duplicated status"""
        run_id = "test_run_006"

        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")

        await state_manager.update_vacancy_status(
            run_id, "V001", "duplicated", new_vacancy_id="V999"
        )

        record = await state_manager.get_processing_record(run_id, "V001")
        assert record.status == "duplicated"
        assert record.new_vacancy_id == "V999"
        assert record.duplicated_at is not None

    async def test_update_vacancy_status_completed(self, state_manager):
        """Test updating vacancy to completed status"""
        run_id = "test_run_007"

        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")

        await state_manager.update_vacancy_status(run_id, "V001", "completed")

        record = await state_manager.get_processing_record(run_id, "V001")
        assert record.status == "completed"
        assert record.completed_at is not None

    async def test_update_vacancy_status_failed(self, state_manager):
        """Test updating vacancy to failed status"""
        run_id = "test_run_008"

        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")

        await state_manager.update_vacancy_status(
            run_id, "V001", "failed", error_message="API error"
        )

        record = await state_manager.get_processing_record(run_id, "V001")
        assert record.status == "failed"
        assert record.error_message == "API error"

    async def test_get_pending_vacancies_excludes_completed(self, state_manager):
        """Test that completed vacancies are not in pending list"""
        run_id = "test_run_009"

        await state_manager.start_run(run_id, total_jobs=3)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V002")
        await state_manager.add_vacancy_record(run_id, "V003")

        await state_manager.update_vacancy_status(run_id, "V001", "completed")
        await state_manager.update_vacancy_status(run_id, "V002", "failed")

        pending = await state_manager.get_pending_vacancies(run_id)
        assert len(pending) == 1
        assert "V003" in pending

    async def test_get_failed_records(self, state_manager):
        """Test retrieving failed records"""
        run_id = "test_run_010"

        await state_manager.start_run(run_id, total_jobs=3)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V002")
        await state_manager.add_vacancy_record(run_id, "V003")

        await state_manager.update_vacancy_status(run_id, "V001", "completed")
        await state_manager.update_vacancy_status(
            run_id, "V002", "failed", error_message="Error 1"
        )
        await state_manager.update_vacancy_status(
            run_id, "V003", "failed", error_message="Error 2"
        )

        failed = await state_manager.get_failed_records(run_id)
        assert len(failed) == 2

    async def test_get_recent_runs(self, state_manager):
        """Test retrieving recent runs"""
        for i in range(5):
            run_id = f"test_run_recent_{i}"
            await state_manager.start_run(run_id, total_jobs=10)
            await state_manager.complete_run(run_id, successful=10, failed=0, skipped=0)

        runs = await state_manager.get_recent_runs(3)
        assert len(runs) == 3

    async def test_run_summary_success_rate(self, state_manager):
        """Test success rate calculation"""
        run_id = "test_run_rate"

        await state_manager.start_run(run_id, total_jobs=100)
        await state_manager.complete_run(run_id, successful=75, failed=20, skipped=5)

        summary = await state_manager.get_run_summary(run_id)
        assert summary.success_rate == 75.0

    async def test_run_summary_duration(self, state_manager):
        """Test duration calculation"""
        run_id = "test_run_duration"

        await state_manager.start_run(run_id, total_jobs=10)
        await state_manager.complete_run(run_id, successful=10, failed=0, skipped=0)

        summary = await state_manager.get_run_summary(run_id)
        assert summary.duration_seconds is not None
        assert summary.duration_seconds >= 0

    async def test_duplicate_vacancy_record_ignored(self, state_manager):
        """Test that duplicate vacancy records are ignored"""
        run_id = "test_run_dup"

        await state_manager.start_run(run_id, total_jobs=1)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V001")

        pending = await state_manager.get_pending_vacancies(run_id)
        assert len(pending) == 1

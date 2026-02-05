"""Tests for job processor"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.models import Vacancy, VacancyStatus, CompleteVacancy, ApiResponse, ApiError
from src.api.vacancy import VacancyService
from src.services.processor import JobProcessor, ProcessingResult, BatchResult
from src.services.state import StateManager
from src.config import ProcessorConfig


@pytest.mark.asyncio
class TestJobProcessor:
    """Tests for JobProcessor"""

    @pytest.fixture
    def processor_config(self):
        """Create processor config"""
        return ProcessorConfig(
            batch_size=10,
            close_reason="refreshed",
            multipost_channels=["website"],
            dry_run=True,
            circuit_breaker_threshold=5,
            continue_on_error=True,
        )

    @pytest.fixture
    async def processor(self, mock_client, processor_config, state_manager):
        """Create job processor"""
        return JobProcessor(
            client=mock_client,
            config=processor_config,
            state_manager=state_manager,
            dry_run=True,
        )

    async def test_run_with_no_vacancies(self, processor, mock_client):
        """Test run with no vacancies returns empty result"""
        mock_client.get_vacancies = AsyncMock(
            return_value=ApiResponse(success=True, data=[], status_code=200)
        )

        result = await processor.run()

        assert result.total == 0
        assert result.successful == 0
        assert result.failed == 0

    async def test_run_processes_vacancies(self, processor, mock_client, mock_api_responses):
        """Test run processes all vacancies"""
        result = await processor.run()

        assert result.total == 2
        assert result.successful == 2
        assert result.failed == 0

    async def test_run_generates_run_id(self, processor):
        """Test that run generates a unique run ID"""
        await processor.run()

        assert processor.run_id is not None
        assert processor.run_id.startswith("run_")

    async def test_run_with_custom_run_id(self, processor):
        """Test run with custom run ID"""
        custom_id = "custom_run_123"

        await processor.run(run_id=custom_id)

        assert processor.run_id == custom_id

    async def test_processing_result_success(self, processor):
        """Test successful processing result"""
        result = await processor.run()

        for r in result.results:
            assert r.success is True
            assert r.new_vacancy_id is not None
            assert r.duration_ms >= 0
            assert "fetch" in r.steps_completed
            assert "duplicate" in r.steps_completed
            assert "close" in r.steps_completed

    async def test_continue_on_error(self, mock_client, processor_config, state_manager):
        """Test processing continues on error when configured"""
        processor = JobProcessor(
            client=mock_client,
            config=processor_config,
            state_manager=state_manager,
            dry_run=False,
        )

        call_count = 0

        async def mock_add_with_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ApiError(500, "Server error", "/vacancy/addVacancy")
            return ApiResponse(
                success=True, data={"id": "V999"}, status_code=200
            )

        mock_client.add_vacancy = AsyncMock(side_effect=mock_add_with_error)

        result = await processor.run()

        assert result.total == 2
        assert result.successful == 1
        assert result.failed == 1

    async def test_stop_on_error(self, mock_client, processor_config, state_manager):
        """Test processing stops on error when configured"""
        processor_config.continue_on_error = False
        processor = JobProcessor(
            client=mock_client,
            config=processor_config,
            state_manager=state_manager,
            dry_run=False,
        )

        call_count = 0

        async def mock_add_with_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ApiError(500, "Server error", "/vacancy/addVacancy")

        mock_client.add_vacancy = AsyncMock(side_effect=mock_add_with_error)

        result = await processor.run()

        assert result.failed >= 1
        assert call_count >= 1


class TestProcessingResult:
    """Tests for ProcessingResult dataclass"""

    def test_success_result(self):
        """Test successful result"""
        result = ProcessingResult(
            original_vacancy_id="V001",
            success=True,
            new_vacancy_id="V999",
            duration_ms=1500,
            steps_completed=["fetch", "duplicate", "close"],
        )

        assert result.success is True
        assert result.error_message is None

    def test_failure_result(self):
        """Test failed result"""
        result = ProcessingResult(
            original_vacancy_id="V001",
            success=False,
            error_message="API timeout",
            duration_ms=5000,
            steps_completed=["fetch"],
        )

        assert result.success is False
        assert result.error_message == "API timeout"


class TestBatchResult:
    """Tests for BatchResult dataclass"""

    def test_empty_batch(self):
        """Test empty batch result"""
        result = BatchResult(total=0, successful=0, failed=0, skipped=0)

        assert result.total == 0

    def test_mixed_batch(self):
        """Test batch with mixed results"""
        results = [
            ProcessingResult("V001", True, "V101"),
            ProcessingResult("V002", True, "V102"),
            ProcessingResult("V003", False, error_message="Error"),
        ]

        batch = BatchResult(
            total=3,
            successful=2,
            failed=1,
            skipped=0,
            results=results,
        )

        assert batch.total == 3
        assert batch.successful == 2
        assert batch.failed == 1
        assert len(batch.results) == 3

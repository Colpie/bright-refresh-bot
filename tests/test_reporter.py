"""Tests for reporter"""

import pytest
from datetime import datetime, timedelta

from src.services.reporter import Reporter, ProcessingReport, FailureDetail
from src.config import AlertConfig, EmailConfig, WebhookConfig


class TestProcessingReport:
    """Tests for ProcessingReport"""

    @pytest.fixture
    def sample_report(self):
        """Create sample report"""
        return ProcessingReport(
            run_id="test_run_001",
            started_at=datetime(2024, 1, 15, 6, 0, 0),
            completed_at=datetime(2024, 1, 15, 6, 30, 0),
            total_vacancies=100,
            successful=95,
            failed=3,
            skipped=2,
            duration_seconds=1800.0,
            failures=[
                FailureDetail("V001", "API timeout", "duplicate"),
                FailureDetail("V002", "Invalid data", "fetch"),
                FailureDetail("V003", "Close failed", "close"),
            ],
        )

    def test_success_rate(self, sample_report):
        """Test success rate calculation"""
        assert sample_report.success_rate == 95.0

    def test_success_rate_zero_total(self):
        """Test success rate with zero vacancies"""
        report = ProcessingReport(
            run_id="test",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_vacancies=0,
            successful=0,
            failed=0,
            skipped=0,
            duration_seconds=0,
        )
        assert report.success_rate == 0.0

    def test_status_success(self):
        """Test status is success when no failures"""
        report = ProcessingReport(
            run_id="test",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_vacancies=100,
            successful=100,
            failed=0,
            skipped=0,
            duration_seconds=100,
        )
        assert report.status == "success"

    def test_status_failed(self):
        """Test status is failed when all fail"""
        report = ProcessingReport(
            run_id="test",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_vacancies=100,
            successful=0,
            failed=100,
            skipped=0,
            duration_seconds=100,
        )
        assert report.status == "failed"

    def test_status_partial(self, sample_report):
        """Test status is partial with mixed results"""
        assert sample_report.status == "partial"

    def test_status_empty(self):
        """Test status is empty when no vacancies"""
        report = ProcessingReport(
            run_id="test",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_vacancies=0,
            successful=0,
            failed=0,
            skipped=0,
            duration_seconds=0,
        )
        assert report.status == "empty"

    def test_to_markdown(self, sample_report):
        """Test markdown report generation"""
        markdown = sample_report.to_markdown()

        assert "# Job Refresh Report" in markdown
        assert "test_run_001" in markdown
        assert "100" in markdown
        assert "95" in markdown
        assert "3" in markdown
        assert "V001" in markdown
        assert "API timeout" in markdown

    def test_to_markdown_dry_run(self, sample_report):
        """Test markdown includes dry run note"""
        sample_report.dry_run = True
        markdown = sample_report.to_markdown()

        assert "DRY RUN" in markdown

    def test_to_html(self, sample_report):
        """Test HTML report generation"""
        html = sample_report.to_html()

        assert "<html>" in html
        assert "test_run_001" in html
        assert "100" in html
        assert "95" in html

    def test_to_dict(self, sample_report):
        """Test dictionary conversion"""
        data = sample_report.to_dict()

        assert data["run_id"] == "test_run_001"
        assert data["total_vacancies"] == 100
        assert data["successful"] == 95
        assert data["failed"] == 3
        assert data["status"] == "partial"
        assert len(data["failures"]) == 3


@pytest.mark.asyncio
class TestReporter:
    """Tests for Reporter"""

    @pytest.fixture
    def alert_config(self):
        """Create alert config"""
        return AlertConfig(
            enabled=True,
            email=EmailConfig(recipients=["test@example.com"]),
            webhook=WebhookConfig(url=None),
            failure_threshold=10,
            failure_rate_threshold=0.1,
        )

    @pytest.fixture
    def reporter(self, state_manager, alert_config):
        """Create reporter"""
        return Reporter(state_manager, alert_config)

    async def test_generate_report(self, reporter, state_manager):
        """Test report generation"""
        run_id = "report_test_001"
        await state_manager.start_run(run_id, total_jobs=10)
        await state_manager.complete_run(run_id, successful=8, failed=2, skipped=0)

        report = await reporter.generate_report(run_id)

        assert report is not None
        assert report.run_id == run_id
        assert report.total_vacancies == 10
        assert report.successful == 8
        assert report.failed == 2

    async def test_generate_report_not_found(self, reporter):
        """Test report generation for non-existent run"""
        report = await reporter.generate_report("nonexistent_run")

        assert report is None

    async def test_generate_report_with_failures(self, reporter, state_manager):
        """Test report includes failure details"""
        run_id = "report_test_002"
        await state_manager.start_run(run_id, total_jobs=3)
        await state_manager.add_vacancy_record(run_id, "V001")
        await state_manager.add_vacancy_record(run_id, "V002")
        await state_manager.update_vacancy_status(run_id, "V001", "completed")
        await state_manager.update_vacancy_status(
            run_id, "V002", "failed", error_message="Test error"
        )
        await state_manager.complete_run(run_id, successful=1, failed=1, skipped=1)

        report = await reporter.generate_report(run_id)

        assert len(report.failures) == 1
        assert report.failures[0].vacancy_id == "V002"
        assert report.failures[0].error_message == "Test error"

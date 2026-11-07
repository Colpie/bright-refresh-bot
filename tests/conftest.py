"""Pytest configuration and fixtures"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import tempfile
import os

from src.config import Config, ApiConfig, ProcessorConfig, AlertConfig, StateConfig, LoggingConfig
from src.api.client import BrightStaffingClient
from src.api.models import Vacancy, CompleteVacancy, VacancyStatus, ApiResponse
from src.services.state import StateManager


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_config():
    """Create test configuration"""
    return Config(
        api=ApiConfig(
            base_url="https://test.b-bright.be/api",
            access_token="test_token_123",
            api_version="1.0",
            rate_limit=10.0,
            max_retries=2,
            timeout=10,
        ),
        processor=ProcessorConfig(
            batch_size=10,
            close_reason=3,
            multipost_channels=[1, 2],
            dry_run=True,
            circuit_breaker_threshold=5,
            continue_on_error=True,
        ),
        alerts=AlertConfig(enabled=False),
        state=StateConfig(db_path=":memory:"),
        logging=LoggingConfig(level="DEBUG", dir="logs"),
    )


@pytest.fixture
def temp_db_path():
    """Create temporary database path"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
async def state_manager(temp_db_path):
    """Create initialized state manager"""
    manager = StateManager(temp_db_path)
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def sample_vacancies():
    """Create sample vacancy data"""
    return [
        Vacancy(
            id="V001",
            title="Software Developer",
            description="Python developer position",
            status=VacancyStatus.OPEN,
            office_id="O1",
            city="Brussels",
            country="Belgium",
        ),
        Vacancy(
            id="V002",
            title="Project Manager",
            description="IT Project Manager",
            status=VacancyStatus.OPEN,
            office_id="O1",
            city="Antwerp",
            country="Belgium",
        ),
        Vacancy(
            id="V003",
            title="Data Analyst",
            description="Business Intelligence role",
            status=VacancyStatus.OPEN,
            office_id="O2",
            city="Ghent",
            country="Belgium",
        ),
    ]


@pytest.fixture
def sample_complete_vacancy(sample_vacancies):
    """Create sample complete vacancy"""
    return CompleteVacancy(
        vacancy=sample_vacancies[0],
        documents=[],
        custom_fields=[],
        competences=[],
    )


@pytest.fixture
def mock_api_responses():
    """Standard mock API responses"""
    return {
        "vacancies": [
            {
                "id": "V001",
                "title": "Software Developer",
                "status": "open",
                "description": "Python developer",
                "office_id": "O1",
                "city": "Brussels",
            },
            {
                "id": "V002",
                "title": "Project Manager",
                "status": "open",
                "description": "IT PM role",
                "office_id": "O1",
                "city": "Antwerp",
            },
        ],
        "add_vacancy": {"id": "V999", "success": True},
        "close_vacancy": {"success": True},
        "documents": [],
        "custom_fields": [],
        "competences": [],
        "channels": [
            {"channel_id": 1, "name": "Website"},
            {"channel_id": 2, "name": "Vdab"},
        ],
    }


@pytest.fixture
def mock_client(mock_config, mock_api_responses):
    """Create mock API client"""
    client = MagicMock(spec=BrightStaffingClient)
    client.config = mock_config.api
    client.dry_run = True

    async def mock_get_vacancies(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["vacancies"],
            status_code=200,
        )

    async def mock_add_vacancy(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["add_vacancy"],
            status_code=200,
        )

    async def mock_close_vacancy(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["close_vacancy"],
            status_code=200,
        )

    async def mock_get_documents(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["documents"],
            status_code=200,
        )

    async def mock_get_custom_fields(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["custom_fields"],
            status_code=200,
        )

    async def mock_get_competences(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["competences"],
            status_code=200,
        )

    async def mock_get_channels(*args, **kwargs):
        return ApiResponse(
            success=True,
            data=mock_api_responses["channels"],
            status_code=200,
        )

    async def mock_add_document(*args, **kwargs):
        return ApiResponse(success=True, data={"success": True}, status_code=200)

    async def mock_add_custom_field(*args, **kwargs):
        return ApiResponse(success=True, data={"success": True}, status_code=200)

    async def mock_add_competence(*args, **kwargs):
        return ApiResponse(success=True, data={"success": True}, status_code=200)

    client.get_vacancies = AsyncMock(side_effect=mock_get_vacancies)
    client.add_vacancy = AsyncMock(side_effect=mock_add_vacancy)
    client.close_vacancy = AsyncMock(side_effect=mock_close_vacancy)
    client.get_vacancy_documents = AsyncMock(side_effect=mock_get_documents)
    client.get_vacancy_custom_fields = AsyncMock(side_effect=mock_get_custom_fields)
    client.get_vacancy_competences = AsyncMock(side_effect=mock_get_competences)
    client.add_vacancy_document = AsyncMock(side_effect=mock_add_document)
    client.add_vacancy_custom_field = AsyncMock(side_effect=mock_add_custom_field)
    client.add_vacancy_competence = AsyncMock(side_effect=mock_add_competence)
    client.get_channels = AsyncMock(side_effect=mock_get_channels)

    return client

"""Tests for vacancy service"""

import pytest
from unittest.mock import AsyncMock

from src.api.models import ApiResponse, ApiError, VacancyStatus
from src.api.vacancy import VacancyService


@pytest.mark.asyncio
class TestVacancyService:
    """Tests for VacancyService"""

    @pytest.fixture
    def vacancy_service(self, mock_client):
        """Create vacancy service"""
        return VacancyService(mock_client)

    async def test_get_all_open_vacancies(self, vacancy_service, mock_client):
        """Test fetching open vacancies"""
        vacancies = await vacancy_service.get_all_open_vacancies()

        assert len(vacancies) == 2
        assert all(v.status == VacancyStatus.OPEN for v in vacancies)
        mock_client.get_vacancies.assert_called_once()

    async def test_get_all_open_vacancies_filters_closed(self, vacancy_service, mock_client):
        """Test that closed vacancies are filtered out"""
        mock_client.get_vacancies = AsyncMock(
            return_value=ApiResponse(
                success=True,
                data=[
                    {"id": "V001", "title": "Open Job", "status": "open"},
                    {"id": "V002", "title": "Closed Job", "status": "closed"},
                    {"id": "V003", "title": "Another Open", "status": "open"},
                ],
                status_code=200,
            )
        )

        vacancies = await vacancy_service.get_all_open_vacancies()

        assert len(vacancies) == 2
        assert all(v.id in ["V001", "V003"] for v in vacancies)

    async def test_get_all_open_vacancies_by_office(self, vacancy_service, mock_client):
        """Test fetching vacancies by office"""
        await vacancy_service.get_all_open_vacancies(office_id="O1")

        mock_client.get_vacancies_by_office.assert_called_once_with("O1", extra_data=True)

    async def test_get_all_open_vacancies_empty(self, vacancy_service, mock_client):
        """Test with no vacancies"""
        mock_client.get_vacancies = AsyncMock(
            return_value=ApiResponse(success=True, data=[], status_code=200)
        )

        vacancies = await vacancy_service.get_all_open_vacancies()

        assert len(vacancies) == 0

    async def test_get_all_open_vacancies_api_failure(self, vacancy_service, mock_client):
        """Test handling API failure"""
        mock_client.get_vacancies = AsyncMock(
            return_value=ApiResponse(success=False, data="Error", status_code=500)
        )

        vacancies = await vacancy_service.get_all_open_vacancies()

        assert len(vacancies) == 0

    async def test_get_complete_vacancy(self, vacancy_service, mock_client):
        """Test fetching complete vacancy data"""
        from src.api.models import Vacancy
        vacancy = Vacancy(id="V001", title="Test Job")

        complete = await vacancy_service.get_complete_vacancy(vacancy)

        assert complete.vacancy.id == "V001"
        assert complete.vacancy.title == "Test Job"
        mock_client.get_vacancy_documents.assert_called_once_with("V001")
        mock_client.get_vacancy_custom_fields.assert_called_once_with("V001")
        mock_client.get_vacancy_competences.assert_called_once_with("V001")

    async def test_get_complete_vacancy_not_found(self, vacancy_service, mock_client):
        """Test complete vacancy with missing related data still returns"""
        from src.api.models import Vacancy
        vacancy = Vacancy(id="V999", title="Missing")

        mock_client.get_vacancy_documents = AsyncMock(
            return_value=ApiResponse(success=True, data=[], status_code=200)
        )
        mock_client.get_vacancy_custom_fields = AsyncMock(
            return_value=ApiResponse(success=True, data=[], status_code=200)
        )
        mock_client.get_vacancy_competences = AsyncMock(
            return_value=ApiResponse(success=True, data=[], status_code=200)
        )

        complete = await vacancy_service.get_complete_vacancy(vacancy)

        assert complete.vacancy.id == "V999"
        assert len(complete.documents) == 0

    async def test_duplicate_vacancy(self, vacancy_service, mock_client, sample_complete_vacancy):
        """Test duplicating a vacancy"""
        new_id = await vacancy_service.duplicate_vacancy(
            sample_complete_vacancy,
            channels=["website", "vdab"],
        )

        assert new_id == "V999"
        mock_client.add_vacancy.assert_called_once()

    async def test_duplicate_vacancy_failure(self, vacancy_service, mock_client, sample_complete_vacancy):
        """Test duplicate failure raises error"""
        mock_client.add_vacancy = AsyncMock(
            return_value=ApiResponse(success=False, data="Error", status_code=400)
        )

        with pytest.raises(ApiError):
            await vacancy_service.duplicate_vacancy(sample_complete_vacancy)

    async def test_close_vacancy(self, vacancy_service, mock_client):
        """Test closing a vacancy"""
        result = await vacancy_service.close_vacancy("V001", "refreshed")

        assert result is True
        mock_client.close_vacancy.assert_called_once_with("V001", "refreshed", None)

    async def test_close_vacancy_failure(self, vacancy_service, mock_client):
        """Test close failure returns False"""
        mock_client.close_vacancy = AsyncMock(
            return_value=ApiResponse(success=False, data="Error", status_code=400)
        )

        result = await vacancy_service.close_vacancy("V001", "refreshed")

        assert result is False

    async def test_get_channels(self, vacancy_service, mock_client):
        """Test fetching channels"""
        channels = await vacancy_service.get_channels()

        assert len(channels) == 2
        assert channels[0].name == "Website"
        assert channels[1].name == "Vdab"

    async def test_get_close_reasons(self, vacancy_service, mock_client):
        """Test fetching close reasons"""
        mock_client.get_close_reasons = AsyncMock(
            return_value=ApiResponse(
                success=True,
                data=[
                    {"id": "1", "name": "Filled"},
                    {"id": "2", "name": "Refreshed"},
                ],
                status_code=200,
            )
        )

        reasons = await vacancy_service.get_close_reasons()

        assert len(reasons) == 2

"""Tests for data models"""

import pytest
from datetime import datetime

from src.api.models import (
    Vacancy,
    VacancyStatus,
    VacancyDocument,
    VacancyCustomField,
    VdabCompetence,
    CompleteVacancy,
    Channel,
    ApiError,
    ApiResponse,
)


class TestVacancy:
    """Tests for Vacancy model"""

    def test_from_api_basic(self):
        """Test basic vacancy creation from API data"""
        data = {
            "id": "V001",
            "title": "Software Developer",
            "description": "Python role",
            "status": "open",
        }

        vacancy = Vacancy.from_api(data)

        assert vacancy.id == "V001"
        assert vacancy.title == "Software Developer"
        assert vacancy.description == "Python role"
        assert vacancy.status == VacancyStatus.OPEN

    def test_from_api_full(self):
        """Test full vacancy creation with all fields"""
        data = {
            "id": "V002",
            "title": "Project Manager",
            "description": "PM role",
            "status": "open",
            "office_id": "O1",
            "office_name": "Brussels Office",
            "city": "Brussels",
            "postal_code": "1000",
            "country": "Belgium",
            "contract_type": "permanent",
            "salary_min": 3000,
            "salary_max": 5000,
            "enterprise_id": "E1",
            "enterprise_name": "Tech Corp",
            "created_at": "2024-01-15T10:00:00Z",
        }

        vacancy = Vacancy.from_api(data)

        assert vacancy.id == "V002"
        assert vacancy.office_id == "O1"
        assert vacancy.city == "Brussels"
        assert vacancy.salary_min == 3000
        assert vacancy.salary_max == 5000
        assert vacancy.enterprise_name == "Tech Corp"

    def test_from_api_alternate_field_names(self):
        """Test vacancy creation with real API field names (uid, function, work_*)"""
        data = {
            "uid": "V003",
            "function": "Analyst",
            "work_post": "2000",
            "regime_id": "full-time",
            "experience_id": "2 years",
        }

        vacancy = Vacancy.from_api(data)

        assert vacancy.id == "V003"
        assert vacancy.title == "Analyst"
        assert vacancy.postal_code == "2000"
        assert vacancy.working_hours == "full-time"
        assert vacancy.experience_required == "2 years"

    def test_from_api_unknown_status(self):
        """Test vacancy with unknown status defaults to OPEN"""
        data = {
            "id": "V004",
            "title": "Test",
            "status": "unknown_status",
        }

        vacancy = Vacancy.from_api(data)

        assert vacancy.status == VacancyStatus.OPEN

    def test_to_api_dict(self):
        """Test converting vacancy to API format (uses API field names)"""
        vacancy = Vacancy(
            id="V001",
            title="Developer",
            description="Python dev",
            office_id="O1",
            city="Brussels",
            channels=["website", "vdab"],
        )

        api_dict = vacancy.to_api_dict()

        assert api_dict["function"] == "Developer"
        assert api_dict["desc_function"] == "Python dev"
        assert api_dict["office_id"] == "O1"
        assert api_dict["work_city"] == "Brussels"
        assert api_dict["channels"] == ["website", "vdab"]
        assert "id" not in api_dict
        assert "status" not in api_dict

    def test_to_api_dict_filters_unknown_raw_data_fields(self):
        """Test that unknown raw_data fields are not sent to the API"""
        vacancy = Vacancy(
            id="V001",
            title="Developer",
            raw_data={"custom_field": "custom_value", "another": 123},
        )

        api_dict = vacancy.to_api_dict()

        assert "custom_field" not in api_dict
        assert "another" not in api_dict


class TestVacancyDocument:
    """Tests for VacancyDocument model"""

    def test_from_api(self):
        """Test document creation from API"""
        data = {
            "id": "D001",
            "filename": "cv.pdf",
            "content_type": "application/pdf",
            "url": "https://example.com/cv.pdf",
        }

        doc = VacancyDocument.from_api(data, "V001")

        assert doc.id == "D001"
        assert doc.vacancy_id == "V001"
        assert doc.filename == "cv.pdf"
        assert doc.content_type == "application/pdf"

    def test_from_api_alternate_names(self):
        """Test document with alternate field names"""
        data = {
            "id": "D002",
            "name": "resume.docx",
            "mime_type": "application/docx",
        }

        doc = VacancyDocument.from_api(data, "V002")

        assert doc.filename == "resume.docx"
        assert doc.content_type == "application/docx"


class TestVacancyCustomField:
    """Tests for VacancyCustomField model"""

    def test_from_api(self):
        """Test custom field creation from real API structure"""
        data = {
            "uid": "571",
            "vacancy_id": "571",
            "free1": "Engineering",
            "free2": "",
            "text1": "Notes here",
            "desc1": "",
        }

        cf = VacancyCustomField.from_api(data)

        assert cf.uid == "571"
        assert cf.vacancy_id == "571"
        assert cf.free1 == "Engineering"
        assert cf.text1 == "Notes here"

    def test_from_api_to_dict(self):
        """Test to_dict excludes empty fields"""
        data = {
            "uid": "572",
            "vacancy_id": "572",
            "free1": "Value1",
            "free2": "",
            "text1": "Text",
        }

        cf = VacancyCustomField.from_api(data)
        result = cf.to_dict()

        assert result["free1"] == "Value1"
        assert result["text1"] == "Text"
        assert "free2" not in result


class TestChannel:
    """Tests for Channel model"""

    def test_from_api(self):
        """Test channel creation"""
        data = {
            "channel_id": 1,
            "name": "Website",
            "active": True,
        }

        channel = Channel.from_api(data)

        assert channel.channel_id == 1
        assert channel.name == "Website"
        assert channel.active is True


class TestApiError:
    """Tests for ApiError"""

    def test_is_retryable(self):
        """Test retryable error detection"""
        error_429 = ApiError(429, "Rate limited", "/test")
        error_500 = ApiError(500, "Server error", "/test")
        error_400 = ApiError(400, "Bad request", "/test")

        assert error_429.is_retryable is True
        assert error_500.is_retryable is True
        assert error_400.is_retryable is False

    def test_is_auth_error(self):
        """Test auth error detection"""
        error_401 = ApiError(401, "Unauthorized", "/test")
        error_403 = ApiError(403, "Forbidden", "/test")

        assert error_401.is_auth_error is True
        assert error_403.is_auth_error is False

    def test_str_representation(self):
        """Test error string format"""
        error = ApiError(404, "Not found", "/vacancy/get")

        assert "404" in str(error)
        assert "Not found" in str(error)
        assert "/vacancy/get" in str(error)


class TestCompleteVacancy:
    """Tests for CompleteVacancy model"""

    def test_properties(self):
        """Test convenience properties"""
        vacancy = Vacancy(id="V001", title="Developer")
        complete = CompleteVacancy(vacancy=vacancy)

        assert complete.id == "V001"
        assert complete.title == "Developer"

    def test_with_related_data(self):
        """Test with documents and fields"""
        vacancy = Vacancy(id="V001", title="Developer")
        docs = [VacancyDocument(id="D1", vacancy_id="V001", filename="cv.pdf", content_type="application/pdf")]
        fields = [VacancyCustomField(uid="F1", vacancy_id="V001", free1="IT")]
        comps = [VdabCompetence(id="C1", name="Python")]

        complete = CompleteVacancy(
            vacancy=vacancy,
            documents=docs,
            custom_fields=fields,
            competences=comps,
        )

        assert len(complete.documents) == 1
        assert len(complete.custom_fields) == 1
        assert len(complete.competences) == 1

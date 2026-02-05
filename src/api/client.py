"""HTTP client for Bright Staffing API"""

import asyncio
import json
import time
from typing import Any, Optional, Union

import httpx

from ..config import ApiConfig
from ..utils.logging import get_logger
from .models import ApiError, ApiResponse


# --------------------------------------------------------------------------- #
#  Rate limiter
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Token-bucket rate limiter for async requests."""

    def __init__(self, requests_per_second: float):
        self._rate = requests_per_second
        self._tokens = 1.0
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(1.0, self._tokens + (now - self._last_update) * self._rate)
            self._last_update = now

            if self._tokens < 1.0:
                await asyncio.sleep((1.0 - self._tokens) / self._rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# --------------------------------------------------------------------------- #
#  Circuit breaker
# --------------------------------------------------------------------------- #


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker threshold is exceeded."""


class CircuitBreaker:
    """Stops processing after N consecutive failures."""

    def __init__(self, threshold: int = 10):
        self.threshold = threshold
        self.consecutive_failures = 0
        self._lock = asyncio.Lock()

    async def record_success(self) -> None:
        async with self._lock:
            self.consecutive_failures = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.threshold:
                raise CircuitBreakerOpen(
                    f"Circuit breaker opened after {self.consecutive_failures} "
                    f"consecutive failures (threshold: {self.threshold})"
                )

    @property
    def failure_count(self) -> int:
        return self.consecutive_failures


# --------------------------------------------------------------------------- #
#  API client
# --------------------------------------------------------------------------- #


class BrightStaffingClient:
    """
    Async HTTP client for the Bright Staffing API.

    Features:
      - Token-based authentication (multipart/form-data)
      - Rate limiting with token bucket
      - Exponential backoff retries
      - Circuit breaker for cascading failure protection
      - Dry-run mode (returns mock data, no HTTP calls)
    """

    def __init__(
        self,
        config: ApiConfig,
        dry_run: bool = False,
        circuit_breaker_threshold: int = 10,
    ):
        self.config = config
        self.dry_run = dry_run

        self._base_url = config.base_url.rstrip("/")
        self._access_token = config.access_token
        self._api_version = config.api_version
        self._api_lang = config.api_lang

        self._rate_limiter = RateLimiter(config.rate_limit)
        self._circuit_breaker = CircuitBreaker(circuit_breaker_threshold)
        self._logger = get_logger("api_client")
        self._client: Optional[httpx.AsyncClient] = None

    # -- context manager ----------------------------------------------------- #

    async def __aenter__(self) -> "BrightStaffingClient":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- internal helpers ---------------------------------------------------- #

    def _build_form_data(self, params: dict) -> dict:
        """Build multipart/form-data with required auth fields."""
        form: dict[str, str] = {
            "api_access_token": self._access_token,
            "api_version": self._api_version,
        }
        if self._api_lang:
            form["api_lang"] = self._api_lang

        for key, value in params.items():
            if value is None:
                continue
            form[key] = json.dumps(value) if isinstance(value, (list, dict)) else str(value)

        return form

    def _backoff_seconds(self, retry: int) -> float:
        """Exponential backoff capped at max_backoff."""
        return min(
            self.config.backoff_base * (self.config.backoff_multiplier ** retry),
            self.config.max_backoff,
        )

    # -- core request -------------------------------------------------------- #

    async def request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        *,
        _retry: int = 0,
    ) -> ApiResponse:
        """
        Make an authenticated POST request.

        Raises:
            ApiError:            on non-retryable API errors
            CircuitBreakerOpen:  after too many consecutive failures
            RuntimeError:        if called outside async context manager
        """
        params = params or {}
        url = f"{self._base_url}{endpoint}"

        # --- dry-run shortcut ---
        if self.dry_run:
            self._logger.info("dry_run_request", endpoint=endpoint, params=list(params.keys()))
            return ApiResponse(success=True, data=_mock_response(endpoint), status_code=200)

        # --- rate limiting ---
        await self._rate_limiter.acquire()

        if not self._client:
            raise RuntimeError("Client not initialised. Use 'async with' context manager.")

        start = time.monotonic()

        try:
            response = await self._client.post(url, data=self._build_form_data(params))
            elapsed_ms = int((time.monotonic() - start) * 1000)

            self._logger.debug(
                "api_response",
                endpoint=endpoint,
                status_code=response.status_code,
                duration_ms=elapsed_ms,
            )

            # --- success ---
            if response.status_code == 200:
                await self._circuit_breaker.record_success()
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                return ApiResponse(
                    success=True,
                    data=data,
                    status_code=200,
                    raw_response=data if isinstance(data, dict) else None,
                )

            # --- error ---
            error = ApiError(
                status_code=response.status_code,
                message=response.text,
                endpoint=endpoint,
            )

            if error.is_auth_error:
                self._logger.error("auth_failure", endpoint=endpoint)
                raise error

            if error.is_retryable and _retry < self.config.max_retries:
                await self._circuit_breaker.record_failure()
                wait = self._backoff_seconds(_retry)
                self._logger.warning(
                    "retrying",
                    endpoint=endpoint,
                    status=response.status_code,
                    attempt=_retry + 1,
                    wait_s=wait,
                )
                await asyncio.sleep(wait)
                return await self.request(endpoint, params, _retry=_retry + 1)

            await self._circuit_breaker.record_failure()
            raise error

        except httpx.TimeoutException as exc:
            if _retry < self.config.max_retries:
                await self._circuit_breaker.record_failure()
                wait = self._backoff_seconds(_retry)
                self._logger.warning("timeout_retry", endpoint=endpoint, attempt=_retry + 1)
                await asyncio.sleep(wait)
                return await self.request(endpoint, params, _retry=_retry + 1)

            raise ApiError(status_code=408, message=str(exc), endpoint=endpoint)

        except httpx.HTTPError as exc:
            raise ApiError(status_code=0, message=str(exc), endpoint=endpoint)

    # -- convenience methods ------------------------------------------------- #

    async def get_vacancies(self, filters: Optional[dict] = None) -> ApiResponse:
        return await self.request("/vacancy/getVacancies", filters)

    async def get_vacancies_by_office(
        self, office_id: str, extra_data: bool = False, page: Optional[int] = None,
    ) -> ApiResponse:
        params: dict[str, Any] = {"office_id": office_id}
        if extra_data:
            params["extraData"] = "true"
        if page is not None:
            params["page"] = page
        return await self.request("/vacancy/getVacanciesByOffice", params)

    async def add_vacancy(self, vacancy_data: dict) -> ApiResponse:
        """Create or update a vacancy.

        The API expects the vacancy data wrapped in a 'vacancy' key.
        The vacancy object is then JSON-encoded as a string in multipart/form-data.

        Args:
            vacancy_data: Dict with vacancy fields. Include vacancy_id=0 to create new,
                         or vacancy_id=<existing_id> to update.

        Returns:
            ApiResponse with new/updated vacancy ID.
        """
        # API expects: {"vacancy": {vacancy_data}}
        # The _build_form_data method will JSON-encode the inner dict
        return await self.request("/vacancy/addVacancy", {"vacancy": vacancy_data})

    async def close_vacancy(
        self,
        vacancy_id: str,
        closereason_id: int,
        extra_info: Optional[str] = None,
    ) -> ApiResponse:
        """Close a vacancy.

        Args:
            vacancy_id: The vacancy UID to close.
            closereason_id: Close reason ID (from getVacancyCloseReasons endpoint).
            extra_info: Optional extra information about the closing.

        Returns:
            ApiResponse with updated_vacancy_id.
        """
        params: dict[str, Any] = {
            "vacancy_id": vacancy_id,
            "closereason_id": closereason_id,
        }
        if extra_info:
            params["extra_info"] = extra_info
        return await self.request("/vacancy/closeVacancy", params)

    async def open_vacancy(self, vacancy_id: str) -> ApiResponse:
        return await self.request("/vacancy/openVacancy", {"vacancy_id": vacancy_id})

    async def get_vacancy_documents(self, vacancy_id: str) -> ApiResponse:
        return await self.request("/vacancy/getVacancyDocuments", {"vacancy_id": vacancy_id})

    async def get_vacancy_custom_fields(self, vacancy_id: str) -> ApiResponse:
        return await self.request("/vacancy/getVacancyCustomFields", {"vacancy_id": vacancy_id})

    async def get_vacancy_competences(self, vacancy_id: str) -> ApiResponse:
        return await self.request("/vacancy/getVacancyVdabCompetences", {"vacancy_id": vacancy_id})

    async def get_document(self, document_id: str) -> ApiResponse:
        """Fetch a stored document with its base64 content."""
        return await self.request("/document/getDocument", {"document_id": document_id})

    # -- reference data ------------------------------------------------------ #

    async def get_channels(self) -> ApiResponse:
        return await self.request("/channel/getChannels")

    async def get_close_reasons(self) -> ApiResponse:
        return await self.request("/vacancy/getVacancyCloseReasons")

    async def get_offices(self) -> ApiResponse:
        return await self.request("/office/getOffices")


# --------------------------------------------------------------------------- #
#  Mock responses for dry-run mode
# --------------------------------------------------------------------------- #

_MOCK_RESPONSES: dict[str, Any] = {
    "getVacancies": {
        "vacancies": [
            {
                "uid": "V001",
                "function": "Mock Software Developer",
                "status": "open",
                "desc_function": "Mock job description",
                "office_id": "1",
                "enterprise_id": "1",
                "jobdomain_id": "9",
                "language_id": "1",
            },
            {
                "uid": "V002",
                "function": "Mock Project Manager",
                "status": "open",
                "desc_function": "Mock job description",
                "office_id": "1",
                "enterprise_id": "1",
                "jobdomain_id": "9",
                "language_id": "1",
            },
        ]
    },
    "getVacanciesByOffice": {
        "vacancies": [
            {
                "uid": "V001",
                "function": "Mock Software Developer",
                "status": "open",
                "desc_function": "Mock job description",
                "office_id": "1",
                "enterprise_id": "1",
                "jobdomain_id": "9",
                "language_id": "1",
            },
        ]
    },
    "addVacancy": {"uid": "V999", "vacancy_id": "V999"},
    "addVacancyDocument": {"success": True},
    "addVacancyCustomField": {"success": True},
    "addVacancyVdabCompetence": {"success": True},
    "closeVacancy": {"updated_vacancy_id": 0},
    "openVacancy": {"updated_vacancy_id": 0},
    "getDocument": {"document": {"file_name": "mock.pdf", "content": "", "mime_type": "application/pdf", "file_size": "0 KB"}},
    "getVacancyDocuments": {"documents": []},
    "getVacancyCustomFields": {"custom_fields": []},
    "getVacancyVdabCompetences": {"VDAB competences": []},
    "getChannels": [
        {"channel_id": "1", "name": "Website"},
        {"channel_id": "2", "name": "Vdab"},
    ],
    "getVacancyCloseReasons": {
        "closereasons": [
            {"closereason_id": "1", "name": "Vacature werd ingevuld"},
            {"closereason_id": "2", "name": "Vacature on hold"},
        ]
    },
}


def _mock_response(endpoint: str) -> Any:
    """Return mock data for a given endpoint path."""
    for key, data in _MOCK_RESPONSES.items():
        if endpoint.endswith(key):
            return data
    return {"success": True, "mock": True}

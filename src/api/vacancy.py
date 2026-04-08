"""Vacancy service for Bright Staffing API operations.

All vacancy data (custom fields, VDAB competences, channels) is sent through
a single addVacancy call. There are no separate write endpoints for these.
Documents are automatically backed up during refresh (downloaded and saved locally)
because the API has no vacancy document upload endpoint.
"""

import asyncio
import base64
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.logging import get_logger
from .client import BrightStaffingClient
from .models import (
    ApiError,
    ApiResponse,
    Channel,
    CompleteVacancy,
    Vacancy,
    VacancyCustomField,
    VacancyDocument,
    VacancyStatus,
    VdabCompetence,
)


class VacancyService:
    """
    High-level service for vacancy operations.

    Wraps the raw API client with business logic for fetching,
    duplicating, opening and closing vacancies.
    """

    def __init__(self, client: BrightStaffingClient):
        self.client = client
        self._logger = get_logger("vacancy_service")
        self._user_map: dict[str, str] = {}  # email -> user uid

    # ------------------------------------------------------------------ #
    #  Read operations
    # ------------------------------------------------------------------ #

    async def get_all_open_vacancies(
        self,
        office_id: Optional[str] = None,
    ) -> list[Vacancy]:
        """Fetch all open vacancies with full field data (extraData=true).

        Args:
            office_id: Single office ID, comma-separated IDs ("1,5,7"),
                      or "all" to discover and fetch from every office.

        Uses extraData to get salary, competences, studies, work_country_iso,
        and other fields not included in the basic response.
        """
        office_ids = self._resolve_office_ids(office_id)

        if office_ids:
            all_vacancies: list[Vacancy] = []
            for oid in office_ids:
                # Paginate: API returns max 100 items per page
                page = 1
                office_open = 0
                office_total = 0
                while True:
                    response = await self.client.get_vacancies_by_office(
                        oid, extra_data=True, page=page,
                    )
                    if not response.success:
                        self._logger.error(
                            "get_vacancies_failed", office_id=oid,
                            page=page, error=response.data,
                        )
                        break
                    raw_list = _extract_list(response.data, "vacancies")
                    if not raw_list:
                        break  # No more pages
                    office_total += len(raw_list)
                    for item in raw_list:
                        v = Vacancy.from_api(item)
                        if v.status == VacancyStatus.OPEN:
                            all_vacancies.append(v)
                            office_open += 1
                    # If we got fewer than 100 items, this was the last page
                    if len(raw_list) < 100:
                        break
                    page += 1
                self._logger.info(
                    "office_vacancies_fetched",
                    office_id=oid,
                    pages_fetched=page,
                    total_in_response=office_total,
                    open_count=office_open,
                )
            self._logger.info(
                "vacancies_fetched",
                offices=len(office_ids),
                total=len(all_vacancies),
                open_count=len(all_vacancies),
            )
            return all_vacancies
        else:
            response = await self.client.get_vacancies({"extraData": "true"})
            if not response.success:
                self._logger.error("get_vacancies_failed", error=response.data)
                return []
            raw_list = _extract_list(response.data, "vacancies")
            vacancies = [
                Vacancy.from_api(item)
                for item in raw_list
                if item.get("status", "").lower() == "open"
            ]
            self._logger.info(
                "vacancies_fetched", total=len(raw_list), open_count=len(vacancies),
            )
            return vacancies

    async def get_all_offices(self) -> list[dict]:
        """Discover all available offices."""
        response = await self.client.get_offices()
        if not response.success:
            self._logger.error("get_offices_failed", error=response.data)
            return []
        offices = _extract_list(response.data, "offices")
        active = [o for o in offices if o.get("is_active") == "1"]
        self._logger.info("offices_fetched", total=len(offices), active=len(active))
        return active

    def _resolve_office_ids(self, office_id: Optional[str]) -> list[str]:
        """Parse office_id config into list of IDs."""
        if not office_id:
            return []
        office_id = office_id.strip()
        if office_id.lower() == "all":
            return []  # Caller must use get_all_offices first
        return [oid.strip() for oid in office_id.split(",") if oid.strip()]

    async def get_complete_vacancy(self, vacancy: Vacancy) -> CompleteVacancy:
        """
        Enrich a vacancy with custom fields, VDAB competences, and documents.

        The vacancy should already have full data from extraData=true listing.
        This fetches the additional data needed for duplication in parallel.
        Documents are fetched for backup but cannot be transferred via API.
        """
        vacancy_id = vacancy.id

        docs_resp, fields_resp, comps_resp = await asyncio.gather(
            self.client.get_vacancy_documents(vacancy_id),
            self.client.get_vacancy_custom_fields(vacancy_id),
            self.client.get_vacancy_competences(vacancy_id),
            return_exceptions=True,
        )

        documents = _safe_parse_list(docs_resp, lambda d: VacancyDocument.from_api(d, vacancy_id), "documents")
        custom_fields = _safe_parse_list(fields_resp, VacancyCustomField.from_api, "custom_fields")
        competences = _safe_parse_list(comps_resp, VdabCompetence.from_api, "VDAB competences")

        self._logger.debug(
            "complete_vacancy_fetched",
            vacancy_id=vacancy_id,
            documents=len(documents),
            custom_fields=len(custom_fields),
            competences=len(competences),
        )

        return CompleteVacancy(
            vacancy=vacancy,
            documents=documents,
            custom_fields=custom_fields,
            competences=competences,
        )

    # ------------------------------------------------------------------ #
    #  User lookup (for consultant assignment)
    # ------------------------------------------------------------------ #

    async def _ensure_user_map(self) -> None:
        """Fetch users once and build email->uid lookup for consultant assignment."""
        if self._user_map:
            return
        response = await self.client.get_users()
        if not response.success:
            self._logger.warning("get_users_failed", error=response.data)
            return
        users = _extract_list(response.data, "users")
        for user in users:
            mail = (user.get("mail") or "").strip().lower()
            uid = user.get("uid")
            if mail and uid:
                self._user_map[mail] = str(uid)
        self._logger.info("user_map_loaded", count=len(self._user_map))

    def _resolve_assigned_user_id(self, vacancy: Vacancy) -> Optional[str]:
        """Look up the assigned user ID from the vacancy's assigned_user_mail."""
        mail = (vacancy.raw_data.get("assigned_user_mail") or "").strip().lower()
        if not mail:
            return None
        return self._user_map.get(mail)

    # ------------------------------------------------------------------ #
    #  Write operations
    # ------------------------------------------------------------------ #

    async def duplicate_vacancy(
        self,
        complete_vacancy: CompleteVacancy,
        channels: Optional[list[int]] = None,
    ) -> str:
        """
        Create a full duplicate of a vacancy via a single addVacancy call.

        Everything is sent in one payload:
        - All vacancy fields (from extraData listing)
        - VDAB competences (from getVacancyVdabCompetences)
        - Custom fields (from getVacancyCustomFields)
        - Channel IDs for multiposting

        Returns the new vacancy ID.
        Raises ApiError if creation fails.
        """
        payload = complete_vacancy.build_duplication_payload(channels=channels)

        # Inject assigned user (consultant) ID from email lookup
        # CRITICAL: The field name is "user_consulent_id" not "assigned_user_id"!
        await self._ensure_user_map()
        user_id = self._resolve_assigned_user_id(complete_vacancy.vacancy)
        if user_id:
            payload["user_consulent_id"] = user_id
            self._logger.info(
                "consultant_assigned",
                vacancy_id=complete_vacancy.id,
                email=complete_vacancy.vacancy.raw_data.get("assigned_user_mail"),
                user_id=user_id,
            )
        else:
            self._logger.warning(
                "consultant_not_found",
                vacancy_id=complete_vacancy.id,
                email=complete_vacancy.vacancy.raw_data.get("assigned_user_mail"),
                user_map_size=len(self._user_map),
            )

        # Log payload summary for debugging
        desc_fields = {k: len(v) if v else 0 for k, v in payload.items() if 'desc' in k}
        self._logger.info(
            "duplicating_vacancy_payload",
            vacancy_id=complete_vacancy.id,
            payload_fields=len(payload),
            has_assigned_user=("user_consulent_id" in payload),
            has_study_id=("study_id" in payload),
            desc_fields=desc_fields,
        )

        response = await self.client.add_vacancy(payload)

        if not response.success:
            raise ApiError(
                status_code=400,
                message=f"Failed to create vacancy: {response.data}",
                endpoint="/vacancy/addVacancy",
            )

        new_id = _extract_id(response.data)
        if not new_id:
            raise ApiError(
                status_code=500,
                message="No vacancy ID returned from API",
                endpoint="/vacancy/addVacancy",
            )

        self._logger.info(
            "vacancy_duplicated",
            original_id=complete_vacancy.id,
            new_id=new_id,
            title=complete_vacancy.title,
            competences=len(complete_vacancy.competences),
            custom_fields=len(complete_vacancy.custom_fields),
            province_id=complete_vacancy.vacancy.raw_data.get("province_id"),
            working_hours=complete_vacancy.vacancy.raw_data.get("working_hours"),
        )

        return new_id

    async def open_vacancy(self, vacancy_id: str) -> bool:
        """Open a vacancy (e.g. after creation).

        Returns True on success, False on failure.
        """
        response = await self.client.open_vacancy(vacancy_id)
        if not response.success:
            self._logger.error(
                "open_vacancy_failed", vacancy_id=vacancy_id, error=response.data,
            )
            return False

        self._logger.info("vacancy_opened", vacancy_id=vacancy_id)
        return True

    async def close_vacancy(
        self,
        vacancy_id: str,
        closereason_id: int,
        extra_info: Optional[str] = None,
    ) -> bool:
        """Close a vacancy.

        Args:
            vacancy_id: The vacancy UID to close.
            closereason_id: Close reason ID (from getVacancyCloseReasons).
                           Use 3 for "Dubbele vacature" in refresh workflow.
            extra_info: Optional extra information about the closing.

        Returns True on success, False on failure.
        """
        try:
            response = await self.client.close_vacancy(vacancy_id, closereason_id, extra_info)
        except ApiError as exc:
            self._logger.error(
                "close_vacancy_api_error",
                vacancy_id=vacancy_id,
                closereason_id=closereason_id,
                status_code=exc.status_code,
                error=str(exc),
            )
            return False

        if not response.success:
            self._logger.error(
                "close_vacancy_failed",
                vacancy_id=vacancy_id,
                closereason_id=closereason_id,
                error=response.data,
            )
            return False

        self._logger.info(
            "vacancy_closed",
            vacancy_id=vacancy_id,
            closereason_id=closereason_id,
        )
        return True

    # ------------------------------------------------------------------ #
    #  Full refresh workflow
    # ------------------------------------------------------------------ #

    async def refresh_vacancy(
        self,
        vacancy: Vacancy,
        closereason_id: int = 3,
        channels: Optional[list[int]] = None,
    ) -> Optional[str]:
        """Execute the full refresh workflow for a single vacancy.

        Steps:
          1. Fetch complete data (custom fields, VDAB competences)
          2. Create duplicate via addVacancy (vacancy_id=0)
          3. Open the new vacancy
          4. Close the original vacancy

        Args:
            vacancy: Source vacancy (from get_all_open_vacancies with extraData).
            closereason_id: Close reason (default 3 = "Dubbele vacature").
            channels: Channel IDs for multiposting (e.g. [1, 2] for Website + VDAB).

        Returns:
            New vacancy ID on success, None on failure.
        """
        original_id = vacancy.id

        try:
            # Step 1: Get complete data
            complete = await self.get_complete_vacancy(vacancy)

            # Step 2: Create duplicate
            new_id = await self.duplicate_vacancy(complete, channels=channels)

            # Step 3: Open the new vacancy
            opened = await self.open_vacancy(new_id)
            if not opened:
                self._logger.error("refresh_open_failed", new_id=new_id, original_id=original_id)

            # Step 4: Update province AFTER opening the vacancy.
            # The API ignores province_id during creation (vacancy_id=0).
            # IMPORTANT: addVacancy updates appear to clear some dropdown fields
            # when they are omitted from the update payload. Sending only
            # province_id caused group_id ("selectiegroep") to disappear in the UI,
            # so we resend group_id together with province_id.
            # Wrapped in try/except so failures don't prevent closing.
            province_id = complete.vacancy.raw_data.get("province_id")
            if province_id and str(province_id) != "0":
                try:
                    province_int = int(province_id)
                    raw = complete.vacancy.raw_data

                    # Minimal payload: only required fields + province_id
                    update_payload = {
                        "vacancy_id": int(new_id),
                        "office_id": int(raw.get("office_id", 0)),
                        "enterprise_id": int(raw.get("enterprise_id", 0)),
                        "function": raw.get("function", ""),
                        "jobdomain_id": int(raw.get("jobdomain_id", 0)),
                        "language": complete.vacancy.language or "nl",
                        "province_id": province_int,
                    }

                    group_id = raw.get("group_id")
                    if group_id and str(group_id) != "0":
                        update_payload["group_id"] = int(group_id)

                    self._logger.info(
                        "province_update_attempt",
                        vacancy_id=new_id,
                        province_id=province_int,
                        group_id=update_payload.get("group_id"),
                        payload=update_payload,
                    )

                    update_resp = await self.client.add_vacancy(update_payload)
                    self._logger.info(
                        "province_update_result",
                        vacancy_id=new_id,
                        province_id=province_int,
                        success=update_resp.success,
                        response=str(update_resp.data)[:500],
                    )
                except Exception as exc:
                    # Never let province update crash the whole flow
                    self._logger.error(
                        "province_update_error",
                        vacancy_id=new_id,
                        province_id=province_id,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )

            # Step 5: Close original
            closed = await self.close_vacancy(
                original_id,
                closereason_id=closereason_id,
                extra_info=f"Refreshed - new vacancy {new_id}",
            )
            if not closed:
                self._logger.error(
                    "refresh_close_failed",
                    original_id=original_id,
                    new_id=new_id,
                )

            self._logger.info(
                "vacancy_refreshed",
                original_id=original_id,
                new_id=new_id,
                opened=opened,
                closed=closed,
            )
            return new_id

        except ApiError as exc:
            self._logger.error(
                "refresh_failed",
                original_id=original_id,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------ #
    #  Reference data
    # ------------------------------------------------------------------ #

    async def get_channels(self) -> list[Channel]:
        """Get available multiposting channels."""
        response = await self.client.get_channels()
        if not response.success:
            self._logger.error("get_channels_failed", error=response.data)
            return []
        # getChannels returns a direct array, not wrapped
        return _parse_list(response, Channel.from_api)

    async def get_close_reasons(self) -> list[dict]:
        """Get available close reasons."""
        response = await self.client.get_close_reasons()
        if not response.success:
            return []
        return _extract_list(response.data, "closereasons")

    # ------------------------------------------------------------------ #
    #  Document backup
    # ------------------------------------------------------------------ #

    async def backup_vacancy_documents(
        self,
        vacancy_id: str,
        documents: list[VacancyDocument],
        backup_dir: str = "data/documents",
    ) -> list[dict]:
        """Download and save all documents for a vacancy locally.

        For each document:
          1. Calls getDocument to fetch the base64 content
          2. Decodes and saves the file to backup_dir/{vacancy_id}/{filename}

        Args:
            vacancy_id: The vacancy ID (used for folder naming).
            documents: List of VacancyDocument metadata from getVacancyDocuments.
            backup_dir: Base directory for document backups.

        Returns:
            List of dicts with backup results per document.
        """
        if not documents:
            return []

        vacancy_dir = Path(backup_dir) / str(vacancy_id)
        vacancy_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for doc in documents:
            result = {"document_id": doc.id, "filename": doc.filename, "saved": False}
            try:
                resp = await self.client.get_document(doc.id)
                if not resp.success or not resp.data:
                    self._logger.warning(
                        "document_download_failed",
                        vacancy_id=vacancy_id,
                        document_id=doc.id,
                        error="API returned no data",
                    )
                    result["error"] = "No data returned"
                    results.append(result)
                    continue

                doc_data = resp.data.get("document", {}) if isinstance(resp.data, dict) else {}
                content_b64 = doc_data.get("content", "")
                if not content_b64:
                    self._logger.warning(
                        "document_empty_content",
                        vacancy_id=vacancy_id,
                        document_id=doc.id,
                    )
                    result["error"] = "Empty content"
                    results.append(result)
                    continue

                # Use filename from the download response if available
                filename = doc_data.get("file_name", doc.filename) or f"document_{doc.id}"
                file_path = vacancy_dir / filename

                # Handle duplicate filenames
                counter = 1
                while file_path.exists():
                    stem = file_path.stem
                    suffix = file_path.suffix
                    file_path = vacancy_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                file_bytes = base64.b64decode(content_b64)
                file_path.write_bytes(file_bytes)

                result["saved"] = True
                result["path"] = str(file_path)
                result["size_bytes"] = len(file_bytes)
                result["mime_type"] = doc_data.get("mime_type", "")

                self._logger.info(
                    "document_backed_up",
                    vacancy_id=vacancy_id,
                    document_id=doc.id,
                    filename=filename,
                    size_bytes=len(file_bytes),
                    path=str(file_path),
                )

            except Exception as exc:
                self._logger.error(
                    "document_backup_error",
                    vacancy_id=vacancy_id,
                    document_id=doc.id,
                    error=str(exc),
                )
                result["error"] = str(exc)

            results.append(result)

        saved_count = sum(1 for r in results if r.get("saved"))
        self._logger.info(
            "documents_backup_complete",
            vacancy_id=vacancy_id,
            total=len(documents),
            saved=saved_count,
            failed=len(documents) - saved_count,
            backup_dir=str(vacancy_dir),
        )

        return results


# --------------------------------------------------------------------------- #
#  Private helpers
# --------------------------------------------------------------------------- #


def _extract_list(data: Any, key: str) -> list:
    """Extract a list from a dict response by key, or return empty list."""
    if isinstance(data, dict):
        result = data.get(key, [])
        return result if isinstance(result, list) else []
    if isinstance(data, list):
        return data
    return []


def _parse_list(response: ApiResponse, factory: Callable, key: Optional[str] = None) -> list:
    """Safely parse an API list response through a factory function."""
    if not response.success or not response.data:
        return []
    if key:
        raw = _extract_list(response.data, key)
    else:
        raw = response.data if isinstance(response.data, list) else []
    return [factory(item) for item in raw]


def _safe_parse_list(
    response_or_exc: Any,
    factory: Callable,
    key: Optional[str] = None,
) -> list:
    """Parse API response, gracefully handling exceptions from asyncio.gather."""
    if isinstance(response_or_exc, Exception):
        return []
    if not isinstance(response_or_exc, ApiResponse):
        return []
    return _parse_list(response_or_exc, factory, key)


def _extract_id(data: Any) -> Optional[str]:
    """Extract vacancy ID from API response.

    addVacancy returns: {"vacancy_id": 774}
    openVacancy/closeVacancy return: {"updated_vacancy_id": "774"}
    """
    if isinstance(data, dict):
        raw = (
            data.get("vacancy_id")
            or data.get("updated_vacancy_id")
            or data.get("uid")
            or data.get("id")
        )
        if raw:
            return str(raw)
    return None

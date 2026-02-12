"""Data models for Bright Staffing API"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from ..utils.html_reconstruct import reconstruct_html


# --------------------------------------------------------------------------- #
#  Enums
# --------------------------------------------------------------------------- #


class VacancyStatus(str, Enum):
    """Vacancy status enumeration"""

    OPEN = "open"
    CLOSED = "closed"
    DRAFT = "draft"
    ARCHIVED = "archived"


# --------------------------------------------------------------------------- #
#  API transport
# --------------------------------------------------------------------------- #


class ApiError(Exception):
    """Raised when an API call fails."""

    def __init__(
        self,
        status_code: int,
        message: str,
        endpoint: str,
        details: Optional[dict] = None,
    ):
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint
        self.details = details
        super().__init__(f"API Error {status_code} on {endpoint}: {message}")

    @property
    def is_retryable(self) -> bool:
        return self.status_code in (429, 500, 502, 503, 504)

    @property
    def is_auth_error(self) -> bool:
        return self.status_code == 401


@dataclass
class ApiResponse:
    """API response wrapper"""

    success: bool
    data: Any
    status_code: int
    raw_response: Optional[dict] = None


# --------------------------------------------------------------------------- #
#  Reference data
# --------------------------------------------------------------------------- #


@dataclass
class Channel:
    """Multiposting channel.

    API returns:
    - channel_id: Channel ID as string (e.g., "1", "2")
    - name: Channel name (e.g., "Website", "Vdab")
    """

    channel_id: int
    name: str
    active: bool = True

    @classmethod
    def from_api(cls, data: dict) -> "Channel":
        # API returns channel_id as string, convert to int
        raw_id = data.get("channel_id", 0)
        channel_id = int(raw_id) if raw_id else 0
        return cls(
            channel_id=channel_id,
            name=data.get("name", ""),
            active=data.get("active", True),
        )


# --------------------------------------------------------------------------- #
#  Vacancy-related models
# --------------------------------------------------------------------------- #


@dataclass
class VacancyDocument:
    """Document attached to a vacancy.

    API returns:
    - document_id: Unique document ID
    - file_name: Original filename
    - file_size: Human-readable size (e.g., "512.82 KB")
    - file_type: File type category name (e.g., "afbeeldingen")
    - file_type_id: File type ID
    """

    id: str
    vacancy_id: str
    filename: str
    content_type: str
    file_size: Optional[str] = None
    file_type_id: Optional[str] = None
    content: Optional[bytes] = None
    url: Optional[str] = None

    @classmethod
    def from_api(cls, data: dict, vacancy_id: str) -> "VacancyDocument":
        return cls(
            # API returns "document_id"
            id=str(data.get("document_id", data.get("id", ""))),
            vacancy_id=vacancy_id,
            # API returns "file_name"
            filename=data.get("file_name", data.get("filename", data.get("name", ""))),
            # API returns "file_type" as category name
            content_type=data.get("file_type", data.get("content_type", data.get("mime_type", ""))),
            file_size=data.get("file_size"),
            file_type_id=data.get("file_type_id"),
            url=data.get("url"),
        )


@dataclass
class VacancyCustomField:
    """Custom field values for a vacancy.

    API returns a single object per vacancy with fields:
    - uid: Custom field record ID
    - vacancy_id: Associated vacancy ID
    - free1 - free6: Free-form text fields (short)
    - text1 - text2: Text fields (medium)
    - desc1 - desc2: Description fields (long text)
    """

    uid: str
    vacancy_id: str
    free1: str = ""
    free2: str = ""
    free3: str = ""
    free4: str = ""
    free5: str = ""
    free6: str = ""
    text1: str = ""
    text2: str = ""
    desc1: str = ""
    desc2: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "VacancyCustomField":
        return cls(
            uid=str(data.get("uid", "")),
            vacancy_id=str(data.get("vacancy_id", "")),
            free1=data.get("free1", ""),
            free2=data.get("free2", ""),
            free3=data.get("free3", ""),
            free4=data.get("free4", ""),
            free5=data.get("free5", ""),
            free6=data.get("free6", ""),
            text1=data.get("text1", ""),
            text2=data.get("text2", ""),
            desc1=data.get("desc1", ""),
            desc2=data.get("desc2", ""),
        )

    def to_dict(self) -> dict:
        """Convert to dict for API submission, excluding empty fields."""
        result = {}
        for field in ("free1", "free2", "free3", "free4", "free5", "free6",
                      "text1", "text2", "desc1", "desc2"):
            val = getattr(self, field)
            if val:
                result[field] = val
        return result


@dataclass
class VdabCompetence:
    """VDAB competence linked to vacancy.

    API returns:
    - code: The VDAB competence ID (use for vdab_competences array in addVacancy)
    - desc: Description of the competence (may contain newlines)
    """

    id: str  # The competence code (maps from API "code" field)
    name: str  # The description (maps from API "desc" field)
    code: Optional[str] = None  # Alias for id

    @classmethod
    def from_api(cls, data: dict) -> "VdabCompetence":
        # API returns "code" as the ID and "desc" as the description
        code = str(data.get("code", data.get("id", "")))
        return cls(
            id=code,
            name=data.get("desc", data.get("name", "")),
            code=code,
        )


# --------------------------------------------------------------------------- #
#  Vacancy
# --------------------------------------------------------------------------- #

# Fields to exclude when round-tripping through to_api_dict (read-only meta)
# Note: vacancy_id is handled specially - set to 0 for new vacancies
_EXCLUDED_RAW_KEYS = frozenset({"uid", "status", "created_at", "updated_at"})

# Language ID to code mapping (API returns language_id, addVacancy needs language code)
_LANGUAGE_MAP: dict[str, str] = {
    "1": "nl",
    "2": "fr",
    "3": "en",
    "0": "nl",  # Default to Dutch if not set
}

# Country name to ISO code mapping
# API returns full names (e.g. "België") but addVacancy requires ISO codes (e.g. "BE")
_COUNTRY_TO_ISO: dict[str, str] = {
    "België": "BE",
    "Belgie": "BE",
    "Belgium": "BE",
    "Nederland": "NL",
    "Netherlands": "NL",
    "France": "FR",
    "Frankrijk": "FR",
    "Germany": "DE",
    "Duitsland": "DE",
    "Luxembourg": "LU",
    "Luxemburg": "LU",
    "United Kingdom": "GB",
}

# Whitelist of fields the API accepts for addVacancy (from API documentation).
# ONLY these fields are sent. Everything else from raw_data is dropped.
# This prevents sending read-only/display fields that could confuse the API.
_WRITABLE_FIELDS = frozenset({
    # Required fields
    "vacancy_id", "office_id", "enterprise_id", "function",
    "jobdomain_id", "language",
    # Optional documented fields
    "department_id", "statute_id",
    "desc_function", "desc_profile", "desc_offer",
    "driverlicense_id", "option_fix", "contract_type",
    "regime_id", "workingduration_id", "working_hours",
    "work_street", "work_street_nr", "work_bus",
    "work_post", "work_city", "work_country",
    "work_lat", "work_lng",
    "group_id", "experience_id", "province_id",
    "salary_type", "salary_amount_min", "salary_amount_max",
    "info_internal", "coef", "sector_id",
    "jobtitle_id", "job_level",
    "user_consulent_id", "is_spontaneous",
    # Array fields: competences + studies are excluded here because they
    # need format conversion (handled by build_duplication_payload).
    "vdab_jobcategory_id", "vdab_jobcategory_name",
    "vdab_competences",
    "user_id",
    # Fields from request sample (not in docs table but accepted)
    "enterprise_dept_id", "is_equal_by_experience",
    # Contact fields (writable per vacancy)
    "contact_name", "contact_mail",
    # Custom fields (free1-6, text1-2, desc1-2) added by build_duplication_payload
})


def _parse_iso_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string, handling trailing 'Z'."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


@dataclass
class Vacancy:
    """Vacancy (job posting) data model"""

    id: str
    title: str
    description: str = ""
    status: VacancyStatus = VacancyStatus.OPEN
    office_id: Optional[str] = None
    office_name: Optional[str] = None
    job_domain_id: Optional[str] = None
    job_title_id: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    contract_type: Optional[str] = None
    working_hours: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    experience_required: Optional[str] = None
    education_required: Optional[str] = None
    channels: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    language: Optional[str] = None  # ISO language code: "nl", "fr", "en"
    enterprise_id: Optional[str] = None
    enterprise_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    requirements: Optional[str] = None
    benefits: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict) -> "Vacancy":
        """Create Vacancy from API response.

        API returns fields like:
        - uid (not id/vacancy_id)
        - function (not title)
        - work_city, work_post, work_country (location fields)
        - desc_function, desc_profile, desc_offer (descriptions)
        - language_id (needs mapping to language code)
        """
        # Determine open/closed status.
        # The API does NOT return a "status" field in the standard response.
        # With extraData=true, it returns "is_closed" ("0" = open, "1" = closed).
        is_closed = data.get("is_closed")
        if is_closed in ("1", 1, True):
            status = VacancyStatus.CLOSED
        elif is_closed in ("0", 0, False):
            status = VacancyStatus.OPEN
        else:
            # Fallback: check explicit status field (e.g. mock data)
            status_str = data.get("status", "open").lower()
            try:
                status = VacancyStatus(status_str)
            except ValueError:
                status = VacancyStatus.OPEN

        def _get_str_or_none(key: str) -> Optional[str]:
            raw = data.get(key)
            return str(raw) if raw else None

        # Map language_id to language code for storage
        language_id = str(data.get("language_id", "0"))
        language_code = _LANGUAGE_MAP.get(language_id, "nl")

        return cls(
            # API returns "uid" as the vacancy ID
            id=str(data.get("uid", data.get("id", data.get("vacancy_id", "")))),
            # API returns "function" as the job title
            title=data.get("function", data.get("title", "")),
            # API returns "desc_function" as description
            description=data.get("desc_function", data.get("description", "")),
            status=status,
            office_id=_get_str_or_none("office_id"),
            office_name=data.get("office_name"),
            language=language_code,
            # API field names match
            job_domain_id=_get_str_or_none("jobdomain_id"),
            job_title_id=_get_str_or_none("jobtitle_id"),
            location=data.get("location"),
            # API returns work_city
            city=data.get("work_city", data.get("city")),
            # API returns work_post
            postal_code=data.get("work_post", data.get("postal_code")),
            # API returns work_country (name) and work_country_iso (code) with extraData
            country=data.get("work_country_iso", data.get("work_country", data.get("country"))),
            contract_type=data.get("contract_type"),
            # API returns regime_id
            working_hours=data.get("regime_id", data.get("working_hours")),
            salary_min=data.get("salary_amount_min", data.get("salary_min")),
            salary_max=data.get("salary_amount_max", data.get("salary_max")),
            # API returns experience_id
            experience_required=data.get("experience_id", data.get("experience_required")),
            education_required=data.get("education_required"),
            channels=data.get("channels", []),
            created_at=_parse_iso_datetime(data.get("created_at")),
            updated_at=_parse_iso_datetime(data.get("updated_at")),
            enterprise_id=_get_str_or_none("enterprise_id"),
            # API returns enterprise_gen_name
            enterprise_name=data.get("enterprise_gen_name", data.get("enterprise_name")),
            # API returns contact_name, contact_mail
            contact_person=data.get("contact_name", data.get("contact_person")),
            contact_email=data.get("contact_mail", data.get("contact_email")),
            contact_phone=data.get("contact_phone"),
            # API returns desc_profile
            requirements=data.get("desc_profile", data.get("requirements")),
            # API returns desc_offer
            benefits=data.get("desc_offer", data.get("benefits")),
            raw_data=data,
        )

    def to_api_dict(self, for_duplication: bool = False) -> dict:
        """Convert vacancy to API request format for addVacancy.

        Args:
            for_duplication: If True, sets vacancy_id to 0 to create a NEW vacancy.
                           If False, uses existing id to UPDATE the vacancy.

        Returns:
            Dict formatted for BrightStaffing addVacancy API endpoint.
            Uses API field names: function, work_city, desc_function, etc.
        """
        data: dict[str, Any] = {}

        # CRITICAL: Set vacancy_id for create vs update
        if for_duplication:
            data["vacancy_id"] = 0  # Creates NEW vacancy
        elif self.id:
            data["vacancy_id"] = self.id  # Updates existing

        # Required fields with API field names
        if self.office_id:
            data["office_id"] = self.office_id
        if self.enterprise_id:
            data["enterprise_id"] = self.enterprise_id
        if self.title:
            data["function"] = self.title  # API uses "function" not "title"

        # Description fields - API naming
        if self.description:
            data["desc_function"] = self.description
        if self.requirements:
            data["desc_profile"] = self.requirements
        if self.benefits:
            data["desc_offer"] = self.benefits

        # Language - required for addVacancy
        if self.language:
            data["language"] = self.language

        # Location fields - API naming
        if self.city:
            data["work_city"] = self.city
        if self.postal_code:
            data["work_post"] = self.postal_code
        if self.country:
            # Convert country name to ISO code if needed
            country = _COUNTRY_TO_ISO.get(self.country, self.country)
            data["work_country"] = country

        # ID reference fields - API naming
        if self.job_domain_id:
            data["jobdomain_id"] = self.job_domain_id
        if self.job_title_id:
            data["jobtitle_id"] = self.job_title_id
        if self.working_hours:
            data["regime_id"] = self.working_hours
        if self.experience_required:
            data["experience_id"] = self.experience_required

        # Salary fields
        if self.salary_min is not None:
            data["salary_amount_min"] = self.salary_min
        if self.salary_max is not None:
            data["salary_amount_max"] = self.salary_max

        # Contact fields are in READ_ONLY list but appear in raw_data.
        # They'll be copied from raw_data in the loop below if present.
        # Don't explicitly set them here to avoid duplicates.

        # List fields
        if self.channels:
            data["channels"] = self.channels

        # Fields that the API expects as integer (from documentation).
        # raw_data returns these as strings, but addVacancy requires int.
        _INTEGER_FIELDS = frozenset({
            "office_id", "province_id", "group_id", "statute_id", "regime_id",
            "sector_id", "jobdomain_id", "jobtitle_id", "driverlicense_id",
            "experience_id", "contract_type", "workingduration_id",
            "job_level", "enterprise_id", "enterprise_dept_id",
            "working_hours", "department_id",
        })

        # Fields already explicitly set above (avoid overwriting with raw_data)
        _already_mapped = frozenset({
            "function", "desc_function", "desc_profile", "desc_offer",
            "work_city", "work_post", "work_country",
        })
        # ID fields where 0 is NOT a valid value (means "not set").
        # The API rejects 0 for these with "X: 0 is not a valid X id".
        _skip_zero_ids = frozenset({
            "jobtitle_id", "sector_id", "statute_id",
            "driverlicense_id", "experience_id", "workingduration_id",
            "regime_id", "contract_type", "group_id", "job_level",
            "department_id", "enterprise_dept_id",
        })

        # Only send fields from the API-documented whitelist.
        # This prevents sending read-only/display/metadata fields
        # that could interfere with vacancy creation.
        for key, value in self.raw_data.items():
            if key not in data and key in _WRITABLE_FIELDS and key not in _already_mapped:
                # Only skip specific ID fields where 0 means "not set"
                if key in _skip_zero_ids and (value == 0 or value == "0"):
                    continue
                # Convert integer fields from string to int per API docs
                if key in _INTEGER_FIELDS and value and str(value).strip():
                    try:
                        data[key] = int(value)
                    except (ValueError, TypeError):
                        data[key] = value
                else:
                    data[key] = value

        # Final pass: ensure ALL integer fields are int, including ones
        # set explicitly above (e.g. office_id, enterprise_id, jobdomain_id).
        for key in list(data.keys()):
            if key in _INTEGER_FIELDS and data[key] is not None:
                raw = str(data[key]).strip()
                if raw:
                    try:
                        data[key] = int(raw)
                    except (ValueError, TypeError):
                        pass

        # Final cleanup: remove ID fields where 0 means "not set".
        # The explicit field setters above (e.g. self.job_title_id) treat
        # "0" as truthy and set the field, bypassing the _skip_zero_ids
        # check in the raw_data loop. This pass catches those cases.
        for key in list(data.keys()):
            if key in _skip_zero_ids and data[key] in (0, "0"):
                del data[key]

        return data


# --------------------------------------------------------------------------- #
#  Complete vacancy (composite)
# --------------------------------------------------------------------------- #


@dataclass
class CompleteVacancy:
    """Complete vacancy with all related data for duplication."""

    vacancy: Vacancy
    documents: list[VacancyDocument] = field(default_factory=list)
    custom_fields: list[VacancyCustomField] = field(default_factory=list)
    competences: list[VdabCompetence] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.vacancy.id

    @property
    def title(self) -> str:
        return self.vacancy.title

    def build_duplication_payload(self, channels: Optional[list[int]] = None) -> dict:
        """Build complete addVacancy payload for duplication.

        Everything goes through addVacancy in a single call:
        - Core vacancy fields (from raw_data with extraData)
        - VDAB competences (from getVacancyVdabCompetences)
        - Custom fields (from getVacancyCustomFields)
        - Channel selection for multiposting
        - vacancy_id=0 to create NEW vacancy

        Documents cannot be transferred via API (no upload endpoint exists).
        """
        data = self.vacancy.to_api_dict(for_duplication=True)

        # Descriptions are fetched with as_html=1, so they already contain
        # the original HTML formatting (bold, bullets, etc.).
        # Only reconstruct if the descriptions somehow lack HTML tags.
        for desc_field in ("desc_function", "desc_profile", "desc_offer"):
            if desc_field in data and data[desc_field]:
                content = data[desc_field]
                # If already has HTML tags, keep as-is (fetched with as_html=1)
                if "<" not in content:
                    data[desc_field] = reconstruct_html(content)

        # Add VDAB competences as integer array
        if self.competences:
            vdab_codes = []
            for comp in self.competences:
                try:
                    vdab_codes.append(int(comp.id))
                except (ValueError, TypeError):
                    pass
            if vdab_codes:
                data["vdab_competences"] = vdab_codes

        # Add custom fields directly in payload (free1-6, text1-2, desc1-2)
        if self.custom_fields:
            cf = self.custom_fields[0]  # One record per vacancy
            cf_data = cf.to_dict()
            for key, value in cf_data.items():
                if value and key not in data:
                    data[key] = value

        # Convert studies array format.
        # API returns: studies = [{'level1_id': '3', 'level1_name': '...', 'level2_id': '637', ...}]
        # API expects: studies = [{'study_id': 637}, {'study_id': ...}]
        studies = self.vacancy.raw_data.get("studies", [])
        if studies and isinstance(studies, list):
            studies_array = []
            for study in studies:
                # Prefer level2_id (more specific), fallback to level1_id
                study_id = study.get("level2_id") or study.get("level1_id")
                if study_id:
                    try:
                        studies_array.append({"study_id": int(study_id)})
                    except (ValueError, TypeError):
                        pass
            if studies_array:
                data["studies"] = studies_array

        # Tell API to accept HTML tags in descriptions (vs stripping them)
        data["as_html"] = "1"

        # Add channels for multiposting.
        # API uses consistent array-of-objects pattern for related entities:
        #   studies: [{"study_id": 5}]
        #   competences: [{"competence_id": 8, "score": 4}]
        # So channels likely follow: [{"channel_id": 1}, {"channel_id": 2}]
        if channels:
            data["channels"] = [{"channel_id": ch} for ch in channels]

        return data

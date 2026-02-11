# BrightStaffing API Documentation

## POST /vacancy/addVacancy

This endpoint contains a POST operation to add a vacancy.

REQUEST BODY SCHEMA: multipart/form-data

The `vacancy` object is forwarded as a JSON encoded object to the API endpoint.
Fields that are not filled in may be omitted from the object.

### Top-level parameters:
- `api_access_token` (string, required)
- `api_version` (string, required)
- `vacancy` (object, required) - datastructure containing the vacancy

### Vacancy object fields:

| Field | Type | Description |
|-------|------|-------------|
| `vacancy_id` | integer, **required** | Unique vacancy id. When adding a new vacancy, this must be value "0". |
| `office_id` | integer, **required** | Unique office_id as mentioned in Object: office |
| `enterprise_id` | integer, **required** | Unique enterprise_id as mentioned in Object: enterprise |
| `function` | string, **required** | Function of the vacancy |
| `jobdomain_id` | integer, **required** | Unique jobdomain id |
| `language` | string, **required** | Enum: "nl", "fr", "en" |
| `department_id` | integer | Unique department_id as mentioned in Object: enterprise_department |
| `statute_id` | integer | Unique statute id as mentioned in Object: statute |
| `desc_function` | string | Description of the function |
| `desc_profile` | string | Description of the profile |
| `desc_offer` | string | Description of the offer |
| `driverlicense_id` | integer | Unique driver license id |
| `option_fix` | boolean | possible values: true, false |
| `contract_type` | integer | Unique id of contract type, see Catalog list vdab.contract_type |
| `regime_id` | integer | Unique id of type of regime, see Catalog list vacancy_regime |
| `workingduration_id` | integer | Unique id of type of workingduration, see Catalog list vacancy.working_duration |
| `working_hours` | integer | working hours |
| `work_street` | string | Street of employment address |
| `work_street_nr` | string | Street number of employment address |
| `work_bus` | string | Bus of employment address |
| `work_post` | string | Postal code of employment address |
| `work_city` | string | City of employment address |
| `work_country` | string | Country of employment address (ISO code) |
| `work_lat` | number (float) | Latitude of employment address |
| `work_lng` | number (float) | Longitude of employment address |
| `group_id` | integer | Unique id of type of group, see Catalog list person_group |
| `experience_id` | integer | Unique experience_id |
| `province_id` | integer | Unique id of type of group, see Catalog list firm.province |
| `salary_type` | any | Enum: "0", "1", "2" (0 => uur, 1 => maand, 2 => day) |
| `salary_amount_min` | number | Expected minimum salary |
| `salary_amount_max` | number | Expected maximum salary |
| `info_internal` | string | Internal info |
| `coef` | number | Coef |
| `sector_id` | integer | Unique sector id |
| `jobtitle_id` | integer | Unique jobtitle id |
| `job_level` | integer | Unique id of type of job_level, see Catalog list job_level |
| `user_consulent_id` | integer | Unique user_consulent_id as mentioned in Object: user |
| `is_spontaneous` | boolean | possible values: true, false |
| `competences` | Array of objects | List of competences: [{competence_id: int, score: 1-5}] |
| `studies` | Array of objects | List of studies: [{study_id: int}] |
| `vdab_jobcategory_id` | string | VDAB job category ID |
| `vdab_jobcategory_name` | string | VDAB job category name |
| `vdab_competences` | Array of integers | List of VDAB competence IDs |
| `user_id` | integer | The user account to use for user_created and permissions |

### Responses:
- 200: Request processed successfully, see response body for JSON data.
- 400: A parameter is missing or the specified parameter is invalid.

---

## Request Sample:
```json
{
  "vacancy_id": 0,
  "office_id": "3",
  "enterprise_id": "6255",
  "enterprise_dept_id": "0",
  "function": "some text",
  "desc_function": "some text",
  "desc_profile": "some text",
  "desc_offer": "some text",
  "driverlicense_id": "7",
  "option_fix": "1",
  "working_hours": "38",
  "info_internal": "some text",
  "work_city": "some text",
  "work_country": "BE",
  "work_post": "8700",
  "work_bus": "",
  "work_street_nr": "2",
  "work_street": "some text",
  "work_lat": "51.00000000",
  "work_lng": "5.0000000000",
  "experience_id": "1",
  "salary_amount_min": "1800.0000",
  "salary_amount_max": "3000.0000",
  "sector_id": "3",
  "jobdomain_id": "26",
  "jobtitle_id": "316",
  "language": "nl",
  "user_consulent_id": "33",
  "regime_id": "115",
  "workingduration_id": "140",
  "job_level": "3",
  "group_id": "2",
  "statute_id": "1",
  "is_spontaneous": "1",
  "is_equal_by_experience": "1",
  "salary_type": "1",
  "coef": "1.82",
  "competences": [
    {"competence_id": 8, "score": 4},
    {"competence_id": 3, "score": 4}
  ],
  "studies": [
    {"study_id": 5},
    {"study_id": 7}
  ],
  "vdab_jobcategory_id": "F160301-2",
  "vdab_jobcategory_name": "some text",
  "vdab_competences": [4112, 16486, 16854, 10577, 11879, 17938]
}
```

## Response Sample (getVacanciesByOffice):
```json
{
  "vacancies": [
    {
      "uid": "2",
      "office_id": "2",
      "reference": "W001/000002",
      "language_id": "0",
      "language_name": "",
      "statute_id": "1",
      "statute_name": "Arbeider",
      "work_city": "",
      "work_country": "",
      "work_post": "",
      "work_bus": "",
      "work_street_nr": "",
      "work_street": "",
      "work_lat": "0.0000000000",
      "work_lng": "0.0000000000",
      "regime_id": "116",
      "regime_name": "Nachtwerk",
      "function": "Bitter Capybara",
      "desc_function": "...",
      "sector_id": "16",
      "sector_name": "Natuur en leefmilieu",
      "jobdomain_id": "9",
      "jobdomain_name": "ICT",
      "jobtitle_id": "1",
      "jobtitle_name": "Systeembeheer",
      "vdab_jobcategory_id": "",
      "vdab_jobcategory_name": "",
      "desc_profile": "...",
      "desc_offer": "...",
      "experience_id": "0",
      "experience_name": "",
      "driverlicense_id": "6",
      "driverlicense": "C1",
      "contact_name": "B-Bright Administrator",
      "contact_mail": "ward@b-bright.be",
      "assigned_user_name": "B-Bright Administrator",
      "assigned_user_mail": "ward@b-bright.be",
      "workingduration_id": "0",
      "workingduration_name": "",
      "option_permanent": "0",
      "enterprise_gen_name": "Customer Demo 2 bvba",
      "enterprise_id": "2",
      "enterprise_dept_id": "0",
      "studies": []
    }
  ]
}
```

---

## POST /vacancy/getVacanciesByOffice

Get vacancies filtered by office.

REQUEST BODY SCHEMA: multipart/form-data

### Post parameters:

| Field | Type | Description |
|-------|------|-------------|
| `office_id` | integer, **required** | Unique office-id |
| `extraData` | boolean | Get extra vacancy data (true/false) |
| `api_lang` | string | Enum: "nl", "fr", "en" - Return the desired language |
| `as_html` | string | Enum: "0", "1" - Show html tags? |
| `ts_created` | integer | Unix timestamp, created since |
| `ts_changed` | integer | Unix timestamp, last changed since |
| `page` | integer | Pageing, each page contains 100 items, starts at 1 |
| `api_access_token` | string, **required** | API access token |
| `api_version` | string, **required** | API version |

### Response: 200
Returns array of vacancy objects.

### Response fields (per vacancy):
| Field | Type | Notes |
|-------|------|-------|
| `uid` | string | Vacancy ID |
| `office_id` | string | |
| `reference` | string | e.g. "W001/000002" |
| `language_id` | string | |
| `language_name` | string | |
| `statute_id` | string | |
| `statute_name` | string | e.g. "Arbeider" |
| `work_city`, `work_country`, `work_post`, `work_bus`, `work_street_nr`, `work_street` | string | Address fields |
| `work_lat`, `work_lng` | string | Coordinates |
| `regime_id` | string | |
| `regime_name` | string | e.g. "Nachtwerk" |
| `function` | string | Job title |
| `desc_function`, `desc_profile`, `desc_offer` | string | Description fields |
| `sector_id`, `sector_name` | string | |
| `jobdomain_id`, `jobdomain_name` | string | |
| `jobtitle_id`, `jobtitle_name` | string | |
| `vdab_jobcategory_id`, `vdab_jobcategory_name` | string | |
| `experience_id`, `experience_name` | string | |
| `driverlicense_id`, `driverlicense` | string | |
| `contact_name`, `contact_mail` | string | |
| `assigned_user_name`, `assigned_user_mail` | string | |
| `workingduration_id`, `workingduration_name` | string | |
| `option_permanent` | string | |
| `enterprise_gen_name`, `enterprise_id`, `enterprise_dept_id` | string | |
| `studies` | array | Study objects |

### Extra fields (only with extraData=true):
These fields are NOT in the base response. They appear when `extraData=true`:
- `province_id`, `province_name`
- `salary_amount_min`, `salary_amount_max`, `salary_type`
- `contract_type`, `working_hours`
- `job_level`, `option_fix`
- `work_country_iso`
- `is_closed`, `is_spontaneous`, `is_equal_by_experience`, `is_urgent`
- `website`
- `competences`, `languages`, `driverlicenses`
- `work_addresses`, `work_regions`
- `enterprise_gen_*` (full enterprise address)
- `enterprise_vatnumber`, `firm_name`, `firm_vatnumber`
- `office_*` (full office details)

---

## POST /vacancy/openVacancy

Open a vacancy.

Parameters:
- `api_access_token` (string, required)
- `api_version` (string, required)
- `vacancy_id` (integer, required) - Unique id of vacancy object

Response 200: `{"updated_vacancy_id": 0}`

---

## POST /vacancy/closeVacancy

Close a vacancy.

Parameters:
- `api_access_token` (string, required)
- `api_version` (string, required)
- `vacancy_id` (integer, required) - Unique id of vacancy object
- `closereason_id` (integer, required) - Unique id of closereason object
- `extra_info` (string) - Extra info about the closing

Response 200: `{"updated_vacancy_id": 0}`

---

## POST /vacancy/getVacancyCloseReasons

Get possible vacancy close reasons.

Parameters:
- `api_access_token` (string, required)
- `api_version` (string, required)

Response 200:
```json
{
  "closereasons": [
    {"closereason_id": "1", "name": "Vacature werd ingevuld"},
    {"closereason_id": "2", "name": "Vacature on hold"}
  ]
}
```

---

## Key Notes:
- province_id IS a valid writable field for addVacancy (type: integer)
- province_id references Catalog list: firm.province
- group_id IS a valid writable field (type: integer, references person_group)
- coef IS a valid writable field (type: number)
- competences array format: [{competence_id: int, score: 1-5}]
- studies array format: [{study_id: int}]
- The vacancy object is JSON-encoded as a string in multipart/form-data
- province_id is NOT in the response sample - it comes from extraData=true

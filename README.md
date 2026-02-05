# Bright Staffing Job Refresh Bot

Automated job refresh system for Bright Staffing API. Processes vacancies by duplicating them as fresh postings and closing the originals.

## Features

- Automated vacancy refresh workflow (Fetch -> Backup Docs -> Duplicate -> Open -> Close Original)
- Automatic document backup - Downloads vacancy documents before closing originals
- Multiposting to Website + VDAB channels
- Telegram notifications on every run (success or failure)
- Dry-run mode for testing without API calls
- State tracking with resume capability
- Configurable rate limiting and circuit breaker
- Detailed logging and reporting
- Email, webhook, and Telegram alerts
- Rollback support - Undo changes if something goes wrong
- Docker support - Containerized deployment
- CI/CD pipeline with GitHub Actions
- Scheduled runs - Saturday 08:30 Brussels time

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API credentials

# 4. Test with dry run
python -m src.main run --dry-run --limit 5

# 5. Run for real (small batch first)
python -m src.main run --limit 10
```

## Configuration

### Required Environment Variables

```bash
BRIGHT_API_BASE_URL=https://match.b-bright.be/api
BRIGHT_API_ACCESS_TOKEN=your_token_here
BRIGHT_OFFICE_ID=1  # Office ID (1=Oudenaarde, 5=Kuurne, etc.)
```

### Optional Settings

```bash
DRY_RUN=false           # Set true for testing
BATCH_SIZE=50           # Concurrent processing limit
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
TELEGRAM_BOT_TOKEN=     # Telegram bot token (from @BotFather)
TELEGRAM_CHAT_ID=       # Telegram chat ID for notifications
```

## Usage

### Run Commands

```bash
# Dry run (no real changes)
python -m src.main run --dry-run

# Limited test run
python -m src.main run --limit 10

# Full production run
python -m src.main run

# Resume failed run
python -m src.main run --resume RUN_ID
```

### Status Commands

```bash
# List recent runs
python -m src.main status

# Check specific run
python -m src.main status RUN_ID

# View history
python -m src.main history --limit 20

# Test API connection
python -m src.main test-connection

# Validate configuration
python -m src.main validate
```

### Rollback Commands

```bash
# Preview rollback (dry-run)
python -m src.main rollback RUN_ID --dry-run

# Execute rollback
python -m src.main rollback RUN_ID

# Only reopen originals
python -m src.main rollback RUN_ID --no-close-duplicates

# Only close duplicates
python -m src.main rollback RUN_ID --no-reopen
```

## Docker Deployment

```bash
# Dry run
docker-compose up job-refresh

# Production run
docker-compose up job-refresh-live

# Scheduled (Saturday 08:30)
docker-compose up -d scheduler

# Check status
docker-compose up status
```

## Windows Task Scheduler

```bash
# Install task (Saturday 08:30)
python scripts/setup_scheduler.py --install --hour 8 --minute 30

# Check status
python scripts/setup_scheduler.py --status

# Run now
python scripts/setup_scheduler.py --run-now

# Uninstall
python scripts/setup_scheduler.py --uninstall
```

## Project Structure

```
src/
  main.py           # CLI entry point
  config.py         # Configuration loader
  api/
    client.py       # HTTP client (rate limiting, retries)
    models.py       # Data models
    vacancy.py      # Vacancy service
  services/
    processor.py    # Main job processor
    reporter.py     # Report generator
    rollback.py     # Rollback service
    state.py        # SQLite state manager
config/
  config.yaml       # YAML configuration
scripts/
  setup_scheduler.py    # Windows scheduler setup
  docker_entrypoint.sh  # Docker entry script
```

## Workflow

For each open vacancy:
1. **Fetch** complete data (custom fields, VDAB competences, document list)
2. **Backup documents** - Download and save any attached files to `data/documents/{vacancy_id}/`
3. **Duplicate** - Create NEW vacancy via `addVacancy` with `vacancy_id=0` + multipost channels
4. **Open** new vacancy via `openVacancy`
5. **Close** ORIGINAL vacancy with reason "Dubbele vacature"

## API Endpoints Used

| Operation | Endpoint |
|-----------|----------|
| List vacancies | `POST /vacancy/getVacanciesByOffice` |
| Create vacancy | `POST /vacancy/addVacancy` |
| Close vacancy | `POST /vacancy/closeVacancy` |
| Open vacancy | `POST /vacancy/openVacancy` |
| Get custom fields | `POST /vacancy/getVacancyCustomFields` |
| Get competences | `POST /vacancy/getVacancyVdabCompetences` |
| Get documents | `POST /vacancy/getVacancyDocuments` |
| Download document | `POST /document/getDocument` |
| Get channels | `POST /channel/getChannels` |
| Get offices | `POST /office/getOffices` |

## Known Limitations

- Documents are backed up locally but cannot be re-uploaded to new vacancies (no upload endpoint in API). Staff can re-attach saved files from `data/documents/` via the BrightStaffing UI.
- VDAB competences endpoint may return 500 errors on staging (server-side issue, handled gracefully)

## Offices Available

| ID | Name | Location |
|----|------|----------|
| 1 | M001 | Match HR Oudenaarde |
| 3 | M900 | Interne medewerkers |
| 5 | M002 | Match HR Kuurne |
| 7 | M003 | Digital Talent Hunters |

## License

Private - For Match Staffing agency use only.

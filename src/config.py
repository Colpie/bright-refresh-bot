"""Configuration management for Job Refresh Bot"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

# --------------------------------------------------------------------------- #
#  Section configs
# --------------------------------------------------------------------------- #


class ApiConfig(BaseModel):
    """API connection configuration"""

    base_url: str = "https://match.b-bright.be/api"
    access_token: str = ""
    api_version: str = "1.0"
    api_lang: str = "en"
    office_id: str = ""  # Comma-separated office IDs or "all" for all offices
    rate_limit: float = 1.0
    max_retries: int = 3
    timeout: int = 30
    backoff_base: float = 2.0
    backoff_multiplier: float = 2.0
    max_backoff: float = 60.0
    # Web login credentials for multiposting (session-based endpoint)
    web_username: str = ""
    web_password: str = ""

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("rate_limit")
    @classmethod
    def validate_rate_limit(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("rate_limit must be positive")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retries cannot be negative")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 1:
            raise ValueError("timeout must be at least 1 second")
        return v


class ProcessorConfig(BaseModel):
    """Job processing configuration"""

    batch_size: int = 100
    close_reason: int = 3  # closereason_id: 3 = "Dubbele vacature"
    multipost_channels: list[int] = Field(default_factory=lambda: [1, 3])  # 1=Website, 3=Vdab
    dry_run: bool = False
    circuit_breaker_threshold: int = 10
    continue_on_error: bool = True

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("batch_size must be at least 1")
        return v

    @field_validator("circuit_breaker_threshold")
    @classmethod
    def validate_circuit_breaker(cls, v: int) -> int:
        if v < 1:
            raise ValueError("circuit_breaker_threshold must be at least 1")
        return v


class ScheduleConfig(BaseModel):
    """Scheduling configuration"""

    timezone: str = "Europe/Brussels"
    day_of_week: int = Field(default=5, ge=0, le=6)
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=30, ge=0, le=59)


class EmailConfig(BaseModel):
    """Email alert configuration"""

    recipients: list[str] = Field(default_factory=list)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = "jobrefresh@example.com"


class WebhookConfig(BaseModel):
    """Webhook alert configuration"""

    url: Optional[str] = None


class TelegramConfig(BaseModel):
    """Telegram notification configuration"""

    bot_token: str = ""
    chat_id: str = ""


class AlertConfig(BaseModel):
    """Alert configuration"""

    enabled: bool = True
    email: EmailConfig = Field(default_factory=EmailConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    failure_threshold: int = 10
    failure_rate_threshold: float = 0.1


class StateConfig(BaseModel):
    """State storage configuration"""

    db_path: str = "data/state.db"


class LoggingConfig(BaseModel):
    """Logging configuration"""

    level: str = "INFO"
    dir: str = "logs"
    format: str = "json"
    max_file_size_mb: int = 10
    backup_count: int = 5

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"level must be one of {allowed}")
        return upper


# --------------------------------------------------------------------------- #
#  Root config
# --------------------------------------------------------------------------- #


class Config(BaseModel):
    """Main application configuration"""

    api: ApiConfig = Field(default_factory=ApiConfig)
    processor: ProcessorConfig = Field(default_factory=ProcessorConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# --------------------------------------------------------------------------- #
#  Environment variable overrides  (env > yaml > defaults)
# --------------------------------------------------------------------------- #

_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "BRIGHT_API_BASE_URL": ("api.base_url", str),
    "BRIGHT_API_ACCESS_TOKEN": ("api.access_token", str),
    "BRIGHT_API_VERSION": ("api.api_version", str),
    "BRIGHT_OFFICE_ID": ("api.office_id", str),
    "DRY_RUN": ("processor.dry_run", bool),
    "BATCH_SIZE": ("processor.batch_size", int),
    "SCHEDULE_TIMEZONE": ("schedule.timezone", str),
    "LOG_LEVEL": ("logging.level", str),
    "LOG_DIR": ("logging.dir", str),
    "STATE_DB_PATH": ("state.db_path", str),
    "TELEGRAM_BOT_TOKEN": ("alerts.telegram.bot_token", str),
    "TELEGRAM_CHAT_ID": ("alerts.telegram.chat_id", str),
    "BRIGHT_WEB_USERNAME": ("api.web_username", str),
    "BRIGHT_WEB_PASSWORD": ("api.web_password", str),
}


def _apply_env_overrides(config: Config) -> None:
    """Apply environment variable overrides to config."""
    for env_key, (path, dtype) in _ENV_OVERRIDES.items():
        raw = os.getenv(env_key)
        if raw is None:
            continue

        parts = path.split(".")
        obj = config
        for part in parts[:-1]:
            obj = getattr(obj, part)

        if dtype is bool:
            value = raw.lower() in ("true", "1", "yes")
        elif dtype is int:
            value = int(raw)
        else:
            value = raw

        setattr(obj, parts[-1], value)


# --------------------------------------------------------------------------- #
#  Public helpers
# --------------------------------------------------------------------------- #


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from YAML file and environment variables.

    Priority (highest to lowest):
      1. Environment variables
      2. YAML config file
      3. Default values
    """
    load_dotenv()

    if config_path is None:
        config_path = os.getenv("CONFIG_PATH", "config/config.yaml")

    config_data: dict = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            config_data = yaml.safe_load(f) or {}

    config = Config(**config_data)
    _apply_env_overrides(config)
    return config


def validate_config(config: Config) -> list[str]:
    """
    Validate configuration and return list of errors.
    Returns an empty list when everything is valid.
    """
    errors: list[str] = []

    if not config.api.access_token and not config.processor.dry_run:
        errors.append(
            "API access token is required (set BRIGHT_API_ACCESS_TOKEN or use --dry-run)"
        )

    if not config.api.office_id and not config.processor.dry_run:
        errors.append(
            "Office ID is required (set BRIGHT_OFFICE_ID or use --dry-run)"
        )

    if config.alerts.enabled and config.alerts.email.recipients:
        if not config.alerts.email.smtp_user:
            errors.append(
                "SMTP user is required when email alerts are enabled with recipients"
            )

    return errors

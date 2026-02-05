"""Logging configuration and utilities"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json

import structlog
from structlog.typing import EventDict


def add_timestamp(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add ISO timestamp to log events"""
    event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return event_dict


def add_log_level(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add log level to event dict"""
    event_dict["level"] = method_name.upper()
    return event_dict


class JSONRenderer:
    """Custom JSON renderer for structured logging"""

    def __call__(self, logger: Any, name: str, event_dict: EventDict) -> str:
        return json.dumps(event_dict, default=str)


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    log_format: str = "json",
    run_id: Optional[str] = None,
    max_file_size_mb: int = 10,
    backup_count: int = 5,
) -> None:
    """
    Configure structured logging for the application with log rotation.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files
        log_format: Output format ("json" or "text")
        run_id: Optional run identifier for log file naming
        max_file_size_mb: Max size of log file before rotation (MB)
        backup_count: Number of backup log files to keep
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if run_id:
        log_filename = f"job_refresh_{run_id}_{timestamp}.log"
    else:
        log_filename = f"job_refresh_{timestamp}.log"

    log_file = log_path / log_filename

    # Use RotatingFileHandler for automatic log rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_file_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=backup_count,
        encoding="utf-8",
    )

    handlers = [
        logging.StreamHandler(sys.stdout),
        file_handler,
    ]

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        handlers=handlers,
    )

    processors = [
        structlog.stdlib.filter_by_level,
        add_timestamp,
        add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        processors.append(JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "job_refresh") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance"""
    return structlog.get_logger(name)


class JobLogger:
    """Specialized logger for job processing operations"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.logger = get_logger("job_processor")

    def log_run_start(self, total_jobs: int) -> None:
        """Log the start of a processing run"""
        self.logger.info(
            "job_run_started",
            run_id=self.run_id,
            total_jobs=total_jobs,
            log_event="run_start",
        )

    def log_run_complete(
        self,
        total: int,
        successful: int,
        failed: int,
        skipped: int,
        duration_seconds: float,
    ) -> None:
        """Log completion of processing run"""
        self.logger.info(
            "job_run_completed",
            run_id=self.run_id,
            total_jobs=total,
            successful=successful,
            failed=failed,
            skipped=skipped,
            duration_seconds=round(duration_seconds, 2),
            success_rate=round(successful / total * 100, 2) if total > 0 else 0,
            log_event="run_complete",
        )

    def log_vacancy_start(self, vacancy_id: str, title: str) -> None:
        """Log start of vacancy processing"""
        self.logger.info(
            "vacancy_processing_started",
            run_id=self.run_id,
            vacancy_id=vacancy_id,
            vacancy_title=title,
            log_event="vacancy_start",
        )

    def log_vacancy_step(
        self, vacancy_id: str, step: str, status: str, details: Optional[dict] = None
    ) -> None:
        """Log a processing step for a vacancy"""
        log_data = {
            "run_id": self.run_id,
            "vacancy_id": vacancy_id,
            "step": step,
            "status": status,
            "log_event": "vacancy_step",
        }
        if details:
            log_data.update(details)

        if status == "success":
            self.logger.info("vacancy_step_completed", **log_data)
        elif status == "failed":
            self.logger.error("vacancy_step_failed", **log_data)
        else:
            self.logger.debug("vacancy_step_progress", **log_data)

    def log_vacancy_complete(
        self,
        vacancy_id: str,
        new_vacancy_id: Optional[str],
        status: str,
        duration_ms: int,
    ) -> None:
        """Log completion of vacancy processing"""
        self.logger.info(
            "vacancy_processing_completed",
            run_id=self.run_id,
            vacancy_id=vacancy_id,
            new_vacancy_id=new_vacancy_id,
            status=status,
            duration_ms=duration_ms,
            log_event="vacancy_complete",
        )

    def log_vacancy_error(
        self, vacancy_id: str, error: Exception, step: str
    ) -> None:
        """Log an error during vacancy processing"""
        self.logger.error(
            "vacancy_processing_error",
            run_id=self.run_id,
            vacancy_id=vacancy_id,
            step=step,
            error_type=type(error).__name__,
            error_message=str(error),
            log_event="vacancy_error",
        )

    def log_api_request(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: int,
        success: bool,
    ) -> None:
        """Log an API request"""
        log_method = self.logger.debug if success else self.logger.warning
        log_method(
            "api_request",
            run_id=self.run_id,
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=duration_ms,
            success=success,
            log_event="api_request",
        )

    def log_dry_run(self, action: str, details: dict) -> None:
        """Log a dry-run action that would be taken"""
        self.logger.info(
            "dry_run_action",
            run_id=self.run_id,
            action=action,
            log_event="dry_run",
            **details,
        )

    def log_circuit_breaker(self, consecutive_failures: int, threshold: int) -> None:
        """Log circuit breaker activation"""
        self.logger.error(
            "circuit_breaker_activated",
            run_id=self.run_id,
            consecutive_failures=consecutive_failures,
            threshold=threshold,
            log_event="circuit_breaker",
        )

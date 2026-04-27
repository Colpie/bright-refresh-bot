"""Reporting and alerting for job processing"""

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from typing import Optional

from ..config import AlertConfig
from ..utils.logging import get_logger
from .state import StateManager


@dataclass
class FailureDetail:
    """Details of a processing failure"""

    vacancy_id: str
    error_message: str
    step: str


@dataclass
class ProcessingReport:
    """Complete report of a processing run"""

    run_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_vacancies: int
    successful: int
    failed: int
    skipped: int
    duration_seconds: float
    failures: list[FailureDetail] = field(default_factory=list)
    dry_run: bool = False

    @property
    def success_rate(self) -> float:
        if self.total_vacancies == 0:
            return 0.0
        return (self.successful / self.total_vacancies) * 100

    @property
    def status(self) -> str:
        if self.total_vacancies == 0:
            return "empty"
        if self.failed == 0:
            return "success"
        if self.successful == 0:
            return "failed"
        return "partial"

    def to_markdown(self) -> str:
        status_label = {
            "success": "[OK]",
            "failed": "[FAILED]",
            "partial": "[PARTIAL]",
            "empty": "[EMPTY]",
        }

        lines = [
            f"# Job Refresh Report {status_label.get(self.status, '')}",
            "",
            f"**Run ID:** `{self.run_id}`",
            f"**Started:** {self.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ]

        if self.completed_at:
            lines.append(
                f"**Completed:** {self.completed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )

        lines.extend(
            [
                f"**Duration:** {self.duration_seconds:.1f} seconds",
                "",
                "## Summary",
                "",
                "| Metric | Count |",
                "|--------|-------|",
                f"| Total Vacancies | {self.total_vacancies} |",
                f"| Successful | {self.successful} |",
                f"| Failed | {self.failed} |",
                f"| Skipped | {self.skipped} |",
                f"| Success Rate | {self.success_rate:.1f}% |",
            ]
        )

        if self.dry_run:
            lines.extend(
                [
                    "",
                    "> **Note:** This was a DRY RUN. No actual changes were made.",
                ]
            )

        if self.failures:
            lines.extend(
                [
                    "",
                    "## Failures",
                    "",
                    "| Vacancy ID | Step | Error |",
                    "|------------|------|-------|",
                ]
            )

            for failure in self.failures[:20]:
                error_short = failure.error_message
                if len(error_short) > 50:
                    error_short = error_short[:50] + "..."

                error_short = error_short.replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| {failure.vacancy_id} | {failure.step} | {error_short} |"
                )

            if len(self.failures) > 20:
                lines.append(
                    f"| ... | ... | ({len(self.failures) - 20} more failures) |"
                )

        return "\n".join(lines)

    def to_html(self) -> str:
        status_color = {
            "success": "#28a745",
            "failed": "#dc3545",
            "partial": "#ffc107",
            "empty": "#6c757d",
        }

        color = status_color.get(self.status, "#6c757d")

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; color: #222; }}
        .header {{ background-color: {color}; color: white; padding: 20px; border-radius: 5px; }}
        .summary {{ margin: 20px 0; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .success {{ color: #28a745; }}
        .failure {{ color: #dc3545; }}
        .note {{ background-color: #fff3cd; padding: 10px; border-radius: 5px; margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Job Refresh Report</h1>
        <p>Run ID: {escape(self.run_id)}</p>
    </div>

    <div class="summary">
        <h2>Summary</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Vacancies</td><td>{self.total_vacancies}</td></tr>
            <tr><td>Successful</td><td class="success">{self.successful}</td></tr>
            <tr><td>Failed</td><td class="failure">{self.failed}</td></tr>
            <tr><td>Skipped</td><td>{self.skipped}</td></tr>
            <tr><td>Success Rate</td><td>{self.success_rate:.1f}%</td></tr>
            <tr><td>Duration</td><td>{self.duration_seconds:.1f} seconds</td></tr>
        </table>
    </div>
"""

        if self.dry_run:
            html += """
    <div class="note">
        <strong>Note:</strong> This was a DRY RUN. No actual changes were made.
    </div>
"""

        if self.failures:
            html += """
    <div class="failures">
        <h2>Failures</h2>
        <table>
            <tr><th>Vacancy ID</th><th>Step</th><th>Error</th></tr>
"""

            for failure in self.failures[:20]:
                html += (
                    "            <tr>"
                    f"<td>{escape(failure.vacancy_id)}</td>"
                    f"<td>{escape(failure.step)}</td>"
                    f"<td>{escape(failure.error_message)}</td>"
                    "</tr>\n"
                )

            if len(self.failures) > 20:
                html += (
                    f"            <tr><td colspan='3'>... and "
                    f"{len(self.failures) - 20} more failures</td></tr>\n"
                )

            html += """
        </table>
    </div>
"""

        html += """
</body>
</html>
"""
        return html

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_vacancies": self.total_vacancies,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": self.success_rate,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "dry_run": self.dry_run,
            "failures": [
                {
                    "vacancy_id": f.vacancy_id,
                    "step": f.step,
                    "error_message": f.error_message,
                }
                for f in self.failures
            ],
        }


class Reporter:
    """Report generation and alerting"""

    def __init__(self, state_manager: StateManager, alert_config: AlertConfig):
        self.state_manager = state_manager
        self.alert_config = alert_config
        self.logger = get_logger("reporter")

    async def generate_report(
        self,
        run_id: str,
        dry_run: bool = False,
    ) -> Optional[ProcessingReport]:
        summary = await self.state_manager.get_run_summary(run_id)

        if not summary:
            self.logger.warning("run_not_found", run_id=run_id)
            return None

        failed_records = await self.state_manager.get_failed_records(run_id)

        failures: list[FailureDetail] = []

        for record in failed_records:
            step = "unknown"

            if record.duplicated_at and not record.closed_at:
                step = "close"
            elif record.status == "failed":
                step = "duplicate"

            failures.append(
                FailureDetail(
                    vacancy_id=record.original_vacancy_id,
                    error_message=record.error_message or "Unknown error",
                    step=step,
                )
            )

        report = ProcessingReport(
            run_id=run_id,
            started_at=summary.started_at,
            completed_at=summary.completed_at,
            total_vacancies=summary.total_jobs,
            successful=summary.successful,
            failed=summary.failed,
            skipped=summary.skipped,
            duration_seconds=summary.duration_seconds or 0.0,
            failures=failures,
            dry_run=dry_run,
        )

        self.logger.info(
            "report_generated",
            run_id=run_id,
            total=report.total_vacancies,
            successful=report.successful,
            failed=report.failed,
            skipped=report.skipped,
            status=report.status,
        )

        return report

    async def send_alerts(self, report: ProcessingReport) -> None:
        """Send alerts based on report status"""

        if not self.alert_config.enabled:
            self.logger.info("alerts_disabled", run_id=report.run_id)
            return

        # Telegram is a compact run notification, so send it for success and failure.
        if self.alert_config.telegram.bot_token and self.alert_config.telegram.chat_id:
            await self._send_telegram_alert(report)

        should_alert = (
            report.status == "failed"
            or report.status == "partial"
            or report.failed > self.alert_config.failure_threshold
            or (
                report.total_vacancies > 0
                and (report.failed / report.total_vacancies)
                > self.alert_config.failure_rate_threshold
            )
        )

        # Avoid noisy emails/webhooks for clean success runs.
        if not should_alert:
            self.logger.info(
                "alert_skipped",
                run_id=report.run_id,
                reason="success_or_below_threshold",
            )
            return

        if self.alert_config.email.recipients:
            await self._send_email_alert(report)

        if self.alert_config.webhook.url:
            await self._send_webhook_alert(report)

    async def _send_email_alert(self, report: ProcessingReport) -> None:
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            email_config = self.alert_config.email

            if not email_config.smtp_user or not email_config.smtp_password:
                self.logger.warning(
                    "email_alert_skipped",
                    reason="missing_smtp_credentials",
                )
                return

            msg = MIMEMultipart("alternative")
            msg["Subject"] = (
                f"Job Refresh Report - {report.status.upper()} - {report.run_id}"
            )
            msg["From"] = email_config.from_address
            msg["To"] = ", ".join(email_config.recipients)

            msg.attach(MIMEText(report.to_markdown(), "plain"))
            msg.attach(MIMEText(report.to_html(), "html"))

            await aiosmtplib.send(
                msg,
                hostname=email_config.smtp_host,
                port=email_config.smtp_port,
                username=email_config.smtp_user,
                password=email_config.smtp_password,
                start_tls=True,
            )

            self.logger.info(
                "email_alert_sent",
                run_id=report.run_id,
                recipients=email_config.recipients,
            )

        except ImportError:
            self.logger.warning(
                "email_alert_skipped",
                reason="aiosmtplib_not_installed",
            )
        except Exception as e:
            self.logger.error(
                "email_alert_failed",
                run_id=report.run_id,
                error=str(e),
            )

    async def _send_webhook_alert(self, report: ProcessingReport) -> None:
        try:
            import httpx

            webhook_url = self.alert_config.webhook.url

            if not webhook_url:
                return

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=report.to_dict(),
                    timeout=30,
                )

            if 200 <= response.status_code < 300:
                self.logger.info(
                    "webhook_alert_sent",
                    run_id=report.run_id,
                    url=webhook_url,
                )
            else:
                self.logger.warning(
                    "webhook_alert_failed",
                    run_id=report.run_id,
                    status_code=response.status_code,
                    body=response.text[:200],
                )

        except Exception as e:
            self.logger.error(
                "webhook_alert_error",
                run_id=report.run_id,
                error=str(e),
            )

    async def _send_telegram_alert(self, report: ProcessingReport) -> None:
        try:
            import httpx

            tg = self.alert_config.telegram

            if not tg.bot_token or not tg.chat_id:
                return

            status_icon = {
                "success": "OK",
                "failed": "FAILED",
                "partial": "WARNING",
                "empty": "INFO",
            }

            icon = status_icon.get(report.status, "INFO")

            lines = [
                f"[{icon}] Job Refresh Report",
                "",
                f"Status: {report.status.upper()}",
                f"Run: {report.run_id}",
                f"Total: {report.total_vacancies}",
                f"Success: {report.successful}",
                f"Failed: {report.failed}",
                f"Skipped: {report.skipped}",
                f"Rate: {report.success_rate:.1f}%",
                f"Duration: {report.duration_seconds:.0f}s",
            ]

            if report.dry_run:
                lines.extend(["", "DRY RUN - no real changes"])

            if report.failures:
                lines.append("")
                lines.append(f"Top errors ({min(5, len(report.failures))}):")

                for failure in report.failures[:5]:
                    error_short = failure.error_message.replace("\n", " ")
                    if len(error_short) > 80:
                        error_short = error_short[:80] + "..."

                    lines.append(
                        f"- {failure.vacancy_id} [{failure.step}]: {error_short}"
                    )

            text = "\n".join(lines)
            url = f"https://api.telegram.org/bot{tg.bot_token}/sendMessage"

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": tg.chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )

            if response.status_code == 200:
                self.logger.info(
                    "telegram_alert_sent",
                    run_id=report.run_id,
                )
            else:
                self.logger.warning(
                    "telegram_alert_failed",
                    run_id=report.run_id,
                    status_code=response.status_code,
                    body=response.text[:200],
                )

        except Exception as e:
            self.logger.error(
                "telegram_alert_error",
                run_id=report.run_id,
                error=str(e),
            )
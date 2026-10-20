"""Durable handoff of Bright refreshes; never infer a VDAB number from a Bright ID."""

import json
import re
from urllib.parse import urlsplit

import httpx

from ..config import PortalConfig
from ..utils.logging import get_logger
from .state import StateManager


def bright_origin(base_url: str) -> str:
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Bright handoff requires an HTTPS API URL without credentials or query parameters")
    return f"https://{url.hostname.lower()}" + (f":{url.port}" if url.port else "")


def publication_number(response: object, path: str) -> str | None:
    # Empty by default: the actual response contract must be confirmed first.
    if not path:
        return None
    value = response
    try:
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    number = str(value)
    return number if re.fullmatch(r"[1-9][0-9]{5,11}", number) else None


async def flush_portal_outbox(state: StateManager, config: PortalConfig, event_id: str | None = None, retry_review: bool = False) -> int:
    if not config.endpoint or not config.token:
        return 0
    url = urlsplit(config.endpoint)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or len(config.token) < 32:
        raise ValueError("Portal endpoint must be HTTPS without credentials/query, with a token of at least 32 characters")
    applied = 0
    logger = get_logger("portal_refresh")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for event in await state.pending_portal_refreshes(event_id):
            number = publication_number(json.loads(event["publication_response"]), config.vdab_json_path)
            if event["status"] == "needs_review" and not retry_review:
                continue
            if event["status"] == "awaiting_vdab" and number is None:
                continue
            payload = {key: event[key] for key in ("event_id", "bright_origin", "original_bright_id", "new_bright_id")}
            payload["vdab_job_id"] = number
            try:
                response = await client.post(config.endpoint, json=payload,
                    headers={"Authorization": f"Bearer {config.token}", "Accept": "application/json"})
                if response.status_code != 200:
                    raise RuntimeError(f"Portal HTTP {response.status_code}")
                status = response.json().get("status")
                if status not in {"applied", "awaiting_vdab", "needs_review"}:
                    raise RuntimeError("Portal returned an unrecognised acknowledgement")
                await state.record_portal_refresh(event["event_id"], status)
                applied += int(status == "applied")
                logger.info("portal_refresh_acknowledged", event_id=event["event_id"], status=status)
            except Exception as exc:
                # Never log request headers, tokens, response bodies or transport exception URLs.
                error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                await state.record_portal_refresh(event["event_id"], "pending", error)
                logger.warning("portal_refresh_pending", event_id=event["event_id"], reason=error)
                break
    return applied

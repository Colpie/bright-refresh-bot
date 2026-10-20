"""Publication contracts, durable retry and handoff isolation; no live requests."""
import hashlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.config import PortalConfig
from src.services.portal import bright_origin, publication_number, flush_portal_outbox
from src.services.state import StateManager


def test_number_requires_an_explicit_path_and_valid_value():
    response = {"results": [{"verified_number": "74809933", "vacancy_id": 999999}]}
    assert publication_number(response, "") is None
    assert publication_number(response, "results.0.verified_number") == "74809933"
    for value in [True, "https://example.test/74809933", "74809933 extra", 0, {}, None]:
        assert publication_number({"id": value}, "id") is None
    assert publication_number(response, "missing.value") is None


def test_bright_origin_preserves_environment_and_rejects_credentials():
    assert bright_origin("https://match.b-bright.be/backend/index.php/api/") == "https://match.b-bright.be"
    assert bright_origin("https://match-staging.b-bright.be/api") == "https://match-staging.b-bright.be"
    with pytest.raises(ValueError):
        bright_origin("https://secret@example.test/api")


@pytest.mark.asyncio
async def test_retry_survives_database_reopen_and_does_not_republish(tmp_path):
    path = str(tmp_path / "state.db")
    state = StateManager(path)
    await state.initialize()
    for _ in range(2):
        await state.queue_portal_refresh("https://match.b-bright.be", 100, 200, {"number": "74809933"})
    await state.close()
    state = StateManager(path)
    await state.initialize()
    config = PortalConfig(endpoint="https://portal.example.test/api/integrations/bright-refresh", token="x"*40, vdab_json_path="number")
    responses = [httpx.Response(503), httpx.Response(200, json={"status": "applied"})]
    calls = []
    async def post(url, **kwargs):
        calls.append(kwargs["json"])
        return responses.pop(0)
    with patch("src.services.portal.httpx.AsyncClient.post", side_effect=post):
        assert await flush_portal_outbox(state, config) == 0
        assert len(await state.pending_portal_refreshes()) == 1
        assert await flush_portal_outbox(state, config) == 1
        assert await state.pending_portal_refreshes() == []
        assert await flush_portal_outbox(state, config) == 0
    assert calls[0] == calls[1]
    assert calls[0]["vdab_job_id"] == "74809933"
    assert calls[0]["event_id"] == hashlib.sha256(b"https://match.b-bright.be|100|200").hexdigest()
    await state.close()


@pytest.mark.asyncio
async def test_missing_number_never_guesses_from_other_response_ids(state_manager):
    await state_manager.queue_portal_refresh("https://match.b-bright.be", 100, 200, {"results": [999999]})
    config = PortalConfig(endpoint="https://portal.example.test/api/integrations/bright-refresh", token="x"*40)
    with patch("src.services.portal.httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = httpx.Response(200, json={"status": "awaiting_vdab"})
        await flush_portal_outbox(state_manager, config)
        assert post.call_args.kwargs["json"]["vdab_job_id"] is None
        await flush_portal_outbox(state_manager, config)
        post.assert_awaited_once()
    assert (await state_manager.pending_portal_refreshes())[0]["status"] == "awaiting_vdab"


@pytest.mark.asyncio
async def test_disabled_bridge_makes_no_requests(state_manager):
    await state_manager.queue_portal_refresh("https://match.b-bright.be", 100, 200, {})
    with patch("src.services.portal.httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        assert await flush_portal_outbox(state_manager, PortalConfig()) == 0
        post.assert_not_called()


@pytest.mark.asyncio
async def test_confirming_path_later_completes_saved_response(state_manager):
    await state_manager.queue_portal_refresh("https://match.b-bright.be", 100, 200, {"actual_number": "74809933"})
    config = PortalConfig(endpoint="https://portal.example.test/api/integrations/bright-refresh", token="x"*40)
    with patch("src.services.portal.httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = httpx.Response(200, json={"status": "awaiting_vdab"})
        await flush_portal_outbox(state_manager, config)
        config.vdab_json_path = "actual_number"
        post.return_value = httpx.Response(200, json={"status": "applied"})
        assert await flush_portal_outbox(state_manager, config) == 1
        assert post.await_count == 2


@pytest.mark.asyncio
async def test_rejected_handoff_remains_pending(state_manager):
    await state_manager.queue_portal_refresh("https://match.b-bright.be", 100, 200, {})
    config = PortalConfig(endpoint="https://portal.example.test/api/integrations/bright-refresh", token="x"*40)
    with patch("src.services.portal.httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = httpx.Response(409)
        await flush_portal_outbox(state_manager, config)
    event = (await state_manager.pending_portal_refreshes())[0]
    assert event["status"] == "pending"
    assert event["attempts"] == 1
    assert event["last_error"] == "Portal HTTP 409"


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,publication,expected", [(False, {"number": "74809933"}, 1), (False, None, 0), (True, {"number": "74809933"}, 0)])
async def test_pipeline_only_saves_real_successful_vdab_publications(state_manager, dry_run, publication, expected):
    from unittest.mock import MagicMock
    from src.api.models import Vacancy
    from src.config import ProcessorConfig
    from src.services.processor import JobProcessor
    client = MagicMock()
    client.config.base_url = "https://match.b-bright.be/api"
    processor = JobProcessor(client, ProcessorConfig(), state_manager, dry_run=dry_run)
    processor._run_id = "test-handoff"
    processor._job_logger = MagicMock()
    await state_manager.start_run(processor._run_id, 1)
    await state_manager.add_vacancy_record(processor._run_id, "100")
    processor._step_fetch = AsyncMock(return_value=MagicMock())
    processor._step_backup_documents = AsyncMock()
    processor._step_duplicate = AsyncMock(return_value="200")
    processor._step_open = AsyncMock()
    processor._step_update_province = AsyncMock()
    processor._step_offline = AsyncMock(return_value=True)
    processor._step_close = AsyncMock(return_value=True)
    processor._step_multipost = AsyncMock(return_value=publication)
    result = await processor._process_single(Vacancy(id="100", title="Operator"))
    assert result.success
    assert len(await state_manager.pending_portal_refreshes()) == expected

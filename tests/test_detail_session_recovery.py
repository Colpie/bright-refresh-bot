import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.client import BrightStaffingClient
from src.config import ApiConfig, ProcessorConfig
from src.services.processor import JobProcessor


@pytest.mark.asyncio
async def test_unreadable_detail_reauthenticates_once_without_mutation():
    calls = []
    def respond(request):
        calls.append(request.url.path)
        assert request.url.path == '/index.php/vacancy/detail'
        if len(calls) == 1:
            return httpx.Response(200, text='<input name="password">')
        return httpx.Response(200, json={'status': 'success', 'results': {'detail': {'uid': '94457', 'info_internal': 'Byner: 135'}}})
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api', web_username='test', web_password='test'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client._web_session_cookies = {'session': 'expired'}
    client.web_login = AsyncMock(return_value=True)
    client.verify_web_session = AsyncMock(return_value=True)
    try:
        assert await client.get_vacancy_internal_info('94457') == 'Byner: 135'
        assert len(calls) == 2
        client.web_login.assert_awaited_once()
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_unverified_relogin_does_not_repeat_detail_read():
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api', web_username='test', web_password='test'))
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text='<html>login</html>')
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client._web_session_cookies = {'session': 'expired'}
    client.web_login = AsyncMock(return_value=True)
    client.verify_web_session = AsyncMock(return_value=False)
    try:
        from src.api.models import ApiError
        with pytest.raises(ApiError, match='non-JSON'):
            await client.get_vacancy_internal_info('94457')
        assert len(requests) == 1
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_full_live_run_rejects_login_cookie_without_verified_session():
    client = MagicMock()
    client.config = ApiConfig(web_username='test', web_password='test')
    client.web_login = AsyncMock(return_value=True)
    client.verify_web_session = AsyncMock(return_value=False)
    processor = JobProcessor(client, ProcessorConfig(), MagicMock(), dry_run=False)
    processor._vacancy_id = None
    with pytest.raises(RuntimeError, match='verified Bright web session'):
        await processor._ensure_web_session()
    client.verify_web_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_batch_stops_before_mutations_when_detail_access_fails(mock_client, state_manager):
    from src.api.models import ApiError
    processor = JobProcessor(mock_client, ProcessorConfig(), state_manager, dry_run=False)
    processor._ensure_web_session = AsyncMock()
    mock_client.get_vacancy_internal_info.side_effect = ApiError(502, 'unconfirmed detail', '/vacancy/detail')
    with pytest.raises(ApiError):
        await processor.run()
    mock_client.add_vacancy.assert_not_awaited()
    mock_client.close_vacancy.assert_not_awaited()
    assert mock_client.get_vacancy_internal_info.await_count == 1

import httpx
import pytest
from src.api.client import BrightStaffingClient
from src.config import ApiConfig


def test_canonical_api_url_uses_web_root_without_backend_prefix():
    client = BrightStaffingClient(ApiConfig(base_url='https://match.brightstaffing.be/backend/index.php/api/'))
    assert client._web_base_url == 'https://match.brightstaffing.be'


def test_short_api_url_keeps_same_web_root():
    client = BrightStaffingClient(ApiConfig(base_url='https://match.b-bright.be/api'))
    assert client._web_base_url == 'https://match.b-bright.be'


@pytest.mark.asyncio
async def test_login_cookie_without_authenticated_page_is_rejected():
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<input name="password">')))
    client._web_session_cookies = {'session': 'test'}
    try:
        assert await client.verify_web_session() is False
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_authenticated_bright_page_is_confirmed():
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='const User = JSON.parse("{}");')))
    client._web_session_cookies = {'session': 'test'}
    try:
        assert await client.verify_web_session() is True
    finally:
        await client._client.aclose()

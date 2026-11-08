import httpx
import pytest
from src.api.client import BrightStaffingClient
from src.config import ApiConfig


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['multipost_vacancy', 'delete_multiposting_vacancy'])
@pytest.mark.parametrize('payload,expected', [
    ({'status': 'success', 'results': [{'status': 'error', 'result': 'Error parsing VDAB response'}]}, False),
    ({'status': 'success', 'results': [None]}, False),
    ({'status': 'success', 'results': [{'status': 'success'}, {'status': 'error'}]}, False),
    ({'status': 'success', 'results': [{'status': 'success'}]}, True),
    ({'status': 'error', 'results': []}, False),
])
async def test_channel_error_overrides_success_envelope(method, payload, expected):
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    client._web_session_cookies = {'session': 'test'}
    try:
        response = await getattr(client, method)('94457', 3)
        assert response.success is expected
    finally:
        await client._client.aclose()

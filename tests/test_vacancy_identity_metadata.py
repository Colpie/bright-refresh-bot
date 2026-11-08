import httpx
import pytest
from src.api.client import BrightStaffingClient
from src.api.models import ApiError
from src.config import ApiConfig


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['valid', 'empty', 'wrong_id', 'missing', 'login', 'redirect', 'error'])
async def test_internal_metadata_requires_exact_authenticated_detail(case):
    marker = 'Byner-ID: a15P400000EnUTgIAN | Byner: 135 | Klant: P&V Panels | Recruiter: Lisa'
    detail = {'uid': '93833', 'info_internal': marker if case != 'empty' else ''}
    if case == 'wrong_id':
        detail['uid'] = '999'
    if case == 'missing':
        del detail['info_internal']

    def respond(request):
        assert request.method == 'POST'
        assert request.url.path == '/index.php/vacancy/detail'
        assert request.content == b'uid=93833'
        if case == 'login':
            return httpx.Response(200, text='<input name="password">')
        if case == 'redirect':
            return httpx.Response(302, headers={'location': '/index.php/auth/login'})
        return httpx.Response(200, json={'status': 'error' if case == 'error' else 'success', 'results': {'detail': detail}})

    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client._web_session_cookies = {'session': 'test'}
    try:
        if case in ['valid', 'empty']:
            assert await client.get_vacancy_internal_info('93833') == detail['info_internal']
        else:
            with pytest.raises(ApiError):
                await client.get_vacancy_internal_info('93833')
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_metadata_without_session_stops_before_http_request():
    client = BrightStaffingClient(ApiConfig(base_url='https://test.b-bright.be/api'))
    with pytest.raises(ApiError):
        await client.get_vacancy_internal_info('93833')

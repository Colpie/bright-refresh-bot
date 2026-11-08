import httpx
import pytest
from src.api.client import BrightStaffingClient
from src.config import ApiConfig


@pytest.mark.asyncio
async def test_api_never_receives_or_overwrites_web_session():
    def api(request):
        assert 'web-session' not in request.headers.get('cookie','')
        return httpx.Response(200,json={'VDAB competences':[]},headers={'set-cookie':'PHPSESSID=api-session; Path=/'})
    def web(request):
        assert 'web-session' in request.headers.get('cookie','')
        assert 'api-session' not in request.headers.get('cookie','')
        return httpx.Response(200,json={'status':'success','results':{'detail':{'uid':'100','info_internal':''}}})
    c=BrightStaffingClient(ApiConfig(base_url='https://match.b-bright.be/api',rate_limit=1000))
    c._client=httpx.AsyncClient(transport=httpx.MockTransport(web))
    c._api_client=httpx.AsyncClient(transport=httpx.MockTransport(api))
    c._client.cookies.set('PHPSESSID','web-session',domain='match.b-bright.be',path='/')
    c._web_session_cookies={'PHPSESSID':'web-session'}
    try:
        await c.get_vacancy_competences('100')
        assert await c.get_vacancy_internal_info('100')==''
        assert c._client.cookies.get('PHPSESSID')=='web-session'
        assert c._api_client.cookies.get('PHPSESSID')=='api-session'
    finally:await c.__aexit__(None,None,None)
    assert c._client is None and c._api_client is None


@pytest.mark.asyncio
async def test_context_owns_two_independent_cookie_jars():
    c=BrightStaffingClient(ApiConfig())
    async with c:
        assert c._client is not c._api_client
        assert c._client.cookies is not c._api_client.cookies
    assert c._client is None and c._api_client is None

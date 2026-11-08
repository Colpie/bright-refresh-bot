from unittest.mock import AsyncMock
import pytest
from src.api.client import BrightStaffingClient
from src.api.models import ApiError, ApiResponse
from src.config import ApiConfig


def detail(closed):
    return {'detail': {'is_closed': str(closed), 'closereason_id': '3'}}


def client():
    c=BrightStaffingClient(ApiConfig())
    c._web_session_cookies={'session':'test'}
    return c


@pytest.mark.asyncio
async def test_already_closed_skips_write():
    c=client();c.get_vacancy_detail=AsyncMock(return_value=detail(1));c.request=AsyncMock()
    result=await c.close_vacancy('94455',3)
    assert result.success and result.data['confirmed_from_detail']
    c.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_502_after_committed_close_is_confirmed_without_repeat():
    c=client();c.get_vacancy_detail=AsyncMock(side_effect=[detail(0),detail(1)])
    c.request=AsyncMock(side_effect=ApiError(502,'Bad Gateway','/vacancy/closeVacancy'))
    result=await c.close_vacancy('94455',3)
    assert result.success
    c.request.assert_awaited_once_with('/vacancy/closeVacancy',{'vacancy_id':'94455','closereason_id':3},retryable=False)


@pytest.mark.asyncio
async def test_502_without_committed_close_stays_failed():
    c=client();c.get_vacancy_detail=AsyncMock(return_value=detail(0))
    c.request=AsyncMock(side_effect=ApiError(502,'Bad Gateway','/vacancy/closeVacancy'))
    with pytest.raises(ApiError):await c.close_vacancy('94455',3)
    c.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_success_without_closed_state_is_not_reported_as_success():
    c=client();c.get_vacancy_detail=AsyncMock(return_value=detail(0))
    c.request=AsyncMock(return_value=ApiResponse(success=True,data={},status_code=200))
    with pytest.raises(ApiError,match='did not confirm'):await c.close_vacancy('94455',3)

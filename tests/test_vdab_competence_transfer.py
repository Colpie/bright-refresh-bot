from unittest.mock import AsyncMock
import pytest
from src.api.models import Vacancy, ApiResponse
from src.api.vacancy import VacancyService


@pytest.mark.asyncio
async def test_selected_competences_survive_empty_public_endpoint(mock_client):
    codes=['17775','16810','63137','63139']
    mock_client.get_vacancy_detail.return_value={'detail':{'info_internal':'Byner: 135'},'vdab_competences':[{'vdab_competence_code':code} for code in codes]}
    mock_client.get_vacancy_competences=AsyncMock(return_value=ApiResponse(success=True,data={'VDAB competences':[]},status_code=200))
    complete=await VacancyService(mock_client).get_complete_vacancy(Vacancy(id='94457',title='Operator'))
    payload=complete.build_duplication_payload()
    assert payload['vdab_competences']==[17775,16810,63137,63139]
    assert payload['info_internal']=='Byner: 135'


@pytest.mark.asyncio
async def test_unknown_competence_state_stops_before_creating(mock_client):
    mock_client.get_vacancy_detail.return_value={'detail':{'info_internal':''}}
    with pytest.raises(RuntimeError,match='does not confirm'):
        await VacancyService(mock_client).get_complete_vacancy(Vacancy(id='94457',title='Operator'))
    mock_client.add_vacancy.assert_not_awaited()
    mock_client.close_vacancy.assert_not_awaited()

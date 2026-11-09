from unittest.mock import AsyncMock, MagicMock
import pytest
from src.api.client import BrightStaffingClient
from src.api.models import Vacancy, CompleteVacancy
from src.config import ProcessorConfig
from src.services.processor import JobProcessor


@pytest.mark.parametrize('message,expected', [
    ('VDAB sjabloon is niet ingevuld!', True),
    ('Minimum 1 studiekennis competentie is verplicht', True),
    ('Kwaliteit-blokkerend: specifieke studies vereist', True),
    ('Error parsing VDAB response', False),
    ('Access denied', False),
])
def test_content_rejection_is_not_a_technical_failure(message, expected):
    data = {'status':'success','results':[{'status':'error','result':message}]}
    assert BrightStaffingClient.is_vdab_content_rejection(data) is expected
    assert not BrightStaffingClient.is_vdab_content_rejection({'status':'error','results':data['results']})


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['template','studies'])
async def test_incomplete_source_remains_untouched(state_manager, missing):
    client=MagicMock()
    processor=JobProcessor(client,ProcessorConfig(),state_manager,dry_run=False)
    processor._run_id='preflight';processor._job_logger=MagicMock()
    await state_manager.start_run('preflight',1)
    await state_manager.add_vacancy_record('preflight','100')
    raw={'vdab_jobcategory_id':'I160401-3','studies':[{'study_id':'3'}]}
    raw['vdab_jobcategory_id' if missing=='template' else 'studies']='' if missing=='template' else []
    vacancy=Vacancy(id='100',title='Operator',raw_data=raw)
    processor.vacancy_service.get_complete_vacancy=AsyncMock(return_value=CompleteVacancy(vacancy=vacancy))
    processor._step_duplicate=AsyncMock()
    processor._step_offline=AsyncMock()
    processor._step_close=AsyncMock()
    result=await processor._process_single(vacancy)
    assert not result.success and result.new_vacancy_id is None
    assert 'oorspronkelijke vacature behouden' in result.error_message
    processor._step_duplicate.assert_not_awaited()
    processor._step_offline.assert_not_awaited()
    processor._step_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_studies_and_template_survive_payload(mock_client):
    from src.api.vacancy import VacancyService
    mock_client.get_vacancy_detail.return_value={
        'detail':{'info_internal':'Byner: 135','vdab_jobcategory_id':'I160401-3','vdab_jobcategory_name':'Mecanicien'},
        'vdab_competences':[], 'studies':[{'study_id':'637','study_name':'Techniek'}]}
    vacancy=Vacancy(id='100',title='Operator',raw_data={'studies':[{'level1_id':'3'}]})
    complete=await VacancyService(mock_client).get_complete_vacancy(vacancy)
    payload=complete.build_duplication_payload()
    assert payload['vdab_jobcategory_id']=='I160401-3'
    assert payload['studies']==[{'study_id':637}]


@pytest.mark.asyncio
async def test_missing_template_recovery_records_review_and_continues(tmp_path):
    from src.api.models import ApiResponse
    from src.services.run_recovery import recover_run
    from tests.test_run_recovery import fake_client
    client,rows=fake_client()
    rows['200']['multiposting'][0]['is_published']='1'
    client.multipost_vacancy=AsyncMock(return_value=ApiResponse(success=False,status_code=200,
        data={'status':'success','results':[{'status':'error','result':'VDAB sjabloon is niet ingevuld!'}]}))
    result=await recover_run(client,{'origin':client._web_base_url,'pairs':[{'old_id':'100','new_id':'200'}]},tmp_path)
    assert result=={'total':1,'completed':0,'review':1,'failed':0}


@pytest.mark.asyncio
@pytest.mark.parametrize('error,second_processed', [
    ('VDAB content validation: ontbrekend VDAB-sjabloon; geen kopie aangemaakt', True),
    ('Publication requires review for existing new vacancy 200: VDAB content validation', True),
    ('Publication failed for existing new vacancy 200: Error parsing VDAB response', False),
])
async def test_content_issue_does_not_stop_other_jobs_but_technical_issue_does(state_manager,error,second_processed):
    from src.services.processor import ProcessingResult
    processor=JobProcessor(MagicMock(),ProcessorConfig(batch_size=1),state_manager,dry_run=False)
    processor._run_id='batch-preflight';processor._job_logger=MagicMock()
    await state_manager.start_run(processor._run_id,2)
    for uid in ['100','101']:
        await state_manager.add_vacancy_record(processor._run_id,uid)
    processor._process_single=AsyncMock(side_effect=[
        ProcessingResult(original_vacancy_id='100',success=False,error_message=error),
        ProcessingResult(original_vacancy_id='101',success=True,new_vacancy_id='201')])
    await processor._process_vacancies([Vacancy(id=uid,title='Operator') for uid in ['100','101']])
    assert processor._process_single.await_count==(2 if second_processed else 1)

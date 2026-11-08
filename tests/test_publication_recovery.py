from unittest.mock import AsyncMock, MagicMock
import pytest
from src.api.models import ApiResponse, Vacancy
from src.services.publication_recovery import recover_publication
from src.services.processor import JobProcessor
from src.config import ProcessorConfig


def detail(uid, closed, website='1', vdab=None):
    return {'detail': {'uid': uid, 'is_closed': closed, 'function': 'Operator', 'enterprise_id': '123', 'info_internal': 'Byner: 135'},
            'multiposting': [{'uid': '1', 'is_published': website}, {'uid': '3', 'is_published': vdab}]}


@pytest.mark.asyncio
async def test_recovery_only_publishes_missing_channel_and_never_duplicates():
    client = MagicMock()
    client.get_vacancy_detail = AsyncMock(side_effect=[detail('100','1'),detail('200','0'),detail('200','0',vdab='1')])
    client.multipost_vacancy = AsyncMock(return_value=ApiResponse(success=True,data={},status_code=200))
    result = await recover_publication(client,'100','200',[1,3])
    client.multipost_vacancy.assert_awaited_once_with('200',3)
    client.add_vacancy.assert_not_called()
    client.close_vacancy.assert_not_called()
    assert result['channels'][-1]['status']=='published'


@pytest.mark.asyncio
async def test_recovery_rejects_different_identity_before_publication():
    client=MagicMock()
    wrong=detail('200','0');wrong['detail']['info_internal']='Byner: 999'
    client.get_vacancy_detail=AsyncMock(side_effect=[detail('100','1'),wrong])
    client.multipost_vacancy=AsyncMock()
    with pytest.raises(RuntimeError,match='does not match'):
        await recover_publication(client,'100','200',[1,3])
    client.multipost_vacancy.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_keeps_vdab_failure_visible_without_repeating():
    client=MagicMock()
    client.get_vacancy_detail=AsyncMock(side_effect=[detail('100','1'),detail('200','0')])
    client.multipost_vacancy=AsyncMock(return_value=ApiResponse(success=False,data={'results':[{'status':'error'}]},status_code=200))
    with pytest.raises(RuntimeError,match='channel 3'):
        await recover_publication(client,'100','200',[1,3])
    client.multipost_vacancy.assert_awaited_once()


@pytest.mark.asyncio
async def test_multipost_error_makes_pipeline_fail_with_existing_new_id(state_manager):
    client=MagicMock()
    processor=JobProcessor(client,ProcessorConfig(),state_manager,dry_run=False)
    processor._run_id='failed-publication';processor._job_logger=MagicMock()
    await state_manager.start_run(processor._run_id,1)
    await state_manager.add_vacancy_record(processor._run_id,'100')
    complete=MagicMock();complete.competences=[]
    processor._step_fetch=AsyncMock(return_value=complete)
    processor._step_backup_documents=AsyncMock()
    processor._step_duplicate=AsyncMock(return_value='200')
    processor._step_open=AsyncMock()
    processor._step_update_province=AsyncMock()
    processor._step_offline=AsyncMock(return_value=True)
    processor._step_close=AsyncMock(return_value=True)
    processor._step_multipost=AsyncMock(side_effect=RuntimeError('VDAB rejected'))
    result=await processor._process_single(Vacancy(id='100',title='Operator'))
    assert not result.success
    assert result.new_vacancy_id=='200'
    assert 'Publication failed' in result.error_message
    assert (await state_manager.get_failed_records(processor._run_id))[0].new_vacancy_id=='200'


@pytest.mark.asyncio
async def test_channel_rejection_is_not_swallowed(state_manager):
    client=MagicMock();client._web_session_cookies={'session':'test'}
    client.multipost_vacancy=AsyncMock(return_value=ApiResponse(success=False,data={'status':'success','results':[{'status':'error','result':'VDAB parsing'}]},status_code=200))
    processor=JobProcessor(client,ProcessorConfig(multipost_channels=[3]),state_manager,dry_run=False)
    with pytest.raises(RuntimeError,match='VDAB'):
        await processor._step_multipost('200')


@pytest.mark.asyncio
@pytest.mark.parametrize('publish_fails', [False, True])
async def test_retry_close_finishes_publication_before_marking_complete(state_manager, publish_fails):
    client=MagicMock();client.config.base_url='https://match.brightstaffing.be/api'
    processor=JobProcessor(client,ProcessorConfig(),state_manager,dry_run=False)
    processor._run_id='retry-close';processor._job_logger=MagicMock()
    await state_manager.start_run('retry-close',1)
    await state_manager.add_vacancy_record('retry-close','100')
    await state_manager.update_vacancy_status('retry-close','100','duplicated',new_vacancy_id='200')
    await state_manager.update_vacancy_status('retry-close','100','failed',error_message='Close original failed - new vacancy left open for safety')
    processor.vacancy_service.close_vacancy=AsyncMock(return_value=True)
    processor._step_multipost=AsyncMock(side_effect=RuntimeError('VDAB unavailable')) if publish_fails else AsyncMock(return_value={'status':'success'})
    await processor.retry_failed_closures('retry-close')
    processor._step_multipost.assert_awaited_once_with('200')
    row=(await state_manager.get_run_records('retry-close'))[0]
    assert row.status==('failed' if publish_fails else 'completed')
    assert row.new_vacancy_id=='200'
    assert len(await state_manager.pending_portal_refreshes())==(0 if publish_fails else 1)

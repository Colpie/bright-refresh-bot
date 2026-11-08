import copy
from unittest.mock import AsyncMock,MagicMock
import pytest
from src.services.run_recovery import repair_pair,recover_run,RecoveryReview
from src.api.models import ApiResponse


def snapshot(uid,closed,web,vdab,codes=()):
    return {'detail':{'uid':uid,'is_closed':closed,'closereason_id':'3','function':'Operator','enterprise_id':'123','info_internal':'','hash':'version','desc_function':'<p>Original</p>'},
        'studies':[],'competences':[], 'vdab_competences':[{'vdab_competence_code':code} for code in codes],
        'multiposting':[{'uid':'1','is_published':web},{'uid':'3','is_published':vdab}]}


def fake_client():
    c=MagicMock();c._web_base_url='https://match.b-bright.be'
    rows={'100':snapshot('100','1','1','1',('17775',)),'200':snapshot('200','0',None,None)}
    c.get_vacancy_detail=AsyncMock(side_effect=lambda uid:copy.deepcopy(rows[uid]))
    async def update(payload):
        assert payload['vacancy_id']=='200'
        assert payload['desc_function']=='<p>Original</p>'
        rows['200']['vdab_competences']=[{'vdab_competence_code':str(code)} for code in payload['vdab_competences']]
        return ApiResponse(success=True,data={'vacancy_id':'200'},status_code=200)
    async def open_old(uid):
        rows[uid]['detail']['is_closed']='0';return ApiResponse(success=True,data={},status_code=200)
    async def unpost(uid,channel):
        assert rows[uid]['detail']['is_closed']=='0'
        rows[uid]['multiposting'][1]['is_published']='0';return ApiResponse(success=True,data={},status_code=200)
    async def close_old(uid,*args):
        rows[uid]['detail']['is_closed']='1';return ApiResponse(success=True,data={},status_code=200)
    async def publish(uid,channel):
        assert rows['100']['detail']['is_closed']=='1'
        assert rows['100']['multiposting'][1]['is_published']=='0'
        rows[uid]['multiposting'][channel==3]['is_published']='1'
        return ApiResponse(success=True,data={},status_code=200)
    c.add_vacancy=AsyncMock(side_effect=update)
    c.open_vacancy=AsyncMock(side_effect=open_old)
    c.delete_multiposting_vacancy=AsyncMock(side_effect=unpost)
    c.close_vacancy=AsyncMock(side_effect=close_old)
    c.multipost_vacancy=AsyncMock(side_effect=publish)
    return c,rows


@pytest.mark.asyncio
async def test_complete_recovery_updates_existing_copy_then_unposts_closes_and_publishes(tmp_path):
    c,rows=fake_client()
    assert (await repair_pair(c,'100','200',tmp_path))['status']=='completed'
    assert c.add_vacancy.call_args.args[0]['vacancy_id']=='200'
    assert rows['100']['detail']['is_closed']=='1'
    assert rows['200']['multiposting'][1]['is_published']=='1'
    # Repeating the recovery makes no new write/publication.
    c.add_vacancy.reset_mock();c.open_vacancy.reset_mock();c.multipost_vacancy.reset_mock()
    await repair_pair(c,'100','200',tmp_path)
    c.add_vacancy.assert_not_awaited();c.open_vacancy.assert_not_awaited();c.multipost_vacancy.assert_not_awaited()


@pytest.mark.asyncio
async def test_pair_identity_change_stops_before_writes(tmp_path):
    c,rows=fake_client();rows['200']['detail']['enterprise_id']='999'
    with pytest.raises(RecoveryReview):await repair_pair(c,'100','200',tmp_path)
    c.add_vacancy.assert_not_awaited();c.open_vacancy.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_unpost_restores_source_closed_state_and_never_publishes(tmp_path):
    c,rows=fake_client();c.delete_multiposting_vacancy=AsyncMock(return_value=ApiResponse(success=False,data={},status_code=200))
    with pytest.raises(RuntimeError,match='removal failed'):await repair_pair(c,'100','200',tmp_path)
    assert rows['100']['detail']['is_closed']=='1'
    c.multipost_vacancy.assert_not_awaited()


@pytest.mark.asyncio
async def test_manifest_rejects_cross_host_or_reused_replacement(tmp_path):
    c,_=fake_client()
    for manifest in [ {'origin':'https://other.example','pairs':[]}, {'origin':c._web_base_url,'pairs':[{'old_id':'100','new_id':'200'},{'old_id':'101','new_id':'200'}]} ]:
        with pytest.raises(ValueError):await recover_run(c,manifest,tmp_path)
    c.get_vacancy_detail.assert_not_awaited()

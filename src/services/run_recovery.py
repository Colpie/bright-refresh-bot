"""Idempotent recovery of known pairs from one interrupted refresh run."""
import asyncio
import copy
import json
import os
from pathlib import Path
from ..api.client import BrightStaffingClient
from ..api.models import Vacancy, CompleteVacancy, VdabCompetence, VacancyCustomField


class RecoveryReview(RuntimeError):
    pass


def published(snapshot: dict, channel: int) -> bool:
    rows = [row for row in snapshot.get('multiposting', []) if str(row.get('uid')) == str(channel)]
    if len(rows) != 1:
        raise RecoveryReview(f'Channel {channel} not uniquely confirmed')
    return str(rows[0].get('is_published')) == '1'


def competence_codes(snapshot: dict) -> list[str]:
    rows = snapshot.get('vdab_competences')
    if not isinstance(rows, list) or any(not str(row.get('vdab_competence_code', '')).isdigit() for row in rows):
        raise RecoveryReview('Unconfirmed competence selection')
    return sorted(str(row['vdab_competence_code']) for row in rows)


async def repair_pair(client: BrightStaffingClient, old_id: str, new_id: str, backup: Path) -> dict:
    old = await client.get_vacancy_detail(old_id)
    new = await client.get_vacancy_detail(new_id)
    source, target = old['detail'], new['detail']
    if str(source.get('is_closed')) == '1' and str(source.get('closereason_id')) != '3':
        raise RecoveryReview('Source has another close reason; not republished automatically')
    for field in ['function', 'enterprise_id']:
        if not source.get(field) or source[field] != target.get(field):
            raise RecoveryReview(f'Pair differs on {field}')
    if str(target.get('is_closed')) != '0':
        raise RecoveryReview('Replacement has been closed; not reopened automatically')
    if target.get('info_internal') and source.get('info_internal') != target['info_internal']:
        raise RecoveryReview('Replacement identity changed')
    expected, actual = competence_codes(old), competence_codes(new)
    if actual and actual != expected:
        raise RecoveryReview('Replacement competence selection changed')
    backup.mkdir(parents=True, exist_ok=True)
    path = backup / f'{old_id}-{new_id}.before.json'
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'old': old, 'new': new}, handle)
    if actual != expected or source.get('info_internal', '') != target.get('info_internal', ''):
        if published(new, 3):
            raise RecoveryReview('Published replacement needs a content update; no blind republish')
        complete = CompleteVacancy(vacancy=Vacancy.from_api(copy.deepcopy(target)),
            competences=[VdabCompetence(id=code, name='', code=code) for code in expected],
            custom_fields=[VacancyCustomField.from_api(target)])
        payload = complete.build_duplication_payload()
        payload['vacancy_id'] = new_id
        payload['info_internal'] = source.get('info_internal') or ''
        payload['studies'] = [{'study_id': int(row['study_id'])} for row in new['studies']]
        payload['competences'] = [{'competence_id': int(row['competence_id']), 'score': row['score']} for row in new['competences']]
        if await client.get_vacancy_detail(new_id) != new:
            raise RecoveryReview('Replacement changed concurrently')
        response = await client.add_vacancy(payload)
        if not response.success or str(response.data.get('vacancy_id')) != new_id:
            raise RuntimeError('Existing replacement update not confirmed')
        updated = await client.get_vacancy_detail(new_id)
        changes = {key for key in set(target) | set(updated['detail']) if target.get(key) != updated['detail'].get(key)}
        if changes - {'hash', 'ts_changed', 'user_changed', 'user_changed_name', 'info_internal'}:
            raise RuntimeError(f'Unexpected replacement field change: {sorted(changes)}')
        if competence_codes(updated) != expected:
            raise RuntimeError('Competence transfer not confirmed')
        new = updated
    # Bright can briefly return an incomplete channel list immediately after an update.
    if any(len([row for row in new.get('multiposting', []) if str(row.get('uid')) == str(channel)]) != 1 for channel in [1, 3]):
        new = await client.get_vacancy_detail(new_id)
    for channel in [1, 3]:
        published(new, channel)  # Validate the replacement before touching the source.
    # A closed source cannot be unposted in Bright. Briefly reopen only this known source
    # when its VDAB flag is still set, then unpost and restore its closed state.
    if published(old, 3):
        if str(source.get('is_closed')) == '1':
            response = await client.open_vacancy(old_id)
            if not response.success:
                raise RuntimeError('Source reopening for VDAB removal failed')
        response = await client.delete_multiposting_vacancy(old_id, 3)
        if not response.success:
            await client.close_vacancy(old_id, 3, 'Herstel mislukte vernieuwing')
            raise RuntimeError(f'Source VDAB removal failed: {str(response.data)[:350]}')
    response = await client.close_vacancy(old_id, 3, 'Herstel mislukte vernieuwing')
    if not response.success:
        raise RuntimeError('Source closing not confirmed')
    new = await client.get_vacancy_detail(new_id)
    for channel in [1, 3]:
        if published(new, channel):
            continue
        response = await client.multipost_vacancy(new_id, channel)
        if not response.success:
            message = str(response.data)
            if channel == 3 and isinstance(response.data, dict) and response.data.get('status') == 'success' and any(word in message.lower() for word in ['verplicht', 'is required', 'ongeldig', 'niet geldig']):
                raise RecoveryReview(f'VDAB content validation: {message[:550]}')
            raise RuntimeError(f'Channel {channel} publication failed: {message[:350]}')
    final_old = await client.get_vacancy_detail(old_id)
    final_new = await client.get_vacancy_detail(new_id)
    if str(final_old['detail']['is_closed']) != '1' or published(final_old, 3):
        raise RuntimeError('Final source state not confirmed')
    if not all(published(final_new, channel) for channel in [1, 3]) or competence_codes(final_new) != expected:
        raise RuntimeError('Final publication state not confirmed')
    return {'old_id': old_id, 'new_id': new_id, 'status': 'completed'}


async def recover_run(client: BrightStaffingClient, manifest: dict, backup: Path, workers: int = 1, emit=print) -> dict:
    if client._web_base_url != manifest.get('origin'):
        raise ValueError('Recovery manifest belongs to a different Bright host')
    pairs = manifest['pairs']
    old_ids = [str(pair['old_id']) for pair in pairs]
    new_ids = [str(pair['new_id']) for pair in pairs]
    if (len(set(old_ids)) != len(pairs) or len(set(new_ids)) != len(pairs)
            or set(old_ids) & set(new_ids) or any(not value.isdigit() for value in old_ids + new_ids)):
        raise ValueError('Recovery manifest has ambiguous vacancy identities')
    queue = asyncio.Queue()
    for pair in pairs:
        queue.put_nowait(pair)
    stopped = asyncio.Event()
    counts = {'total': len(pairs), 'completed': 0, 'review': 0, 'failed': 0}
    backup.mkdir(parents=True, exist_ok=True)

    async def worker():
        while not stopped.is_set():
            try:
                pair = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            old_id, new_id = str(pair['old_id']), str(pair['new_id'])
            try:
                event = await repair_pair(client, old_id, new_id, backup)
                counts['completed'] += 1
            except RecoveryReview as exc:
                counts['review'] += 1
                event = {'old_id': old_id, 'new_id': new_id, 'status': 'review', 'error': str(exc)}
            except Exception as exc:
                counts['failed'] += 1
                stopped.set()
                event = {'old_id': old_id, 'new_id': new_id, 'status': 'failed', 'error': str(exc)[:600]}
            with (backup / 'events.jsonl').open('a') as handle:
                handle.write(json.dumps(event) + '\n')
            emit(json.dumps({'event': 'recovery_pair', **event, 'counts': dict(counts)}))
            queue.task_done()
    await asyncio.gather(*(worker() for _ in range(workers)))
    return counts

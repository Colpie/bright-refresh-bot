"""Complete publication of an explicitly confirmed existing refresh pair."""
from ..api.client import BrightStaffingClient


async def recover_publication(client: BrightStaffingClient, original_id: str, new_id: str,
                              channels: list[int]) -> dict:
    if not original_id.isdigit() or not new_id.isdigit() or original_id == new_id:
        raise ValueError("Use two different, explicit Bright IDs")
    old = await client.get_vacancy_detail(original_id)
    new = await client.get_vacancy_detail(new_id)
    source, target = old['detail'], new['detail']
    if str(source.get('is_closed')) != '1' or str(target.get('is_closed')) != '0':
        raise RuntimeError("Recovery requires a closed original and an open existing replacement")
    for field in ['function', 'enterprise_id', 'info_internal']:
        if field not in source or field not in target or source[field] != target[field]:
            raise RuntimeError(f"Refresh pair does not match on {field}; nothing published")
    if not channels or any(channel not in [1, 3] for channel in channels):
        raise ValueError("Recovery supports the configured Website and VDAB channels")
    outcome = {'original_id': original_id, 'new_id': new_id, 'channels': []}
    for channel in channels:
        matches = [row for row in new.get('multiposting', []) if str(row.get('uid')) == str(channel)]
        if len(matches) != 1:
            raise RuntimeError(f"Channel {channel} is not uniquely confirmed; nothing sent to that channel")
        if str(matches[0].get('is_published')) == '1':
            outcome['channels'].append({'channel': channel, 'status': 'already_published'})
            continue
        response = await client.multipost_vacancy(new_id, channel)
        if not response.success:
            raise RuntimeError(f"Existing vacancy {new_id}, channel {channel}: {str(response.data)[:700]}")
        new = await client.get_vacancy_detail(new_id)
        confirmed = [row for row in new.get('multiposting', [])
                     if str(row.get('uid')) == str(channel) and str(row.get('is_published')) == '1']
        if len(confirmed) != 1:
            raise RuntimeError(f"Channel {channel}: publication not confirmed; inspect Bright before repeating")
        outcome['channels'].append({'channel': channel, 'status': 'published'})
    return outcome

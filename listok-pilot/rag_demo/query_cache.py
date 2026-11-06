import re
from .config import ROOT, canonical_hash, read_json, relative, write_new_json

CACHE = ROOT / '.query_cache'
CACHE_VERSION = 1


def scope(question, top_k, manifest, policy, profile):
    return {'question': question, 'top_k': top_k,
            'index_id': manifest['index_id'], 'policy': policy,
            'profile': dict(profile),
            'model_files_sha256': manifest['fingerprint']['model_files_sha256']}


def directory():
    expected = (ROOT / '.query_cache').absolute()
    if CACHE.resolve() != expected:
        raise ValueError('Query cache must remain inside the project')
    return CACHE


def lookup(key, current_scope):
    path = directory() / (key + '.json')
    if not path.is_file():
        return None
    record = read_json(path)
    keys = {'cache_version', 'key', 'scope', 'created_at', 'origin_query_id',
            'payload', 'payload_sha256'}
    if not isinstance(record, dict) or set(record) != keys:
        raise ValueError('Invalid saved search structure; clear query cache')
    if (record['cache_version'] != CACHE_VERSION or record['key'] != key
            or record['scope'] != current_scope or canonical_hash(record['scope']) != key):
        raise ValueError('Saved search settings do not match the current request')
    payload = record['payload']
    if (not isinstance(payload, dict)
            or set(payload) != {'hits', 'context_state', 'filtering'}
            or record['payload_sha256'] != canonical_hash(payload)):
        raise ValueError('Saved search payload has changed; clear query cache')
    if (not isinstance(record['origin_query_id'], str) or not record['origin_query_id']
            or not isinstance(record['created_at'], str) or not record['created_at']):
        raise ValueError('Saved search provenance is incomplete')
    return record


def save(key, current_scope, payload, query_id, created_at):
    path = directory() / (key + '.json')
    record = {'cache_version': CACHE_VERSION, 'key': key, 'scope': current_scope,
              'created_at': created_at, 'origin_query_id': query_id,
              'payload': payload, 'payload_sha256': canonical_hash(payload)}
    write_new_json(path, record)
    return record


def status():
    path = directory()
    entries = [item for item in path.glob('*.json')
               if re.fullmatch(r'[0-9a-f]{64}\.json', item.name)]
    return {'status': 'query_cache', 'path': relative(path),
            'entry_count': len(entries), 'default_enabled': True}


def clear():
    path = directory()
    deleted = 0
    for item in path.glob('*.json'):
        if re.fullmatch(r'[0-9a-f]{64}\.json', item.name):
            if item.resolve().parent != path.resolve():
                raise ValueError('Cache entry points outside the query cache')
            item.unlink()
            deleted += 1
    return {'status': 'query_cache_cleared', 'path': relative(path),
            'deleted_count': deleted, 'evidence_preserved': True}

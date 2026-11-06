import math
import sys
from pathlib import Path
from .config import ROOT, EVIDENCE, PROFILE, read_json, write_json, write_new_json, relative, sha256_bytes
from .storage import validate_index, context_from_hits, identifier, now, update_passport
from .policy import allowed_access, query_filter, source_allowed, snapshot, within_threshold

RETRIEVAL_KEYS = {'status', 'query_id', 'index_id', 'question', 'top_k', 'hits',
                  'context', 'context_chunk_ids', 'retrieval_trace_path',
                  'role', 'policy', 'context_state', 'filtering'}
RETRIEVAL_KEYS.add('search_execution')
HIT_KEYS = {'rank', 'chunk_id', 'text', 'metadata', 'distance'}
METADATA_KEYS = {'document_id', 'title', 'source_path', 'section', 'version', 'updated',
                 'owner', 'line_start', 'line_end', 'document_sha256', 'chunk_sha256',
                 'token_count', 'access', 'source_status'}

def exact_keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(label + ': invalid structure or unexpected fields')

def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ': nonempty string required')

def check_retrieval(retrieval, manifest, collection):
    exact_keys(retrieval, RETRIEVAL_KEYS, 'retrieval')
    allowed = allowed_access(retrieval['role'])
    if retrieval['policy'] != snapshot():
        raise ValueError('Retrieval policy differs from active policy; run a new retrieval')
    if retrieval['status'] != 'retrieval_only':
        raise ValueError('retrieval status must be retrieval_only')
    if retrieval['index_id'] != manifest['index_id']:
        raise ValueError('Historical retrieval index_id differs from current manifest; run a new retrieval')
    nonempty(retrieval['query_id'], 'query_id')
    nonempty(retrieval['question'], 'question')
    if type(retrieval['top_k']) is not int or retrieval['top_k'] <= 0:
        raise ValueError('retrieval top_k must be a positive integer')
    execution = retrieval['search_execution']
    execution_keys = {'mode', 'cache_enabled', 'cache_key', 'cache_path',
                      'origin_query_id', 'saved_at', 'search_elapsed_ms'}
    exact_keys(execution, execution_keys, 'search execution')
    if execution['mode'] not in ('fresh_search', 'cached_results'):
        raise ValueError('Unknown search execution mode')
    if type(execution['cache_enabled']) is not bool:
        raise ValueError('cache_enabled must be a boolean')
    if (type(execution['search_elapsed_ms']) not in (float, int)
            or not math.isfinite(execution['search_elapsed_ms']) or execution['search_elapsed_ms'] < 0):
        raise ValueError('Search elapsed time must be finite and nonnegative')
    if execution['mode'] == 'cached_results' and not execution['cache_enabled']:
        raise ValueError('Saved results require an enabled query cache')
    nonempty(execution['origin_query_id'], 'origin_query_id')
    if execution['mode'] == 'fresh_search' and execution['origin_query_id'] != retrieval['query_id']:
        raise ValueError('Fresh search origin_query_id differs from query_id')
    if execution['mode'] == 'cached_results' and execution['origin_query_id'] == retrieval['query_id']:
        raise ValueError('Repeated search must preserve its original query_id separately')
    if execution['cache_enabled']:
        from .query_cache import scope, CACHE
        from .config import canonical_hash
        expected_key = canonical_hash(scope(retrieval['question'], retrieval['top_k'], manifest,
                                            retrieval['policy'], PROFILE))
        if (execution['cache_key'] != expected_key
                or execution['cache_path'] != relative(CACHE / (expected_key + '.json'))):
            raise ValueError('Query cache key or path differs from the saved request')
        nonempty(execution['saved_at'], 'saved_at')
    elif any(execution[field] is not None for field in ('cache_key', 'cache_path', 'saved_at')):
        raise ValueError('Disabled query cache must have empty cache metadata')
    if not isinstance(retrieval['hits'], list) or len(retrieval['hits']) > retrieval['top_k']:
        raise ValueError('retrieval hits must be an array no larger than top_k')
    state = retrieval['context_state']
    if state not in ('available', 'empty', 'forbidden'):
        raise ValueError('Unknown context_state')
    if (state == 'available') != bool(retrieval['hits']):
        raise ValueError('context_state and hit count mismatch')
    filtering = retrieval['filtering']
    counts = {'authorized_candidates', 'distance_rejected', 'context_withheld', 'kept'}
    exact_keys(filtering, counts | {'authorization_blocked'}, 'filtering')
    if any(type(filtering[key]) is not int or filtering[key] < 0 for key in counts):
        raise ValueError('filtering counts must be nonnegative integers')
    if type(filtering['authorization_blocked']) is not bool or filtering['authorization_blocked'] != (state == 'forbidden'):
        raise ValueError('authorization diagnostic and context_state mismatch')
    if filtering['kept'] != len(retrieval['hits']) or filtering['authorized_candidates'] != sum(filtering[key] for key in ('distance_rejected', 'context_withheld', 'kept')):
        raise ValueError('filtering count mismatch')
    if state != 'forbidden' and filtering['context_withheld']:
        raise ValueError('only forbidden context may withhold authorized candidates')
    allowed_count = sum(item['metadata']['access'] in allowed and source_allowed(item['metadata'], retrieval['policy'])
                        for item in manifest['chunks'].values())
    if filtering['authorized_candidates'] != min(retrieval['top_k'], allowed_count):
        raise ValueError('authorized candidate count differs from current index')
    seen = set()
    for rank, hit in enumerate(retrieval['hits'], start=1):
        exact_keys(hit, HIT_KEYS, 'hit')
        exact_keys(hit['metadata'], METADATA_KEYS, 'hit metadata')
        if hit['metadata']['access'] not in allowed:
            raise ValueError('Hit is inaccessible for the retrieval role')
        if not source_allowed(hit['metadata'], retrieval['policy']):
            raise ValueError('Hit is superseded under the retrieval policy')
        if type(hit['rank']) is not int or hit['rank'] != rank:
            raise ValueError('hit rank mismatch')
        nonempty(hit['chunk_id'], 'chunk_id')
        nonempty(hit['text'], 'hit text')
        if hit['chunk_id'] in seen or hit['chunk_id'] not in manifest['chunks']:
            raise ValueError('unknown or duplicate hit chunk_id')
        seen.add(hit['chunk_id'])
        if type(hit['distance']) not in (float, int) or not math.isfinite(hit['distance']):
            raise ValueError('hit distance must be finite')
        if not within_threshold(hit['distance'], retrieval['policy']):
            raise ValueError('Hit exceeds the active policy distance threshold')
        expected = manifest['chunks'][hit['chunk_id']]
        if expected['metadata'] != hit['metadata'] or expected['text_sha256'] != sha256_bytes(hit['text'].encode('utf-8')):
            raise ValueError('retrieval hit text/metadata differ from manifest')
        stored = collection.get(ids=[hit['chunk_id']], where=query_filter(retrieval['role'], retrieval['policy']),
                                include=['documents', 'metadatas'])
        if stored['ids'] != [hit['chunk_id']] or stored['documents'][0] != hit['text'] or stored['metadatas'][0] != hit['metadata']:
            raise ValueError('retrieval hit differs from collection')
    if retrieval['context_chunk_ids'] != [h['chunk_id'] for h in retrieval['hits']]:
        raise ValueError('context_chunk_ids mismatch')
    if retrieval['context'] != context_from_hits(retrieval['hits']):
        raise ValueError('context differs from hits')
    nonempty(retrieval['retrieval_trace_path'], 'retrieval_trace_path')
    trace_path = (ROOT / retrieval['retrieval_trace_path']).resolve()
    if not trace_path.is_relative_to(EVIDENCE.resolve()) or not trace_path.is_file():
        raise ValueError('retrieval trace missing or outside evidence')
    trace = read_json(trace_path)
    if trace.get('retrieval') != retrieval:
        raise ValueError('retrieval differs from original saved trace')
    if trace.get('profile') != PROFILE or trace.get('policy') != retrieval['policy'] or trace.get('role') != retrieval['role']:
        raise ValueError('retrieval trace profile/policy/role mismatch')

def check_answer(answer, retrieval):
    exact_keys(answer, {'answer', 'citations', 'decision'}, 'answer JSON')
    nonempty(answer['answer'], 'answer')
    policy = retrieval['policy']
    decision = answer['decision']
    state = retrieval['context_state']
    if decision not in policy['parameters']['decisions']:
        raise ValueError('decision is not permitted by the retrieval policy')
    if not isinstance(answer['citations'], list):
        raise ValueError('citations must be an array')
    if answer['decision'] == 'answer' and not answer['citations']:
        raise ValueError('decision answer requires at least one citation')
    if answer['decision'] == 'insufficient_context' and answer['citations']:
        raise ValueError('insufficient_context requires empty citations')
    if answer['decision'] == 'refuse' and answer['citations']:
        raise ValueError('refuse requires empty citations')
    if state in ('empty', 'forbidden'):
        expected = 'insufficient_context' if policy['version'] == 'v1' else 'refuse'
        if decision != expected or answer['citations']:
            raise ValueError(state + ' context requires ' + expected + ' with empty citations')
    if decision in ('clarify', 'escalate') and state != 'available':
        raise ValueError('clarify/escalate require available candidate context')
    hits = {h['chunk_id']: h for h in retrieval['hits']}
    enriched, mapping = [], []
    for ordinal, citation in enumerate(answer['citations'], start=1):
        exact_keys(citation, {'document_id', 'chunk_id', 'quote'}, 'citation')
        for key in ('document_id', 'chunk_id', 'quote'):
            nonempty(citation[key], 'citation ' + key)
        if citation['chunk_id'] not in hits:
            raise ValueError('Unknown citation chunk_id in current hits: ' + citation['chunk_id'])
        hit = hits[citation['chunk_id']]
        if citation['document_id'] != hit['metadata']['document_id']:
            raise ValueError('Citation document_id/chunk_id pair mismatch: ' + citation['chunk_id'])
        if citation['quote'] not in hit['text']:
            raise ValueError('Citation quote absent from specified hit: ' + citation['chunk_id'])
        fields = {key: hit['metadata'][key] for key in ('title', 'source_path', 'section', 'line_start', 'line_end')}
        enriched.append({**citation, **fields})
        mapping.append({'citation_number': ordinal, 'citation': citation,
                        'hit_rank': hit['rank'], 'chunk_id': hit['chunk_id'],
                        'document_id': hit['metadata']['document_id'], **fields,
                        'document_sha256': hit['metadata']['document_sha256'],
                        'chunk_sha256': hit['metadata']['chunk_sha256']})
    return enriched, mapping

def finalize(retrieval_path, answer_path):
    retrieval_file = ROOT / retrieval_path
    answer_file = ROOT / answer_path
    retrieval = read_json(retrieval_file)
    answer = read_json(answer_file)
    exact_keys(retrieval, RETRIEVAL_KEYS, 'retrieval')
    exact_keys(answer, {'answer', 'citations', 'decision'}, 'answer JSON')
    allowed_access(retrieval['role'])
    if retrieval['policy'] != snapshot():
        raise ValueError('Retrieval policy differs from active policy; run a new retrieval')
    manifest, collection = validate_index(retrieval['role'], retrieval['policy'])
    check_retrieval(retrieval, manifest, collection)
    citations, mapping = check_answer(answer, retrieval)
    # No successful artifacts are written until every check above has passed.
    capture_id = identifier('capture')
    paths = {kind: f'evidence/{kind}-{capture_id}.json' for kind in ('result', 'trace', 'citation-map')}
    result = {'status': 'finalized', 'capture_id': capture_id, 'query_id': retrieval['query_id'],
              'index_id': retrieval['index_id'], 'question': retrieval['question'],
              'role': retrieval['role'], 'policy': retrieval['policy'], 'context_state': retrieval['context_state'],
              'answer': answer['answer'], 'citations': citations, 'decision': answer['decision'],
              'artifact_paths': paths}
    validation = {'structure': True, 'index_freshness': True, 'citation_provenance': True,
                  'policy_freshness': True, 'access_boundaries': True, 'behavior_guards': True,
                  'semantic_support': 'requires separate human or current-chat review'}
    trace = {'capture_id': capture_id, 'created_at': now(), 'question': retrieval['question'],
             'index_id': retrieval['index_id'], 'retrieval': retrieval, 'context': retrieval['context'],
             'role': retrieval['role'], 'policy': retrieval['policy'],
             'raw_answer': answer, 'raw_answer_path': relative(answer_file),
             'retrieval_path': relative(retrieval_file), 'validation': validation, 'result': result}
    write_new_json(ROOT / paths['result'], result)
    write_new_json(ROOT / paths['trace'], trace)
    write_new_json(ROOT / paths['citation-map'], {'capture_id': capture_id, 'index_id': retrieval['index_id'],
                                                'role': retrieval['role'], 'policy': retrieval['policy'],
                                                'mappings': mapping})
    update_passport('answer', {'policy_path': 'rag-policy.md',
                              'raw_answer_path': relative(answer_file)})
    update_passport('verification', {'capture_id': capture_id, 'index_id': retrieval['index_id'],
                                     'artifact_paths': paths, 'validation': validation})
    passport_path = EVIDENCE / 'technical-passport.json'
    passport = read_json(passport_path)
    passport.setdefault('captures', []).append({'capture_id': capture_id, 'index_id': retrieval['index_id'],
                                                'raw_answer_path': relative(answer_file), 'artifact_paths': paths})
    write_json(passport_path, passport)
    for path in paths.values():
        print('Saved ' + path, file=sys.stderr)
    return result

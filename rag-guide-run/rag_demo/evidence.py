import math
import sys
from pathlib import Path
from .config import ROOT, EVIDENCE, read_json, write_json, relative, sha256_bytes
from .storage import validate_index, context_from_hits, identifier, now, update_passport

RETRIEVAL_KEYS = {'status', 'query_id', 'index_id', 'question', 'top_k', 'hits',
                  'context', 'context_chunk_ids', 'retrieval_trace_path'}
HIT_KEYS = {'rank', 'chunk_id', 'text', 'metadata', 'distance'}
METADATA_KEYS = {'document_id', 'title', 'source_path', 'section', 'version', 'updated',
                 'owner', 'line_start', 'line_end', 'document_sha256', 'chunk_sha256', 'token_count'}

def exact_keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(label + ': invalid structure or unexpected fields')

def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ': nonempty string required')

def check_retrieval(retrieval, manifest, collection):
    exact_keys(retrieval, RETRIEVAL_KEYS, 'retrieval')
    if retrieval['status'] != 'retrieval_only':
        raise ValueError('retrieval status must be retrieval_only')
    if retrieval['index_id'] != manifest['index_id']:
        raise ValueError('Historical retrieval index_id differs from current manifest; run a new retrieval')
    nonempty(retrieval['query_id'], 'query_id')
    nonempty(retrieval['question'], 'question')
    if type(retrieval['top_k']) is not int or retrieval['top_k'] <= 0:
        raise ValueError('retrieval top_k must be a positive integer')
    if not isinstance(retrieval['hits'], list) or not retrieval['hits']:
        raise ValueError('retrieval hits must be a nonempty array')
    if len(retrieval['hits']) != min(retrieval['top_k'], manifest['chunk_count']):
        raise ValueError('retrieval hit count does not match top_k/index')
    seen = set()
    for rank, hit in enumerate(retrieval['hits'], start=1):
        exact_keys(hit, HIT_KEYS, 'hit')
        exact_keys(hit['metadata'], METADATA_KEYS, 'hit metadata')
        if type(hit['rank']) is not int or hit['rank'] != rank:
            raise ValueError('hit rank mismatch')
        nonempty(hit['chunk_id'], 'chunk_id')
        nonempty(hit['text'], 'hit text')
        if hit['chunk_id'] in seen or hit['chunk_id'] not in manifest['chunks']:
            raise ValueError('unknown or duplicate hit chunk_id')
        seen.add(hit['chunk_id'])
        if type(hit['distance']) not in (float, int) or not math.isfinite(hit['distance']):
            raise ValueError('hit distance must be finite')
        expected = manifest['chunks'][hit['chunk_id']]
        if expected['metadata'] != hit['metadata'] or expected['text_sha256'] != sha256_bytes(hit['text'].encode('utf-8')):
            raise ValueError('retrieval hit text/metadata differ from manifest')
        stored = collection.get(ids=[hit['chunk_id']], include=['documents', 'metadatas'])
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

def check_answer(answer, retrieval):
    exact_keys(answer, {'answer', 'citations', 'decision'}, 'answer JSON')
    nonempty(answer['answer'], 'answer')
    if answer['decision'] not in ('answer', 'insufficient_context'):
        raise ValueError('decision must be answer or insufficient_context')
    if not isinstance(answer['citations'], list):
        raise ValueError('citations must be an array')
    if answer['decision'] == 'answer' and not answer['citations']:
        raise ValueError('decision answer requires at least one citation')
    if answer['decision'] == 'insufficient_context' and answer['citations']:
        raise ValueError('insufficient_context requires empty citations')
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
    manifest, collection = validate_index()
    check_retrieval(retrieval, manifest, collection)
    citations, mapping = check_answer(answer, retrieval)
    # No successful artifacts are written until every check above has passed.
    capture_id = identifier('capture')
    paths = {kind: f'evidence/{kind}-{capture_id}.json' for kind in ('result', 'trace', 'citation-map')}
    result = {'status': 'finalized', 'capture_id': capture_id, 'query_id': retrieval['query_id'],
              'index_id': retrieval['index_id'], 'question': retrieval['question'],
              'answer': answer['answer'], 'citations': citations, 'decision': answer['decision'],
              'artifact_paths': paths}
    validation = {'structure': True, 'index_freshness': True, 'citation_provenance': True,
                  'semantic_support': 'requires separate human or current-chat review'}
    trace = {'capture_id': capture_id, 'created_at': now(), 'question': retrieval['question'],
             'index_id': retrieval['index_id'], 'retrieval': retrieval, 'context': retrieval['context'],
             'raw_answer': answer, 'raw_answer_path': relative(answer_file),
             'retrieval_path': relative(retrieval_file), 'validation': validation, 'result': result}
    write_json(ROOT / paths['result'], result)
    write_json(ROOT / paths['trace'], trace)
    write_json(ROOT / paths['citation-map'], {'capture_id': capture_id, 'index_id': retrieval['index_id'],
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

import datetime
import importlib.metadata
import platform
import sys
import time
import uuid
from pathlib import Path
import chromadb
from chromadb.config import Settings
from .config import (ROOT, MODEL_DIR, STORE, EVIDENCE, COLLECTION, PROFILE,
                     canonical_hash, file_sha256, read_json, write_json, relative,
                     sha256_bytes, write_new_json)
from .documents import load_documents, save_chunks
from .model import local_file_hashes, load_local_model, encode
from .policy import (allowed_access, query_filter, source_filter, source_allowed,
                     snapshot, select_candidates)
from . import query_cache

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def identifier(kind):
    return kind + '-' + uuid.uuid4().hex

def client():
    return chromadb.PersistentClient(path=str(STORE), settings=Settings(anonymized_telemetry=False))

def stamp():
    docs, excluded = load_documents()
    hashes = {doc.metadata['id']: {'path': doc.source_path, 'sha256': doc.document_sha256,
                                  'metadata': {'source_status': doc.metadata['source_status']}}
              for doc in docs}
    return {'inventory_sha256': file_sha256(ROOT / 'inventory.csv'),
            'documents': hashes, 'corpus_sha256': canonical_hash(hashes),
            'profile': dict(PROFILE), 'model_files_sha256': local_file_hashes()}, excluded

def environment():
    packages = {dist.metadata['Name']: dist.version for dist in importlib.metadata.distributions()
                if dist.metadata.get('Name')}
    # Keep the venv path without resolving macOS interpreter symlinks.
    interpreter_path = Path(sys.executable).absolute()
    try:
        interpreter = interpreter_path.relative_to(ROOT).as_posix()
    except ValueError:
        interpreter = interpreter_path.name
    return {'os': platform.system(), 'os_version': platform.version(),
            'architecture': platform.machine(), 'python_version': sys.version,
            'interpreter': interpreter,
            'dependencies': dict(sorted(packages.items(), key=lambda item: item[0].lower())),
            'requirements_file': 'requirements-windows.txt' if platform.system() == 'Windows'
                                 else 'requirements-macos.txt'}

def update_passport(section, data):
    path = EVIDENCE / 'technical-passport.json'
    passport = read_json(path) if path.exists() else {}
    passport[section] = data
    passport['updated_at'] = now()
    write_json(path, passport)

def index():
    model = load_local_model()
    docs, chunks, excluded = save_chunks(model.tokenizer)
    fingerprint, _ = stamp()
    source = {'model_id': PROFILE['model_id'], 'local_path': PROFILE['model_path'],
              'dimension': 768, 'device': 'cpu', 'files_sha256': fingerprint['model_files_sha256']}
    write_json(MODEL_DIR / 'model-source.json', source)
    vectors = encode(model, [chunk.embedding_text for chunk in chunks], 'passage')
    index_id = identifier('index')
    db = client()
    if COLLECTION in [col.name for col in db.list_collections()]:
        db.delete_collection(COLLECTION)
    collection = db.create_collection(
        name=COLLECTION, embedding_function=None,
        configuration={'hnsw': {'space': 'cosine'}}, metadata={'index_id': index_id})
    collection.upsert(ids=[c.chunk_id for c in chunks], documents=[c.text for c in chunks],
                      metadatas=[c.metadata for c in chunks], embeddings=vectors.tolist())
    if collection.count() != len(chunks):
        raise ValueError('stored chunk count mismatch')
    chunk_manifest = {c.chunk_id: {'text_sha256': c.metadata['chunk_sha256'],
                                 'metadata': c.metadata} for c in chunks}
    manifest = {'index_id': index_id, 'created_at': now(), 'fingerprint': fingerprint,
                'document_count': len(docs), 'chunk_count': len(chunks),
                'excluded': excluded, 'chunks': chunk_manifest}
    write_json(STORE / 'manifest.json', manifest)
    passport = {'environment': environment(), 'model': source, 'profile': dict(PROFILE),
                'index': manifest, 'os_checks': {'Windows': platform.system() == 'Windows',
                                               'macOS': platform.system() == 'Darwin'},
                'updated_at': now()}
    # Older captures remain immutable historical files; passport reflects this index.
    write_json(EVIDENCE / 'technical-passport.json', passport)
    return {'status': 'indexed', 'index_id': index_id, 'document_count': len(docs),
            'chunk_count': len(chunks), 'dimension': int(vectors.shape[1]),
            'device': model.device.type, 'collection': COLLECTION, 'metric': 'cosine',
            'manifest_path': relative(STORE / 'manifest.json')}

def validate_index(role='manager', policy=None):
    allowed = allowed_access(role)
    policy = policy or snapshot()
    if not (STORE / 'manifest.json').is_file():
        raise ValueError('No saved index; run index first')
    manifest = read_json(STORE / 'manifest.json')
    try:
        inventory_hash = file_sha256(ROOT / 'inventory.csv')
        if inventory_hash != manifest['fingerprint']['inventory_sha256']:
            raise ValueError('inventory changed')
        hashes = {}
        for document_id, item in manifest['fingerprint']['documents'].items():
            path = (ROOT / item['path']).resolve()
            if not path.is_relative_to((ROOT / 'docs').resolve()):
                raise ValueError('manifest document outside docs')
            metadata = item.get('metadata')
            if (not isinstance(metadata, dict) or set(metadata) != {'source_status'}
                    or metadata['source_status'] not in ('current', 'superseded')):
                raise ValueError('manifest source_status metadata is missing or invalid; run index')
            hashes[document_id] = {'path': item['path'], 'sha256': file_sha256(path),
                                   'metadata': dict(metadata)}
        current = {'inventory_sha256': inventory_hash, 'documents': hashes,
                   'corpus_sha256': canonical_hash(hashes), 'profile': dict(PROFILE),
                   'model_files_sha256': local_file_hashes()}
    except (ValueError, OSError) as exc:
        raise ValueError('Stale index: current corpus/model cannot be validated; run index. ' + str(exc)) from exc
    if current != manifest['fingerprint']:
        changed = [key for key in current if current[key] != manifest['fingerprint'].get(key)]
        raise ValueError('Stale index: changed ' + ', '.join(changed) + '; run index')
    db = client()
    if COLLECTION not in [col.name for col in db.list_collections()]:
        raise ValueError('Saved collection is missing; run index')
    collection = db.get_collection(COLLECTION, embedding_function=None)
    if collection.metadata.get('index_id') != manifest['index_id']:
        raise ValueError('Collection and manifest index_id mismatch; run index')
    if collection.count() != manifest['chunk_count']:
        raise ValueError('Collection count mismatch; run index')
    # Validate all IDs/metadata, but read text only through role and source filters.
    stored = collection.get(include=['metadatas'])
    if set(stored['ids']) != set(manifest['chunks']):
        raise ValueError('Collection IDs mismatch; run index')
    for cid, metadata in zip(stored['ids'], stored['metadatas']):
        expected = manifest['chunks'][cid]
        if metadata != expected['metadata'] or metadata.get('access') not in ('public', 'staff', 'manager'):
            raise ValueError('Collection metadata/access mismatch; run index')
        document = manifest['fingerprint']['documents'].get(metadata.get('document_id'))
        if (not document or metadata.get('source_status') != document['metadata']['source_status']
                or metadata.get('source_status') not in ('current', 'superseded')):
            raise ValueError('Collection source_status/fingerprint mismatch; run index')
    accessible = collection.get(where=query_filter(role, policy), include=['documents', 'metadatas'])
    expected_ids = {cid for cid, item in manifest['chunks'].items()
                    if item['metadata']['access'] in allowed and source_allowed(item['metadata'], policy)}
    if set(accessible['ids']) != expected_ids:
        raise ValueError('Authorized collection IDs mismatch; run index')
    for cid, text, metadata in zip(accessible['ids'], accessible['documents'], accessible['metadatas']):
        expected = manifest['chunks'][cid]
        if sha256_bytes(text.encode('utf-8')) != expected['text_sha256'] or metadata != expected['metadata']:
            raise ValueError('Authorized collection text/metadata mismatch; run index')
    return manifest, collection

def context_from_hits(hits):
    return '\n\n'.join(f"[{h['chunk_id']} | {h['metadata']['document_id']} | {h['metadata']['section']}]\n{h['text']}"
                       for h in hits)

def retrieve(question, top_k=8, output=None, role='customer', use_cache=True):
    allowed = allowed_access(role)
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question must be nonempty')
    if type(top_k) is not int or top_k <= 0:
        raise ValueError('top_k must be a positive integer')
    if type(use_cache) is not bool:
        raise ValueError('use_cache must be a boolean')
    policy = snapshot()
    destination = ROOT / output if output else None
    if destination is not None:
        destination = destination.resolve()
        if not destination.is_relative_to(EVIDENCE.resolve()):
            raise ValueError('Retrieval output must be inside evidence')
        if destination.exists():
            raise ValueError('Retrieval output already exists; choose a new filename')
    manifest, collection = validate_index(role, policy)
    query_id = identifier('query')
    cache_scope = query_cache.scope(question, top_k, manifest, policy, PROFILE)
    cache_key = canonical_hash(cache_scope)
    started = time.perf_counter()
    cached = query_cache.lookup(cache_key, cache_scope) if use_cache else None
    if cached is not None:
        payload = cached['payload']
        hits, state, filtering = payload['hits'], payload['context_state'], payload['filtering']
    else:
        model = load_local_model()
        vector = encode(model, [question], 'query')
        eligible_count = sum(source_allowed(item['metadata'], policy) for item in manifest['chunks'].values())
        allowed_count = sum(item['metadata']['access'] in allowed and source_allowed(item['metadata'], policy)
                            for item in manifest['chunks'].values())
        results = {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}
        if allowed_count:
            results = collection.query(query_embeddings=vector.tolist(),
                                       n_results=min(top_k, allowed_count), where=query_filter(role, policy),
                                       include=['documents', 'metadatas', 'distances'])
        # The probe diagnoses withheld context without requesting closed document text.
        probe = None
        if allowed_count < eligible_count:
            probe = collection.query(query_embeddings=vector.tolist(), n_results=1,
                                     where=source_filter(policy),
                                     include=['metadatas', 'distances'])
        hits, state, filtering = select_candidates(results, role, policy, probe)
        payload = {'hits': hits, 'context_state': state, 'filtering': filtering}
        if use_cache:
            cached = query_cache.save(cache_key, cache_scope, payload, query_id, now())
    execution = {'mode': 'cached_results' if cached and cached['origin_query_id'] != query_id else 'fresh_search',
                 'cache_enabled': use_cache,
                 'cache_key': cache_key if use_cache else None,
                 'cache_path': relative(query_cache.CACHE / (cache_key + '.json')) if use_cache else None,
                 'origin_query_id': cached['origin_query_id'] if cached else query_id,
                 'saved_at': cached['created_at'] if cached else None,
                 'search_elapsed_ms': round((time.perf_counter() - started) * 1000, 3)}
    trace_path = EVIDENCE / f'retrieval-trace-{query_id}.json'
    retrieval = {'status': 'retrieval_only', 'query_id': query_id,
                 'index_id': manifest['index_id'], 'question': question, 'top_k': top_k,
                 'role': role, 'policy': policy, 'context_state': state, 'filtering': filtering,
                 'search_execution': execution,
                 'hits': hits, 'context': context_from_hits(hits),
                 'context_chunk_ids': [hit['chunk_id'] for hit in hits],
                 'retrieval_trace_path': relative(trace_path)}
    destination = destination or EVIDENCE / f'retrieval-{query_id}.json'
    write_new_json(destination, retrieval)
    write_new_json(trace_path, {'created_at': now(), 'profile': dict(PROFILE),
                              'role': role, 'policy': policy,
                              'retrieval': retrieval, 'output_path': relative(destination)})
    update_passport('retrieval', {'query_id': query_id, 'index_id': manifest['index_id'],
                                 'top_k': top_k, 'output_path': relative(destination),
                                 'role': role, 'policy': policy, 'context_state': state,
                                 'search_execution': execution,
                                 'retrieval_trace_path': relative(trace_path)})
    print('Saved ' + relative(destination), file=sys.stderr)
    return retrieval

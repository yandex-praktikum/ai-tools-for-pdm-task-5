import datetime
import importlib.metadata
import platform
import sys
import uuid
from pathlib import Path
import chromadb
from chromadb.config import Settings
from .config import (ROOT, MODEL_DIR, STORE, EVIDENCE, COLLECTION, PROFILE, RUNTIME,
                     canonical_hash, file_sha256, read_json, write_json, relative,
                     sha256_bytes)
from .documents import load_documents, save_chunks
from .model import local_file_hashes, load_local_model, encode

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def identifier(kind):
    return kind + '-' + uuid.uuid4().hex

def client():
    return chromadb.PersistentClient(path=str(STORE), settings=Settings(anonymized_telemetry=False))

def stamp():
    docs, excluded = load_documents()
    cache_path = STORE / 'source-fingerprints.json'
    cache = read_json(cache_path) if cache_path.is_file() else {}
    hashes = {}
    for doc in docs:
        stat = (ROOT / doc.source_path).stat()
        signature = [stat.st_size, int(stat.st_mtime)]
        entry = cache.get(doc.metadata['id'], {})
        if entry.get('signature') != signature:
            entry = {'signature': signature, 'sha256': doc.document_sha256}
            cache[doc.metadata['id']] = entry
        hashes[doc.metadata['id']] = {'path': doc.source_path, 'sha256': entry['sha256']}
    write_json(cache_path, cache)
    return {'inventory_sha256': file_sha256(ROOT / 'inventory.csv'),
            'documents': hashes, 'corpus_sha256': canonical_hash(hashes),
            'profile': {key: PROFILE[key] for key in ('model_id', 'dimension', 'metric')},
            'model_files_sha256': local_file_hashes()}, excluded

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
    manifest_path = STORE / 'manifest.json'
    saved = read_json(manifest_path) if manifest_path.is_file() else {}
    index_id = saved.get('index_id') or identifier('index')
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

def validate_index():
    if not (STORE / 'manifest.json').is_file():
        raise ValueError('No saved index; run index first')
    manifest = read_json(STORE / 'manifest.json')
    try:
        current, _ = stamp()
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
    stored = collection.get(include=['documents', 'metadatas'])
    if set(stored['ids']) != set(manifest['chunks']):
        raise ValueError('Collection IDs mismatch; run index')
    for cid, text, metadata in zip(stored['ids'], stored['documents'], stored['metadatas']):
        expected = manifest['chunks'][cid]
        if sha256_bytes(text.encode('utf-8')) != expected['text_sha256'] or metadata != expected['metadata']:
            raise ValueError('Collection text/metadata mismatch; run index')
    return manifest, collection

def context_from_hits(hits):
    frames = []
    budget = int(RUNTIME.get('context_chars', 4096))
    used = 0
    for hit in hits:
        frame = f"[{hit['chunk_id']} | {hit['metadata']['document_id']} | {hit['metadata']['section']}]\n{hit['text']}"
        if frames and used + len(frame) + 2 > budget:
            break
        frames.append(frame)
        used += len(frame) + 2
    return '\n\n'.join(frames)

def retrieve(question, top_k=8, output=None):
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question must be nonempty')
    if type(top_k) is not int or top_k <= 0:
        raise ValueError('top_k must be a positive integer')
    manifest, collection = validate_index()
    model = load_local_model()
    vector = encode(model, [question], 'query')
    results = collection.query(query_embeddings=vector.tolist(),
                               n_results=min(top_k, PROFILE['default_top_k'], collection.count()),
                               include=['documents', 'metadatas', 'distances'])
    hits = [{'rank': rank, 'chunk_id': cid, 'text': text, 'metadata': meta,
             'distance': 1.0 - float(distance)}
            for rank, (cid, text, meta, distance) in enumerate(zip(
                results['ids'][0], results['documents'][0], results['metadatas'][0],
                results['distances'][0]), start=1)]
    query_id = identifier('query')
    trace_path = EVIDENCE / f'retrieval-trace-{query_id}.json'
    retrieval = {'status': 'retrieval_only', 'query_id': query_id,
                 'index_id': manifest['index_id'], 'question': question, 'top_k': top_k,
                 'hits': hits, 'context': context_from_hits(hits),
                 'context_chunk_ids': [hit['chunk_id'] for hit in hits],
                 'retrieval_trace_path': relative(trace_path)}
    destination = ROOT / output if output else EVIDENCE / f'retrieval-{query_id}.json'
    write_json(destination, retrieval)
    write_json(trace_path, {'created_at': now(), 'profile': dict(PROFILE),
                            'retrieval': retrieval, 'output_path': relative(destination)})
    update_passport('retrieval', {'query_id': query_id, 'index_id': manifest['index_id'],
                                 'top_k': top_k, 'output_path': relative(destination),
                                 'retrieval_trace_path': relative(trace_path)})
    print('Saved ' + relative(destination), file=sys.stderr)
    return retrieval

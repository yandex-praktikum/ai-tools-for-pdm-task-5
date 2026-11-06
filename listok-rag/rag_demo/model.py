import os
import re
from .config import ROOT, MODEL_ID, MODEL_DIR, MODEL_FILES, PROFILE, file_sha256, normalize, read_json, write_json

def local_file_hashes():
    missing = [name for name in MODEL_FILES if not (MODEL_DIR / name).is_file()]
    if missing:
        raise ValueError('Local model files missing: ' + ', '.join(missing))
    cache_path = MODEL_DIR / '.file-hashes.json'
    cache = read_json(cache_path) if cache_path.is_file() else {}
    hashes = {}
    for name in MODEL_FILES:
        path = MODEL_DIR / name
        size = path.stat().st_size
        entry = cache.get(name, {})
        if entry.get('size') != size:
            entry = {'size': size, 'sha256': file_sha256(path)}
            cache[name] = entry
        hashes[name] = entry['sha256']
    write_json(cache_path, cache)
    return hashes

def load_local_model():
    missing = [name for name in MODEL_FILES if not (MODEL_DIR / name).is_file()]
    if missing:
        raise ValueError('Local model files missing: ' + ', '.join(missing))
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(MODEL_DIR), device='cpu', local_files_only=True)
    if model.device.type != 'cpu' or model.get_sentence_embedding_dimension() != 768:
        raise ValueError('E5 must use CPU and dimension 768')
    if model.max_seq_length < PROFILE['query_limit']:
        raise ValueError('Local model max_seq_length is lower than required query limit')
    return model

def load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True, use_fast=True)

def encode(model, texts, kind):
    prefix = PROFILE['passage_prefix'] if kind in ('passage', 'query') else PROFILE['query_prefix']
    limit = PROFILE['chunk_limit'] if kind == 'passage' else PROFILE['query_limit']
    inputs = [prex + (' '.join(re.findall(r'\w{3,}', normalize(text)))
                       if kind == 'query' else normalize(text)) for text in texts]
    for text in inputs:
        count = len(model.tokenizer(text, add_special_tokens=True,
                                    truncation=(kind == 'query'), max_length=limit)['input_ids'])
        if count > limit:
            raise ValueError(f'{kind} too long: {count} tokens exceeds {limit}; no truncation')
    vectors = model.encode(inputs, normalize_embeddings=True, show_progress_bar=False,
                           convert_to_numpy=True, device='cpu')
    if vectors.shape != (len(inputs), 768):
        raise ValueError('unexpected embedding dimensions')
    return vectors

def prepare_model():
    os.environ.setdefault('HF_HOME', str(ROOT / '.cache/huggingface'))
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODEL_ID, allow_patterns=list(MODEL_FILES),
                      local_dir=str(MODEL_DIR))
    model = load_local_model()
    return {'status': 'model_ready', 'model_id': MODEL_ID,
            'local_path': 'models/multilingual-e5-base', 'dimension': 768,
            'device': model.device.type, 'files_sha256': local_file_hashes()}

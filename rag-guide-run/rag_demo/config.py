from pathlib import Path
import hashlib
import json
import re
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
MODEL_ID = 'intfloat/multilingual-e5-base'
MODEL_DIR = ROOT / 'models' / 'multilingual-e5-base'
STORE = ROOT / '.rag_store'
EVIDENCE = ROOT / 'evidence'
COLLECTION = 'listok-e5-demo'
MODEL_FILES = ('config.json', 'model.safetensors', 'modules.json',
               'sentence_bert_config.json', '1_Pooling/config.json',
               'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
               'sentencepiece.bpe.model', 'README.md')
PROFILE = {
    'model_id': MODEL_ID, 'model_path': 'models/multilingual-e5-base',
    'device': 'cpu', 'dimension': 768, 'normalize_embeddings': True,
    'passage_prefix': 'passage: ', 'query_prefix': 'query: ',
    'unicode_normalization': 'NFC', 'whitespace': 'collapse Unicode whitespace and strip',
    'chunker': 'structural-h2-source-slices-v1', 'chunk_limit': 384, 'overlap': 0,
    'query_limit': 512, 'line_range': '1-based source lines; split chunks retain section range',
    'collection': COLLECTION, 'metric': 'cosine', 'default_top_k': 8,
}

def normalize(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()

def canonical_hash(data):
    return sha256_bytes(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8'))

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(data), encoding='utf-8', newline='\n')

def relative(path):
    resolved = str(Path(path).resolve())
    if resolved.startswith('\\\\?\\'):
        resolved = resolved[4:]
    return Path(resolved).relative_to(ROOT).as_posix()

from dataclasses import dataclass, asdict
import csv
import io
import re
import yaml
from .config import ROOT, PROFILE, file_sha256, sha256_bytes, normalize, write_json

FIELDS = ('id', 'path', 'origin', 'owner', 'version', 'updated',
          'permission', 'sensitivity', 'status', 'reason')

@dataclass
class Document:
    metadata: dict
    source_path: str
    text: str
    document_sha256: str
    body_line_start: int

@dataclass
class Chunk:
    chunk_id: str
    text: str
    embedding_text: str
    metadata: dict

def load_documents():
    raw = (ROOT / 'inventory.csv').read_text(encoding='utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError('inventory.csv: unexpected columns')
    rows = list(reader)
    seen_ids, seen_paths, seen_hashes = set(), set(), set()
    docs, excluded = [], []
    docs_dir = (ROOT / 'docs').resolve()
    for row in rows:
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in FIELDS):
            raise ValueError('inventory.csv: empty metadata')
        if row['id'] in seen_ids:
            raise ValueError('inventory.csv: duplicate ID ' + row['id'])
        seen_ids.add(row['id'])
        if row['status'] not in ('include', 'exclude'):
            raise ValueError('inventory.csv: status must be include/exclude')
        if row['status'] == 'exclude':
            excluded.append({'id': row['id'], 'reason': row['reason']})
            continue
        if row['permission'] != 'allowed' or row['sensitivity'] != 'synthetic':
            raise ValueError('included document must be allowed and synthetic')
        path = (ROOT / row['path']).resolve()
        if not path.is_relative_to(docs_dir) or path.suffix != '.md':
            raise ValueError('included path must be a Markdown file inside docs')
        if path in seen_paths:
            raise ValueError('inventory.csv: duplicate included path')
        seen_paths.add(path)
        text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != '---':
            raise ValueError('frontmatter required: ' + row['path'])
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if closing is None:
            raise ValueError('unclosed frontmatter: ' + row['path'])
        meta = yaml.safe_load(''.join(lines[1:closing]))
        if not isinstance(meta, dict):
            raise ValueError('frontmatter must be a mapping')
        for key in ('id', 'title', 'version', 'updated', 'owner', 'access'):
            if not isinstance(meta.get(key), str) or not meta[key].strip():
                raise ValueError('missing frontmatter ' + key)
        if meta['access'] not in ('public', 'staff', 'manager'):
            raise ValueError('frontmatter access must be public, staff or manager')
        meta.setdefault('source_status', 'current')
        if meta['source_status'] not in ('current', 'superseded'):
            raise ValueError('frontmatter source_status must be current or superseded')
        for key in ('id', 'version', 'updated', 'owner'):
            if meta[key] != row[key]:
                raise ValueError('inventory/frontmatter mismatch: ' + key)
        body = ''.join(lines[closing + 1:])
        body_hash = sha256_bytes(body.encode('utf-8'))
        if body_hash in seen_hashes:
            raise ValueError('duplicate included document body')
        seen_hashes.add(body_hash)
        docs.append(Document(meta, row['path'], body, file_sha256(path), closing + 2))
    if not docs:
        raise ValueError('no included documents')
    return docs, excluded

def sections(document):
    lines = document.text.splitlines(keepends=True)
    starts = [0] + [i for i, line in enumerate(lines) if line.startswith('## ')]
    starts = sorted(set(starts)) + [len(lines)]
    for start, end in zip(starts, starts[1:]):
        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        if start == end:
            continue
        text = ''.join(lines[start:end]).rstrip('\n')
        section = lines[start][3:].strip() if lines[start].startswith('## ') else 'Введение'
        yield section, text, document.body_line_start + start, document.body_line_start + end - 1

def passage_text(title, text):
    return 'passage: ' + normalize(title + '\n' + text)

def token_count(tokenizer, title, text):
    return len(tokenizer(passage_text(title, text), add_special_tokens=True,
                         truncation=False)['input_ids'])

def split_section(tokenizer, title, source):
    remaining = source
    while remaining:
        if token_count(tokenizer, title, remaining) <= PROFILE['chunk_limit']:
            yield remaining
            break
        boundaries = [match.end() for match in re.finditer(r'\S+\s*', remaining)]
        # Source boundaries preserve exact wording, including spaces between parts.
        lo, hi, best = 0, len(boundaries) - 1, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            end = boundaries[mid]
            if token_count(tokenizer, title, remaining[:end]) <= PROFILE['chunk_limit']:
                best = end
                lo = mid + 1
            else:
                hi = mid - 1
        if best == 0:
            # A single exceptionally long token sequence must still remain lossless.
            lo, hi = 1, len(remaining)
            while lo <= hi:
                mid = (lo + hi) // 2
                if token_count(tokenizer, title, remaining[:mid]) <= PROFILE['chunk_limit']:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
        if best == 0:
            raise ValueError('title/prefix leaves no room for chunk text')
        yield remaining[:best]
        remaining = remaining[best:]

def create_chunks(tokenizer):
    docs, excluded = load_documents()
    chunks = []
    for doc in docs:
        ordinal = 0
        for section, source, first, last in sections(doc):
            parts = list(split_section(tokenizer, doc.metadata['title'], source))
            if ''.join(parts) != source:
                raise ValueError('chunker lost source text')
            for part in parts:
                ordinal += 1
                count = token_count(tokenizer, doc.metadata['title'], part)
                metadata = {
                    'document_id': doc.metadata['id'], 'title': doc.metadata['title'],
                    'source_path': doc.source_path, 'section': section,
                    'version': doc.metadata['version'], 'updated': doc.metadata['updated'],
                    'owner': doc.metadata['owner'], 'line_start': first, 'line_end': last,
                    'access': doc.metadata['access'],
                    'source_status': doc.metadata['source_status'],
                    'document_sha256': doc.document_sha256,
                    'chunk_sha256': sha256_bytes(part.encode('utf-8')), 'token_count': count,
                }
                chunks.append(Chunk(f"{doc.metadata['id']}::chunk-{ordinal:02d}", part,
                                    normalize(doc.metadata['title'] + '\n' + part), metadata))
    return docs, chunks, excluded

def save_chunks(tokenizer):
    docs, chunks, excluded = create_chunks(tokenizer)
    write_json(ROOT / 'evidence/chunks.json', {
        'profile': PROFILE, 'document_count': len(docs), 'chunk_count': len(chunks),
        'excluded': excluded, 'chunks': [asdict(c) for c in chunks]})
    return docs, chunks, excluded


import math
from .config import ROOT, file_sha256, read_json, write_json

BEHAVIOR = ROOT / 'behavior'
ROLES = {
    'customer': ('public',),
    'support': ('public', 'staff'),
    'manager': ('public', 'staff', 'manager'),
}
VERSIONS = ('v1', 'v2')
DECISIONS = {
    'v1': ['answer', 'insufficient_context'],
    'v2': ['answer', 'clarify', 'refuse', 'escalate'],
}
GUARDS = ['answer_requires_citations', 'citation_provenance',
          'empty_context_blocks_answer', 'forbidden_context_blocks_answer']

def allowed_access(role):
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('role must be customer, support or manager')
    return ROLES[role]

def access_filter(role):
    return {'access': {'$in': list(allowed_access(role))}}

def source_filter(policy):
    return ({'source_status': {'$eq': 'current'}}
            if policy['parameters']['filter_current_sources'] else None)

def query_filter(role, policy):
    access = access_filter(role)
    status = source_filter(policy)
    return {'$and': [access, status]} if status else access

def source_allowed(metadata, policy):
    status = metadata.get('source_status')
    if status not in ('current', 'superseded'):
        raise ValueError('Candidate source_status must be current or superseded')
    return not policy['parameters']['filter_current_sources'] or status == 'current'

def distance_limit(value, label, nullable=False):
    if value is None and nullable:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2:
        raise ValueError(label + ' must be a finite cosine distance between 0 and 2')

def snapshot(version=None):
    if version is None:
        active = read_json(BEHAVIOR / 'active.json')
        if not isinstance(active, dict) or set(active) != {'version'}:
            raise ValueError('active policy must contain only version')
        version = active['version']
    if version not in VERSIONS:
        raise ValueError('policy version must be v1 or v2')
    path = BEHAVIOR / (version + '.json')
    parameters = read_json(path)
    keys = {'version', 'retrieval_threshold', 'authorization_probe_distance',
            'filter_current_sources', 'decisions', 'guards'}
    if not isinstance(parameters, dict) or set(parameters) != keys:
        raise ValueError('policy has unexpected fields')
    if parameters['version'] != version or parameters['decisions'] != DECISIONS[version]:
        raise ValueError('policy version/decisions mismatch')
    if parameters['guards'] != GUARDS:
        raise ValueError('policy must preserve source and context guards')
    distance_limit(parameters['retrieval_threshold'], 'retrieval_threshold', nullable=version == 'v1')
    if version == 'v1' and parameters['retrieval_threshold'] is not None:
        raise ValueError('v1 retrieval_threshold must be null')
    distance_limit(parameters['authorization_probe_distance'], 'authorization_probe_distance')
    if type(parameters['filter_current_sources']) is not bool:
        raise ValueError('filter_current_sources must be a boolean')
    system_path = BEHAVIOR / ('system-' + version + '.md')
    if not system_path.is_file() or not system_path.read_text(encoding='utf-8-sig').strip():
        raise ValueError('Policy system instructions are missing or empty')
    return {'version': version, 'policy_sha256': file_sha256(path),
            'parameters': parameters,
            'system_instructions_path': 'behavior/system-' + version + '.md',
            'system_instructions_sha256': file_sha256(system_path)}

def use(version):
    selected = snapshot(version)
    write_json(BEHAVIOR / 'active.json', {'version': version})
    return {'status': 'policy_selected', 'policy': selected}

def within_threshold(distance, policy):
    distance_limit(distance, 'hit distance')
    cutoff = policy['parameters']['retrieval_threshold']
    return cutoff is None or distance <= cutoff

def select_candidates(results, role, policy, probe=None):
    allowed = allowed_access(role)
    hits = []
    distances = results.get('distances', [[]])[0]
    for cid, text, metadata, distance in zip(results['ids'][0], results['documents'][0],
                                           results['metadatas'][0], distances):
        if metadata.get('access') not in allowed:
            raise ValueError('Authorized query returned an inaccessible candidate')
        if not source_allowed(metadata, policy):
            raise ValueError('Authorized query returned a superseded candidate')
        hits.append({'chunk_id': cid, 'text': text, 'metadata': metadata,
                     'distance': float(distance)})
    kept = [hit for hit in hits if within_threshold(hit['distance'], policy)]
    blocked = False
    if probe and probe.get('ids') and probe['ids'][0]:
        metadata = probe['metadatas'][0][0]
        if not source_allowed(metadata, policy):
            raise ValueError('Metadata probe returned a superseded candidate')
        nearest = float(probe['distances'][0][0])
        distance_limit(nearest, 'probe distance')
        best_allowed = min((hit['distance'] for hit in hits), default=float('inf'))
        blocked = (metadata.get('access') not in allowed
                   and nearest <= policy['parameters']['authorization_probe_distance']
                   and nearest < best_allowed)
    state = 'forbidden' if blocked else ('available' if kept else 'empty')
    filtering = {'authorized_candidates': len(hits), 'distance_rejected': len(hits) - len(kept),
                 'context_withheld': len(kept) if blocked else 0,
                 'kept': 0 if blocked else len(kept), 'authorization_blocked': blocked}
    if blocked:
        kept = []
    return [{**hit, 'rank': rank} for rank, hit in enumerate(kept, 1)], state, filtering

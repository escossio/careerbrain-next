"""Private, evidence-only matching over already versioned profile and catalog facts."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from careerbrain.db import tenant_transaction


@dataclass(frozen=True)
class MatchClaim:
    job_id: UUID
    tenant_id: UUID
    event_id: UUID
    profile_version: int
    cache_id: UUID
    policy_version: str
    generation: int
    deletion_epoch: int
    fencing: int


def _valid_evidence(evidence: object, source_version: object) -> bool:
    if (not isinstance(source_version, str) or not source_version
            or not isinstance(evidence, dict) or evidence.get('source_version') != source_version):
        return False
    field, quote, start, end = (evidence.get(key) for key in ('field', 'quote', 'start', 'end'))
    return (isinstance(field, str) and bool(field.strip()) and isinstance(quote, str) and bool(quote)
            and isinstance(start, int) and isinstance(end, int) and 0 <= start < end
            and end - start == len(quote))


def _unmet_requirement_proofs(profile: dict, classification: dict) -> list[dict]:
    """Accept only the V2/V3 pair; legacy attributes never prove a negative."""
    result = classification['result']
    if (result.get('schema_version') != 'careerbrain.semantics.v2'
            or profile.get('contract_version') != 'careerbrain.profile.v3'):
        return []
    requirements = result.get('mandatory_requirements')
    attestations = profile.get('negative_attestations')
    source_version = result.get('source_version')
    profile_source_version = profile.get('source_version')
    if not isinstance(requirements, list) or not isinstance(attestations, list):
        return []
    proofs = []
    for requirement in requirements:
        if not isinstance(requirement, dict) or not _valid_evidence(requirement.get('evidence'), source_version):
            continue
        key = (requirement.get('requirement_id'), requirement.get('name'),
               str(requirement.get('value', '')).casefold())
        if not all(key):
            continue
        for attestation in attestations:
            if not isinstance(attestation, dict) or attestation.get('state') != 'NOT_MET':
                continue
            candidate = (attestation.get('requirement_id'), attestation.get('name'),
                         str(attestation.get('value', '')).casefold())
            if candidate == key and _valid_evidence(attestation.get('evidence'), profile_source_version):
                proofs.append({'mandatory_requirement': requirement,
                               'negative_attestation': attestation})
                break
    return proofs


def _matching_key(attribute: dict) -> tuple[str, str]:
    # Explicit, auditable PT-BR/EN synonym dictionary. Both sides retain raw
    # text quotes/offsets; we never invent qualifications from job titles.
    term = attribute['value'].casefold().strip()
    normalized = {
        'telecomunicações': 'telecom', 'telecomunicacoes': 'telecom',
        'observabilidade': 'observability', 'infraestrutura': 'infrastructure',
        'automação': 'automation', 'automacao': 'automation',
        'redes de computadores': 'network', 'redes': 'network',
        'roteamento': 'routing', 'monitoramento': 'observability',
    }
    return attribute['name'], normalized.get(term, term)


def evaluate(profile: dict, classification: dict) -> tuple[Decimal | None, Decimal | None, list[str], list[dict]]:
    """Return only reproducible overlap or a complete, versioned negative pair."""
    if profile['status'] != 'READY' or classification['status'] != 'READY':
        return None, None, ['REQUIREMENT_UNKNOWN'], []
    unmet = _unmet_requirement_proofs(profile, classification)
    if unmet:
        return None, None, ['REQUIREMENT_UNMET'], unmet
    global_attributes = [a for a in classification['result']['attributes'] if a['basis'] == 'explicit' and a['evidence']]
    private_attributes = {_matching_key(a) for a in profile['attributes']
                          if a['basis'] == 'explicit' and a['evidence']}
    if not global_attributes or not private_attributes:
        return None, None, ['REQUIREMENT_UNKNOWN'], []
    matched = {_matching_key(a) for a in global_attributes} & private_attributes
    if not matched:
        return None, None, ['REQUIREMENT_UNKNOWN'], []
    affinity = Decimal(len(matched)) / Decimal(len({_matching_key(a) for a in global_attributes}))
    confidence = min((Decimal(str(a['confidence'])) for a in global_attributes
                      if _matching_key(a) in matched), default=Decimal(0))
    return affinity, confidence, ['EVIDENCED_AFFINITY'], []


class MatchService:
    def __init__(self, api_pool, worker_pool):
        self.api_pool, self.worker_pool = api_pool, worker_pool
        with worker_pool.connection() as connection:
            if connection.execute('SELECT current_user').fetchone()[0] != 'cb_private_worker':
                raise ValueError('Runtime database role mismatch')

    def schedule(self, tenant_id: str, event_id: str) -> str | None:
        with tenant_transaction(self.worker_pool, tenant_id) as connection:
            row = connection.execute('SELECT private.create_match_job(%s)', (event_id,)).fetchone()
        return None if row[0] is None else str(row[0])

    def claim(self) -> MatchClaim | None:
        owner = uuid4()
        with self.worker_pool.connection() as connection:
            row = connection.execute('SELECT * FROM private.claim_match_job(%s)', (owner,)).fetchone()
        return None if row is None else MatchClaim(*row[:-1], fencing=row[-1])

    def process_once(self) -> str | None:
        claim = self.claim()
        if claim is None:
            return None
        with tenant_transaction(self.worker_pool, str(claim.tenant_id)) as connection:
            profile = connection.execute('''SELECT status,attributes,profile_version,contract_version,
                    source_version,negative_attestations FROM private.profiles WHERE tenant_id=%s''',
                                         (claim.tenant_id,)).fetchone()
            classified = connection.execute('''SELECT c.status,c.result FROM catalog.current_classifications c
                WHERE c.event_id=%s AND c.cache_id=%s''', (claim.event_id, claim.cache_id)).fetchone()
            if profile is None or classified is None:
                affinity, confidence, reasons, proofs = None, None, ['REQUIREMENT_UNKNOWN'], []
            else:
                affinity, confidence, reasons, proofs = evaluate({'status': profile[0], 'attributes': profile[1],
                                                                    'profile_version': profile[2],
                                                                    'contract_version': profile[3],
                                                                    'source_version': profile[4],
                                                                    'negative_attestations': profile[5]},
                                                         {'status': classified[0], 'result': classified[1]})
            row = connection.execute('SELECT private.complete_match_job(%s,%s,%s,%s,%s,%s,%s)',
                (claim.job_id, connection.execute('SELECT lease_owner FROM queue.private_jobs WHERE id=%s',
                                                   (claim.job_id,)).fetchone()[0], claim.fencing,
                 affinity, confidence, reasons, Jsonb(proofs))).fetchone()
        return row[0]

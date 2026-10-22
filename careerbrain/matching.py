"""Private, evidence-only matching over already versioned profile and catalog facts."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

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


def evaluate(profile: dict, classification: dict) -> tuple[Decimal | None, Decimal | None, list[str]]:
    """Return only reproducible overlap; lack of evidence is deliberately null."""
    if profile['status'] != 'READY' or classification['status'] != 'READY':
        return None, None, ['REQUIREMENT_UNKNOWN']
    global_attributes = [a for a in classification['result']['attributes'] if a['basis'] == 'explicit' and a['evidence']]
    private_attributes = {(a['name'], a['value'].casefold()) for a in profile['attributes']
                          if a['basis'] == 'explicit' and a['evidence']}
    if not global_attributes or not private_attributes:
        return None, None, ['REQUIREMENT_UNKNOWN']
    matched = {(a['name'], a['value'].casefold()) for a in global_attributes} & private_attributes
    if not matched:
        return None, None, ['REQUIREMENT_UNKNOWN']
    affinity = Decimal(len(matched)) / Decimal(len({(a['name'], a['value'].casefold()) for a in global_attributes}))
    confidence = min((Decimal(str(a['confidence'])) for a in global_attributes
                      if (a['name'], a['value'].casefold()) in matched), default=Decimal(0))
    return affinity, confidence, ['EVIDENCED_AFFINITY']


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
            profile = connection.execute('SELECT status,attributes FROM private.profiles WHERE tenant_id=%s',
                                         (claim.tenant_id,)).fetchone()
            classified = connection.execute('''SELECT c.status,c.result FROM catalog.current_classifications c
                WHERE c.event_id=%s AND c.cache_id=%s''', (claim.event_id, claim.cache_id)).fetchone()
            if profile is None or classified is None:
                affinity, confidence, reasons = None, None, ['REQUIREMENT_UNKNOWN']
            else:
                affinity, confidence, reasons = evaluate({'status': profile[0], 'attributes': profile[1]},
                                                         {'status': classified[0], 'result': classified[1]})
            row = connection.execute('SELECT private.complete_match_job(%s,%s,%s,%s,%s,%s)',
                (claim.job_id, connection.execute('SELECT lease_owner FROM queue.private_jobs WHERE id=%s',
                                                   (claim.job_id,)).fetchone()[0], claim.fencing,
                 affinity, confidence, reasons)).fetchone()
        return row[0]

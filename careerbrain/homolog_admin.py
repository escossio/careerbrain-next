"""Emit idempotent, narrowly-scoped SQL for synthetic homologation only."""
from __future__ import annotations

import argparse
from uuid import uuid5

from .homolog_producer import AUTH, NS, SOURCE, records

PRODUCER = str(uuid5(NS, 'synthetic-141-producer-v3'))


def sql(token_digest: str) -> str:
    if len(token_digest) != 64 or any(char not in '0123456789abcdef' for char in token_digest): raise ValueError('token digest must be lowercase sha256')
    lines = ['BEGIN;', f"INSERT INTO catalog.sources(id,name) VALUES ('{SOURCE}','SYNTHETIC/HOMOLOG 141') ON CONFLICT (id) DO NOTHING;", f"INSERT INTO catalog.producers(id,active) VALUES ('{PRODUCER}',true) ON CONFLICT (id) DO UPDATE SET active=true;", f"INSERT INTO catalog.authorizations(id,producer_id,source_id,active,usage_allowed) VALUES ('{AUTH}','{PRODUCER}','{SOURCE}',true,true) ON CONFLICT (id) DO UPDATE SET producer_id=EXCLUDED.producer_id,active=true,usage_allowed=true;", f"INSERT INTO catalog.official_contacts(authorization_id,kind,value) VALUES ('{AUTH}','https','https://homolog.invalid/contact/careerbrain-synthetic') ON CONFLICT DO NOTHING;", f"INSERT INTO catalog.producer_tokens(token_digest,producer_id,scope,active) VALUES ('{token_digest}','{PRODUCER}','ingestion:write',true) ON CONFLICT (token_digest) DO UPDATE SET producer_id=EXCLUDED.producer_id,active=true;"]
    for row in records():
        event = row['vacancy']['event']; proof = event['provenance']; evidence = proof['evidence_id']
        access_url = row['vacancy']['access']['value']
        lines.append(f"INSERT INTO catalog.official_contacts(authorization_id,kind,value) VALUES ('{AUTH}','https','{access_url}') ON CONFLICT DO NOTHING;")
        lines.append("INSERT INTO catalog.evidence(id,source_id,authorization_id,digest,kind,url,observed_at,published_at,source_event_id,extractor_version) " + f"VALUES ('{evidence}','{SOURCE}','{AUTH}','{proof['evidence_sha256']}','source_statement','{proof['evidence_url']}','{proof['observed_at']}','{event['published_at']}','{event['source_event_id']}','synthetic-homolog-v2') ON CONFLICT (id,source_id) DO UPDATE SET digest=EXCLUDED.digest,kind=EXCLUDED.kind,url=EXCLUDED.url,observed_at=EXCLUDED.observed_at,published_at=EXCLUDED.published_at,source_event_id=EXCLUDED.source_event_id,extractor_version=EXCLUDED.extractor_version;")
        lines.append(f"INSERT INTO catalog.evidence_approvals(evidence_id,source_id,authorization_id) VALUES ('{evidence}','{SOURCE}','{AUTH}') ON CONFLICT DO NOTHING;")
    return '\n'.join(lines + ['COMMIT;']) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument('--token-digest', required=True); args = parser.parse_args(); print(sql(args.token_digest), end=''); return 0


if __name__ == '__main__': raise SystemExit(main())

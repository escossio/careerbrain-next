"""Deterministic synthetic-only producer for the authenticated ingestion contract."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import ssl
import urllib.request
from pathlib import Path
from uuid import UUID, uuid5

NS = UUID('11111111-1111-1111-1111-111111111111')
SOURCE = str(uuid5(NS, 'synthetic-141-source'))
AUTH = str(uuid5(NS, 'synthetic-141-authorization'))
FIXED_TIME = '2026-10-23T12:00:00Z'
EVIDENCE_ROOT = 'https://homolog.invalid/evidence/careerbrain-synthetic-141'


def _family(index: int) -> tuple[str, str, list[str]]:
    families = (
        ('DevOps Engineer', 'Python, cloud, automation and observability for production infrastructure in this synthetic homologation role.', ['Python', 'cloud', 'automation']),
        ('SRE Engineer', 'Python automation and observability for reliable infrastructure operations in this synthetic homologation role.', ['Python', 'observability', 'infrastructure']),
        ('Network Engineer', 'Routing, switching and telecom operations; Python is not required in this synthetic homologation role.', ['routing', 'telecom']),
        ('Electrical Technician', 'instalações elétricas and field safety activities for this synthetic homologation technical role.', ['instalações elétricas', 'safety']),
        ('Nursing Assistant', 'enfermagem assistance in a clinical care setting for this synthetic homologation support role.', ['enfermagem', 'care']),
        ('Customer Support Analyst', 'atendimento ao cliente for a synthetic support operation with documented service procedures.', ['atendimento ao cliente', 'support']),
        ('Product Designer', 'Interface research and visual design with no listed deterministic skill in this synthetic homologation role.', ['design', 'research']),
    )
    return families[index % len(families)]


def records() -> list[dict]:
    rows = []
    for index in range(1, 142):
        title, description, requirements = _family(index - 1)
        evidence_id = str(uuid5(NS, f'synthetic-141-evidence-{index:03d}'))
        evidence_url = f'{EVIDENCE_ROOT}/synth-{index:03d}'
        evidence_digest = hashlib.sha256((evidence_url + '\n' + description).encode()).hexdigest()
        rows.append({'operation': 'publish', 'vacancy': {
            'source_id': SOURCE, 'source_vacancy_id': f'synth-{index:03d}',
            'title': f'{title} — SYNTHETIC/HOMOLOG {index:03d}',
            'organization': 'CareerBrain Synthetic Labs', 'description': description,
            'requirements': requirements, 'modality': ('remote', 'hybrid', 'onsite')[(index - 1) % 3],
            'location': 'Synthetic City/BR', 'employment_type': ('employee', 'contractor', 'internship')[(index - 1) % 3],
            'access': {'kind': 'https', 'value': f'https://homolog.invalid/apply/synth-{index:03d}'},
            'event': {'source_event_id': f'synth-event-{index:03d}', 'kind': 'original', 'published_at': FIXED_TIME,
                      'provenance': {'authorization_id': AUTH, 'evidence_id': evidence_id,
                                     'evidence_sha256': evidence_digest, 'evidence_kind': 'source_statement',
                                     'evidence_url': evidence_url, 'observed_at': FIXED_TIME,
                                     'extractor_version': 'synthetic-homolog-v2'}}}})
    return rows


def payload(batch_id: str, rows: list[dict]) -> bytes:
    return json.dumps({'schema_version': 'careerbrain.ingestion.v1', 'batch_id': batch_id, 'records': rows}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def write_artifacts(directory: Path) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    rows = records(); output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=('source_vacancy_id', 'source_event_id', 'title', 'organization', 'description', 'requirements', 'modality', 'employment_type', 'access_url', 'evidence_url'))
    writer.writeheader()
    for row in rows:
        item = row['vacancy']
        writer.writerow({'source_vacancy_id': item['source_vacancy_id'], 'source_event_id': item['event']['source_event_id'], 'title': item['title'], 'organization': item['organization'], 'description': item['description'], 'requirements': '|'.join(item['requirements']), 'modality': item['modality'], 'employment_type': item['employment_type'], 'access_url': item['access']['value'], 'evidence_url': item['event']['provenance']['evidence_url']})
    artifacts = {'synthetic-141.csv': output.getvalue().encode(), 'synthetic-141-a.json': payload('synthetic-141-a', rows[:100]), 'synthetic-141-b.json': payload('synthetic-141-b', rows[100:])}
    for name, content in artifacts.items(): (directory / name).write_bytes(content)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in artifacts.items()}
    (directory / 'SHA256SUMS.json').write_text(json.dumps(hashes, sort_keys=True, indent=2) + '\n')
    return hashes


def submit(batch_id: str, rows: list[dict], *, url: str, token: str, ca_file: str) -> dict:
    request = urllib.request.Request(url, payload(batch_id, rows), {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Idempotency-Key': batch_id}, method='POST')
    context = ssl.create_default_context(cafile=ca_file)
    with urllib.request.urlopen(request, context=context, timeout=15) as response:
        return {'batch_id': batch_id, 'http_status': response.status, 'idempotent_replay': response.headers.get('Idempotent-Replay') == 'true', 'receipt': json.loads(response.read())}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument('--write-artifacts', type=Path); parser.add_argument('--submit', action='store_true'); args = parser.parse_args()
    if args.write_artifacts: print(json.dumps({'artifacts_sha256': write_artifacts(args.write_artifacts)}, sort_keys=True))
    if args.submit:
        rows = records(); token = os.environ['CBN_PRODUCER_TOKEN']
        print(json.dumps({'generated': len(rows), 'receipts': [submit('synthetic-141-a', rows[:100], url=os.environ['CBN_INGEST_URL'], token=token, ca_file=os.environ['CBN_TLS_CA']), submit('synthetic-141-b', rows[100:], url=os.environ['CBN_INGEST_URL'], token=token, ca_file=os.environ['CBN_TLS_CA'])]}, sort_keys=True))
    if not args.write_artifacts and not args.submit: parser.error('choose --write-artifacts and/or --submit')
    return 0


if __name__ == '__main__': raise SystemExit(main())

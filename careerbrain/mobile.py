"""Private mobile read/sync/command boundary for pass 08."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timezone
from uuid import UUID

from psycopg.types.json import Jsonb

from careerbrain.db import tenant_transaction
from tools.contracts import ContractError, digest, validate


class Conflict(ValueError):
    pass


def _time(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class MobileService:
    def __init__(self, pool):
        self.pool = pool

    def recommendations(self, tenant_id, cursor=None, limit=50):
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('invalid limit')
        after_time, after_id = None, None
        if cursor:
            try:
                after_time, after_id = cursor.split('.', 1)
                UUID(after_id)
            except (AttributeError, ValueError):
                raise ValueError('invalid cursor') from None
        with tenant_transaction(self.pool, tenant_id) as c:
            profile = c.execute('SELECT profile_version FROM private.profiles').fetchone()
            if profile is None:
                return {'schema_version': 'careerbrain.recommendation-page.v1', 'profile_version': 1, 'items': [], 'next_cursor': None}
            rows = c.execute('''SELECT r.recommendation_id,r.event_id,r.profile_version,r.policy_version,
                r.affinity::float8,r.confidence::float8,r.reasons,r.available_at,e.vacancy_id,v.content->>'title',v.content->'access'
                FROM private.current_recommendations r JOIN private.recommendations base ON base.recommendation_id=r.recommendation_id
                JOIN catalog.publication_events e ON e.id=r.event_id JOIN catalog.vacancies v ON v.id=e.vacancy_id
                WHERE (%s::timestamptz IS NULL OR (base.available_at,base.recommendation_id)>(%s::timestamptz,%s::uuid))
                ORDER BY base.available_at,base.recommendation_id LIMIT %s''', (after_time, after_time, after_id, limit + 1)).fetchall()
        page, more = rows[:limit], len(rows) > limit
        items = [{'recommendation_id': str(x[0]), 'match': {'schema_version': 'careerbrain.match.v1', 'tenant_id': str(tenant_id),
                  'vacancy_id': str(x[8]), 'publication_event_id': str(x[1]), 'profile_version': x[2], 'policy_version': x[3],
                  'eligible': True, 'affinity': x[4], 'confidence': x[5], 'reasons': x[6]}, 'title': x[9], 'access': x[10]} for x in page]
        next_cursor = f'{_time(page[-1][7])}.{page[-1][0]}' if more else None
        return {'schema_version': 'careerbrain.recommendation-page.v1', 'profile_version': profile[0], 'items': items, 'next_cursor': next_cursor}

    def changes(self, tenant_id, cursor=None, limit=50):
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('invalid limit')
        with tenant_transaction(self.pool, tenant_id) as c:
            if cursor:
                try: token = UUID(cursor)
                except (ValueError, TypeError): raise ValueError('invalid cursor') from None
                snapshot = c.execute('SELECT high_watermark,after_sequence FROM private.feed_snapshots WHERE cursor=%s AND expires_at>transaction_timestamp()', (token,)).fetchone()
                if snapshot is None: raise LookupError('expired cursor')
            else:
                high = c.execute('SELECT COALESCE(sequence,0) FROM private.feed_counters').fetchone()
                snapshot = (high[0] if high else 0, 0)
            high, after = snapshot
            # A terminal cursor starts the next immutable snapshot.  Thus a
            # late classification is not hidden behind a completed watermark.
            if after == high:
                row = c.execute('SELECT COALESCE(sequence,0) FROM private.feed_counters').fetchone()
                high, after = (row[0] if row else 0), 0
            rows = c.execute('''SELECT sequence,recommendation_id,event_id,profile_version,kind,created_at
                FROM private.feed WHERE sequence>%s AND sequence<=%s ORDER BY sequence LIMIT %s''', (after, high, limit + 1)).fetchall()
            page, more = rows[:limit], len(rows) > limit
            next_after = page[-1][0] if page else after
            token = c.execute('''INSERT INTO private.feed_snapshots(tenant_id,high_watermark,after_sequence)
                VALUES(identity.active_tenant(),%s,%s) RETURNING cursor''', (high, next_after)).fetchone()[0]
        items = [{'sequence': x[0], 'recommendation_id': str(x[1]), 'publication_event_id': str(x[2]), 'profile_version': x[3],
                  'kind': 'AVAILABLE' if x[4] == 'UPSERT' else 'REMOVED', 'available_at': _time(x[5])} for x in page]
        return {'schema_version': 'careerbrain.sync.v1', 'snapshot_high_watermark': high, 'items': items, 'next_cursor': str(token), 'has_more': more}

    def ack(self, tenant_id, command):
        validate('sync-ack', command)
        ids = [UUID(value) for value in command['recommendation_ids']]
        with tenant_transaction(self.pool, tenant_id) as c:
            result = c.execute('SELECT private.ack_recommendations(%s,%s,%s)', (command['request_id'], ids, digest(command))).fetchone()[0]
        if result == 'IDEMPOTENCY_CONFLICT': raise Conflict()

    def application(self, tenant_id, command):
        validate('application-command', command)
        with tenant_transaction(self.pool, tenant_id) as c:
            result = c.execute('SELECT private.apply_application(%s,%s)', (Jsonb(command), digest(command))).fetchone()[0]
        if result in ('IDEMPOTENCY_CONFLICT', 'VERSION_CONFLICT'): raise Conflict()

    def delete(self, tenant_id, request_id):
        if not isinstance(request_id, str) or not request_id:
            raise ValueError('invalid request')
        capability = secrets.token_urlsafe(32)
        with tenant_transaction(self.pool, tenant_id) as c:
            row = c.execute('SELECT * FROM ops.request_deletion(%s,%s)', (request_id, hashlib.sha256(capability.encode()).hexdigest())).fetchone()
        return {'schema_version': 'careerbrain.deletion.v1', 'request_id': request_id, 'state': 'ACTIVE_DATA_REMOVED',
                'active_data_deadline': _time(row[1]), 'backup_expiry_deadline': _time(row[2]), 'receipt_id': str(row[0]), 'deletion_capability': capability}

    def receipt(self, receipt_id, capability):
        try: receipt = UUID(receipt_id)
        except ValueError: raise ValueError('invalid receipt') from None
        with self.pool.connection() as c:
            row = c.execute('SELECT * FROM ops.get_deletion_receipt(%s,%s)', (receipt, hashlib.sha256(capability.encode()).hexdigest())).fetchone()
        if row is None: raise LookupError('missing receipt')
        return {'schema_version': 'careerbrain.deletion.v1', 'request_id': row[0], 'state': row[1],
                'active_data_deadline': _time(row[2]), 'backup_expiry_deadline': _time(row[3]), 'receipt_id': receipt_id}

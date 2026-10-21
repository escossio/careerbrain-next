"""Explicit disposable migrations and transaction-scoped tenant connections."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
from uuid import UUID

from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('cb_migrator', 'cb_auth', 'cb_api', 'cb_global_worker', 'cb_private_worker', 'cb_privacy')


class MigrationError(RuntimeError):
    pass


def require_disposable(connection):
    if not connection.info.dbname.startswith('cbn_test_'):
        raise MigrationError('This runner is restricted to disposable test databases')


def bootstrap_disposable(connection):
    require_disposable(connection)
    connection.execute((ROOT / 'db/bootstrap.sql').read_text(), prepare=False)
    database = sql.Identifier(connection.info.dbname)
    connection.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(database))
    connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
        database, sql.SQL(',').join(map(sql.Identifier, ROLES))))
    connection.execute(sql.SQL('GRANT CREATE,CONNECT ON DATABASE {} TO cb_owner').format(database))


@dataclass(frozen=True)
class Migration:
    version: int
    up: str
    down: str | None
    checksum: str


def migrations(directory: Path | None = None) -> list[Migration]:
    directory = directory or ROOT / 'db/migrations'
    result = []
    for path in sorted(directory.glob('*.sql')):
        if path.name.endswith('.down.sql'):
            continue
        down_path = path.with_suffix('.down.sql')
        up = path.read_text()
        down = down_path.read_text() if down_path.is_file() else None
        result.append(Migration(int(path.name.split('_')[0]), up, down,
                                hashlib.sha256((up + '\0' + (down or '')).encode()).hexdigest()))
    if not result or len({m.version for m in result}) != len(result):
        raise MigrationError('Missing or duplicate migrations')
    return result


def migrate(connection, target: int | None = None):
    require_disposable(connection)
    known = {m.version: m for m in migrations()}
    target = max(known) if target is None else target
    if target not in known:
        raise MigrationError('Unknown target; destructive foundation downgrade is not supported')
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(704201,2)')
        connection.execute('SET LOCAL ROLE cb_owner')
        connection.execute('''CREATE TABLE IF NOT EXISTS ops.schema_migrations (
            version integer PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT transaction_timestamp())''')
        applied = dict(connection.execute('SELECT version,checksum FROM ops.schema_migrations').fetchall())
        for version, checksum in applied.items():
            if version not in known or checksum != known[version].checksum:
                raise MigrationError('Migration checksum mismatch or unknown applied version')
        for version in sorted(applied, reverse=True):
            if version > target:
                if known[version].down is None:
                    raise MigrationError('Destructive downgrade refused')
                connection.execute(known[version].down, prepare=False)
                connection.execute('DELETE FROM ops.schema_migrations WHERE version=%s', (version,))
        for version, migration in known.items():
            if version <= target and version not in applied:
                connection.execute(migration.up, prepare=False)
                connection.execute('INSERT INTO ops.schema_migrations(version,checksum) VALUES(%s,%s)',
                                   (version, migration.checksum))


def reset_connection(connection):
    if connection.info.transaction_status != TransactionStatus.IDLE:
        connection.close()
        raise RuntimeError('Pool connection was not idle')
    connection.execute('RESET ROLE; RESET ALL', prepare=False)


def tenant_pool(conninfo: str, *, max_size: int = 4) -> ConnectionPool:
    return ConnectionPool(conninfo, min_size=1, max_size=max_size,
                          kwargs={'autocommit': True}, reset=reset_connection,
                          timeout=5, max_idle=30, open=True)


@contextmanager
def tenant_transaction(pool: ConnectionPool, tenant_id: str):
    tenant = str(UUID(str(tenant_id)))
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (tenant,))
            yield connection

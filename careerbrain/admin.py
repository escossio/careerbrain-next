"""Explicit, one-shot administrative commands for the persistent deployment."""
from __future__ import annotations

import os
import sys

import psycopg

from .db import migrate_persistent


def migrate_main() -> int:
    database = os.environ.get('CBN_DATABASE', '')
    conninfo = os.environ.get('CBN_MIGRATOR_CONNINFO', '')
    if not database or not conninfo or os.environ.get('CBN_MIGRATION_CONFIRM') != database:
        raise SystemExit('refusing migration without exact CBN_MIGRATION_CONFIRM destination')
    with psycopg.connect(conninfo, autocommit=True) as connection:
        migrate_persistent(connection, expected_database=database)
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] != 'migrate':
        raise SystemExit('usage: python -m careerbrain.admin migrate')
    raise SystemExit(migrate_main())

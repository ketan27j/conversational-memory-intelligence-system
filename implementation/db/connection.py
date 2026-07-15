"""Connection helper that binds every session to one tenant.

Per ADR-004: the database enforces tenant isolation via row-level security.
This module is the one place that sets the `app.tenant_id` session variable
RLS policies read — callers never write raw tenant filters into queries.
"""
import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection

DSN = os.environ.get(
    "CMIS_DATABASE_URL",
    "postgresql://cmis_app:cmis_app_dev_only@localhost:5433/cmis",
)


@contextmanager
def tenant_connection(tenant_id: str) -> Iterator[Connection]:
    """Yield a connection scoped to exactly one tenant.

    `tenant_id` must come from the verified auth token (see api/auth.py),
    never from a request body or query param — that is the whole point of
    T7's mitigation (threat_model.md).
    """
    conn = psycopg.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def unscoped_connection() -> Iterator[Connection]:
    """A connection with NO tenant set — used only to prove RLS refuses it.

    `current_setting('app.tenant_id', true)` returns NULL here, and
    `tenant_id = NULL` is never true, so the tenant_isolation policy
    returns zero rows for every table. This is exercised directly by
    tests/test_tenant_isolation.py's "no filter, refused by the database" case.
    """
    conn = psycopg.connect(DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

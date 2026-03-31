"""
Pool de connexions PostgreSQL partagé entre analytics et vector_store.
"""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None


def _parse_db_url(url: str) -> dict:
    """Parse manuel pour gérer les mots de passe avec caractères spéciaux ([],?,%…)."""
    # Format : postgresql://user:password@host:port/dbname
    without_scheme = url.split("://", 1)[1]
    credentials, hostpart = without_scheme.rsplit("@", 1)
    user, password = credentials.split(":", 1)
    hostport, dbname = hostpart.split("/", 1) if "/" in hostpart else (hostpart, "postgres")
    host, port = hostport.rsplit(":", 1) if ":" in hostport else (hostport, "5432")
    return {
        "host":     host,
        "port":     int(port),
        "dbname":   dbname,
        "user":     user,
        "password": password,
        "sslmode":  "require",
    }


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("Variable d'environnement DATABASE_URL manquante.")
        params = _parse_db_url(url)
        _pool = ThreadedConnectionPool(1, 10, **params)
    return _pool


@contextmanager
def get_conn(with_vector: bool = False):
    """Emprunte une connexion du pool, commit ou rollback automatiquement."""
    pool = _get_pool()
    conn = pool.getconn()
    if with_vector:
        register_vector(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

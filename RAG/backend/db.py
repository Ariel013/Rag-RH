"""
Pool de connexions PostgreSQL partagé entre analytics et vector_store.
"""
import os
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None

# Retry/backoff à la création du pool : une reprise Supabase (sortie de pause,
# maintenance) peut mettre quelques dizaines de secondes à devenir joignable.
# Sans ça, le premier échec de connexion fait planter tout le process au boot.
_POOL_MAX_ATTEMPTS = 5
_POOL_RETRY_BASE_DELAY = 5  # secondes, doublé à chaque tentative (5, 10, 20, 40)


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

        delay = _POOL_RETRY_BASE_DELAY
        for attempt in range(1, _POOL_MAX_ATTEMPTS + 1):
            try:
                _pool = ThreadedConnectionPool(1, 10, **params)
                break
            except psycopg2.OperationalError as exc:
                if attempt == _POOL_MAX_ATTEMPTS:
                    raise
                print(
                    f"  ✗ Connexion DB échouée (tentative {attempt}/{_POOL_MAX_ATTEMPTS}), "
                    f"nouvelle tentative dans {delay}s : {exc}"
                )
                time.sleep(delay)
                delay *= 2
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


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None

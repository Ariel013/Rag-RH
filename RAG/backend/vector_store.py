"""
Vector store — PostgreSQL + pgvector (Supabase).
Remplace ChromaDB : persistant, pas de dépendance lourde.
"""
import psycopg2.extras

from .db import get_conn

EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2


def init_vector_db() -> None:
    """Crée les tables et index si inexistants. Appelé au démarrage."""
    with get_conn(with_vector=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Topics sémantiques (doit exister avant messages pour la FK)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS topics (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL UNIQUE,
                    embedding  vector({EMBEDDING_DIM}),
                    is_custom  BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id          TEXT PRIMARY KEY,
                    doc_id      TEXT NOT NULL,
                    title       TEXT,
                    source      TEXT,
                    category    TEXT,
                    chunk_index INTEGER,
                    content     TEXT NOT NULL,
                    embedding   vector({EMBEDDING_DIM})
                )
            """)

            # Table de suivi des fichiers uploadés (pour suppression dans Storage)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents_meta (
                    doc_id       TEXT PRIMARY KEY,
                    storage_path TEXT,
                    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_doc_id
                    ON document_chunks(doc_id)
            """)
            # Index HNSW pour la recherche cosinus (fonctionne sur table vide)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_hnsw
                    ON document_chunks USING hnsw (embedding vector_cosine_ops)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notion_sync_log (
                    notion_page_id TEXT PRIMARY KEY,
                    doc_id         TEXT NOT NULL,
                    last_edited    TIMESTAMPTZ,
                    synced_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


class VectorStore:

    # ─── Écriture ─────────────────────────────────────────────────────────

    def add_documents(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        doc_id: str,
        storage_path: str | None = None,
    ) -> None:
        with get_conn(with_vector=True) as conn:
            with conn.cursor() as cur:
                # Enregistrer le fichier source
                cur.execute("""
                    INSERT INTO documents_meta (doc_id, storage_path)
                    VALUES (%s, %s)
                    ON CONFLICT (doc_id) DO UPDATE SET storage_path = EXCLUDED.storage_path
                """, (doc_id, storage_path))

                for i, (chunk, emb, meta) in enumerate(zip(chunks, embeddings, metadatas)):
                    cur.execute("""
                        INSERT INTO document_chunks
                            (id, doc_id, title, source, category, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            content   = EXCLUDED.content,
                            embedding = EXCLUDED.embedding
                    """, (
                        f"{doc_id}_{i}",
                        meta.get("doc_id", doc_id),
                        meta.get("title"),
                        meta.get("source"),
                        meta.get("category"),
                        meta.get("chunk_index", i),
                        chunk,
                        emb,
                    ))

    def delete_document(self, doc_id: str) -> tuple[int, str | None]:
        """Retourne (nombre de chunks supprimés, storage_path ou None)."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT storage_path FROM documents_meta WHERE doc_id = %s",
                    (doc_id,),
                )
                row = cur.fetchone()
                storage_path = row[0] if row else None

                cur.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))
                deleted = cur.rowcount
                cur.execute("DELETE FROM documents_meta WHERE doc_id = %s", (doc_id,))
        return deleted, storage_path

    # ─── Lecture ──────────────────────────────────────────────────────────

    def search(
        self, query_embedding: list[float], n_results: int = 5
    ) -> list[dict]:
        with get_conn(with_vector=True) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT content, doc_id, title, source, category, chunk_index,
                           1 - (embedding <=> %s::vector) AS score
                    FROM document_chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, n_results))
                rows = cur.fetchall()

        return [
            {
                "content": r["content"],
                "metadata": {
                    "doc_id":      r["doc_id"],
                    "title":       r["title"]    or "Document",
                    "source":      r["source"]   or "",
                    "category":    r["category"] or "Général",
                    "chunk_index": r["chunk_index"],
                },
                "score": float(r["score"]),
            }
            for r in rows
        ]

    def list_documents(self) -> list[dict]:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (doc_id)
                        doc_id AS id, title, source, category
                    FROM document_chunks
                    ORDER BY doc_id, chunk_index
                """)
                return [dict(r) for r in cur.fetchall()]

    def get_notion_sync_log(self) -> dict[str, dict]:
        """Retourne {notion_page_id: {doc_id, last_edited}} pour toutes les pages trackées."""
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT notion_page_id, doc_id, last_edited FROM notion_sync_log")
                return {
                    r["notion_page_id"]: {
                        "doc_id":      r["doc_id"],
                        "last_edited": r["last_edited"],
                    }
                    for r in cur.fetchall()
                }

    def upsert_notion_sync_log(
        self, notion_page_id: str, doc_id: str, last_edited: str | None
    ) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO notion_sync_log (notion_page_id, doc_id, last_edited, synced_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (notion_page_id) DO UPDATE SET
                        doc_id      = EXCLUDED.doc_id,
                        last_edited = EXCLUDED.last_edited,
                        synced_at   = NOW()
                """, (notion_page_id, doc_id, last_edited or None))

    def delete_notion_page(self, notion_page_id: str, doc_id: str) -> int:
        """Supprime les chunks d'une page Notion et son entrée dans notion_sync_log."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))
                deleted = cur.rowcount
                cur.execute("DELETE FROM documents_meta WHERE doc_id = %s", (doc_id,))
                cur.execute(
                    "DELETE FROM notion_sync_log WHERE notion_page_id = %s",
                    (notion_page_id,),
                )
        return deleted

    def delete_notion_documents(self) -> int:
        """Supprime tous les chunks Notion et réinitialise le log de sync."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT doc_id FROM document_chunks WHERE source LIKE 'notion:%'")
                notion_doc_ids = [r[0] for r in cur.fetchall()]
                if not notion_doc_ids:
                    cur.execute("DELETE FROM notion_sync_log")
                    return 0
                cur.execute("DELETE FROM document_chunks WHERE source LIKE 'notion:%'")
                deleted = cur.rowcount
                cur.execute(
                    "DELETE FROM documents_meta WHERE doc_id = ANY(%s)",
                    (notion_doc_ids,),
                )
                cur.execute("DELETE FROM notion_sync_log")
        return deleted

    def count(self) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM document_chunks")
                return cur.fetchone()[0]

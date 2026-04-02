"""
Topics sémantiques — classification automatique des questions utilisateurs.
"""
import uuid
import psycopg2.extras

from .db import get_conn

DEFAULT_TOPICS = [
    ("topic_conges",      "Congés et absences"),
    ("topic_paie",        "Paie et salaire"),
    ("topic_avantages",   "Avantages sociaux et mutuelle"),
    ("topic_frais",       "Remboursements et frais"),
    ("topic_onboarding",  "Onboarding et intégration"),
    ("topic_procedures",  "Procédures internes"),
    ("topic_organi",      "Organigramme et contacts"),
    ("topic_outils",      "Outils numériques"),
    ("topic_recrutement", "Recrutement et carrière"),
    ("topic_autre",       "Autre"),
]


def seed_default_topics(rag) -> None:
    """Insère les topics par défaut avec leurs embeddings si absents."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM topics")
            existing = {r[0] for r in cur.fetchall()}

    to_seed = [(tid, name) for tid, name in DEFAULT_TOPICS if tid not in existing]
    if not to_seed:
        return

    names = [name for _, name in to_seed]
    embeddings = rag.embed_texts_sync(names)

    with get_conn(with_vector=True) as conn:
        with conn.cursor() as cur:
            for (tid, name), emb in zip(to_seed, embeddings):
                cur.execute("""
                    INSERT INTO topics (id, name, embedding, is_custom)
                    VALUES (%s, %s, %s, FALSE)
                    ON CONFLICT (id) DO NOTHING
                """, (tid, name, emb))
    print(f"  ✓ {len(to_seed)} topic(s) initialisé(s)")


def assign_topic(question_embedding: list[float]) -> str | None:
    """Retourne l'id du topic le plus proche par similarité cosinus."""
    with get_conn(with_vector=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM topics
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1
            """, (question_embedding,))
            row = cur.fetchone()
    return row[0] if row else None


def get_all_topics() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT t.id, t.name, t.is_custom,
                       COUNT(m.id) AS count
                FROM topics t
                LEFT JOIN messages m ON m.topic_id = t.id
                GROUP BY t.id, t.name, t.is_custom
                ORDER BY count DESC, t.name
            """)
            return [dict(r) for r in cur.fetchall()]


def get_topic_messages(topic_id: str, page: int = 1, page_size: int = 30) -> dict:
    offset = (page - 1) * page_size
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE topic_id = %s", (topic_id,)
            )
            total = cur.fetchone()["c"]
            cur.execute("""
                SELECT id, question, asked_at, had_answer, conversation_id
                FROM messages
                WHERE topic_id = %s
                ORDER BY asked_at DESC
                LIMIT %s OFFSET %s
            """, (topic_id, page_size, offset))
            rows = cur.fetchall()

    items = []
    for r in rows:
        d = dict(r)
        if d.get("asked_at"):
            d["asked_at"] = d["asked_at"].isoformat()
        items.append(d)
    return {"total": total, "page_size": page_size, "items": items}


def create_topic(name: str, embedding: list[float]) -> dict:
    topic_id = "topic_custom_" + uuid.uuid4().hex[:8]
    with get_conn(with_vector=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO topics (id, name, embedding, is_custom)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (name) DO NOTHING
                RETURNING id, name
            """, (topic_id, name.strip(), embedding))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Un topic nommé « {name} » existe déjà.")
    return {"id": row[0], "name": row[1], "is_custom": True, "count": 0}


def reassign_message_topic(message_id: str, topic_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE messages SET topic_id = %s WHERE id = %s",
                (topic_id, message_id),
            )
            return cur.rowcount > 0

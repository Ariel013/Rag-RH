"""
Analytiques — enregistrement des échanges dans PostgreSQL (Supabase)
"""
import json
import uuid

import psycopg2.extras

from .db import get_conn

# Phrases qui signalent l'absence de réponse
_NO_ANSWER = [
    "je ne dispose pas de cette information",
    "je n'ai pas cette information",
    "je n'ai pas d'information",
    "je ne trouve pas cette information",
    "je ne connais pas cette information",
    "cette information n'est pas disponible",
    "je ne peux pas répondre",
    "je n'ai pas accès à cette information",
    "pas dans mes données",
    "n'est pas dans ma base",
    "je ne suis pas en mesure de répondre",
]


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id            TEXT PRIMARY KEY,
                    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    message_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    question        TEXT NOT NULL,
                    answer          TEXT,
                    sources         TEXT,
                    had_answer      INTEGER NOT NULL DEFAULT 1,
                    asked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS unanswered (
                    id             TEXT PRIMARY KEY,
                    message_id     TEXT NOT NULL REFERENCES messages(id),
                    question       TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'pending',
                    admin_response TEXT,
                    resolved_at    TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_msg_conv
                    ON messages(conversation_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_msg_asked
                    ON messages(asked_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_unans_status
                    ON unanswered(status)
            """)
            # Migration : colonne topic_id sur messages (ajout si absente)
            cur.execute("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS topic_id TEXT
            """)


def _is_unanswered(answer: str) -> bool:
    low = (answer or "").lower()
    return any(p in low for p in _NO_ANSWER)


def log_message(
    conversation_id: str, question: str, answer: str, sources: list,
    topic_id: str | None = None,
) -> str:
    msg_id  = str(uuid.uuid4())
    had_ans = 0 if _is_unanswered(answer) else 1
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (conversation_id,),
            )
            cur.execute(
                "UPDATE conversations SET message_count = message_count + 1 WHERE id = %s",
                (conversation_id,),
            )
            cur.execute(
                """INSERT INTO messages
                   (id, conversation_id, question, answer, sources, had_answer, topic_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (msg_id, conversation_id, question, answer, json.dumps(sources), had_ans, topic_id),
            )
            if not had_ans:
                cur.execute(
                    "INSERT INTO unanswered (id, message_id, question) VALUES (%s, %s, %s)",
                    (str(uuid.uuid4()), msg_id, question),
                )
    return msg_id


def get_stats() -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM messages")
            total = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM unanswered WHERE status = 'pending'")
            pending = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM conversations")
            convs = cur.fetchone()["c"]
            cur.execute("""
                SELECT t.id, t.name, COUNT(m.id) AS count
                FROM topics t
                LEFT JOIN messages m ON m.topic_id = t.id
                GROUP BY t.id, t.name
                ORDER BY count DESC
            """)
            top_topics = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS c FROM messages WHERE topic_id IS NULL")
            unclassified = cur.fetchone()["c"]
    return {
        "total_questions":     total,
        "unanswered_pending":  pending,
        "total_conversations": convs,
        "top_topics": [
            {"id": r["id"], "name": r["name"], "count": r["count"]}
            for r in top_topics
        ],
        "unclassified": unclassified,
    }


def get_conversations(page: int = 1, page_size: int = 20) -> dict:
    offset = (page - 1) * page_size
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM conversations")
            total = cur.fetchone()["c"]
            cur.execute("""
                SELECT
                    c.id,
                    c.started_at,
                    c.message_count,
                    (SELECT question FROM messages
                     WHERE conversation_id = c.id ORDER BY asked_at LIMIT 1) AS first_question,
                    (SELECT COUNT(*) FROM messages
                     WHERE conversation_id = c.id AND had_answer = 0) AS unanswered_count
                FROM conversations c
                ORDER BY c.started_at DESC
                LIMIT %s OFFSET %s
            """, (page_size, offset))
            rows = cur.fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if d.get("started_at"): d["started_at"] = d["started_at"].isoformat()
        items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def get_conversation_messages(conversation_id: str) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, question, answer, sources, had_answer, asked_at
                FROM messages WHERE conversation_id = %s ORDER BY asked_at
            """, (conversation_id,))
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:    d["sources"] = json.loads(d["sources"] or "[]")
        except: d["sources"] = []
        if d.get("asked_at"): d["asked_at"] = d["asked_at"].isoformat()
        result.append(d)
    return result


def get_unanswered(status: str = "pending", page: int = 1, page_size: int = 20) -> dict:
    offset = (page - 1) * page_size
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM unanswered WHERE status = %s", (status,)
            )
            total = cur.fetchone()["c"]
            cur.execute("""
                SELECT u.id, u.question, u.status, u.admin_response, u.resolved_at,
                       m.asked_at, m.conversation_id
                FROM unanswered u
                JOIN messages m ON u.message_id = m.id
                WHERE u.status = %s
                ORDER BY m.asked_at DESC
                LIMIT %s OFFSET %s
            """, (status, page_size, offset))
            rows = cur.fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if d.get("asked_at"):    d["asked_at"]    = d["asked_at"].isoformat()
        if d.get("resolved_at"): d["resolved_at"] = d["resolved_at"].isoformat()
        items.append(d)
    return {"total": total, "items": items}


def delete_unanswered(unanswered_id: str) -> bool:
    """Supprime une question sans réponse. Retourne True si trouvée et supprimée."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unanswered WHERE id = %s", (unanswered_id,))
            return cur.rowcount > 0


def resolve_unanswered(unanswered_id: str, admin_response: str) -> str | None:
    """Marque comme résolu et retourne la question (pour l'ajouter au RAG)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question FROM unanswered WHERE id = %s", (unanswered_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            question = row[0]
            cur.execute("""
                UPDATE unanswered
                SET status = 'resolved', admin_response = %s, resolved_at = NOW()
                WHERE id = %s
            """, (admin_response, unanswered_id))
    return question

"""
API FastAPI — Assistant RH RAG
"""
import asyncio
import json
import os
import threading
import uuid
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

from .analytics import (
    get_conversation_messages,
    get_conversations,
    get_stats,
    delete_unanswered,
    get_unanswered,
    init_db,
    log_message,
    resolve_unanswered,
)
from .document_processor import process_document
from .notion_loader import check_notion_connection, load_notion_pages
from .rag import RAGPipeline
from .topics import (
    assign_topic,
    create_topic,
    get_all_topics,
    get_topic_messages,
    reassign_message_topic,
    seed_default_topics,
)
from .vector_store import init_vector_db

# ─── App ───────────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Assistant RH RAG API", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_env = os.getenv("ALLOWED_ORIGINS", "*")
_allowed_origins = (
    ["*"] if _cors_env == "*"
    else [o.strip() for o in _cors_env.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = "uploads"

NOTION_SYNC_INTERVAL = 2 * 60 * 60  # 2 heures en secondes

# ─── Admin Auth ────────────────────────────────────────────────────────────

ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_TOKEN    = os.getenv("ADMIN_TOKEN", "").strip()


def verify_admin(authorization: str | None = Header(default=None)) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN non configuré côté serveur.")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Non autorisé.")

# ─── Supabase Storage ─────────────────────────────────────────────────────

async def _storage_upload(path: str, data: bytes) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url, content=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/octet-stream",
            },
            timeout=30,
        )
        return r.is_success


async def _storage_delete(path: str) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY or not path:
        return
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    async with httpx.AsyncClient() as client:
        await client.delete(
            url,
            headers={"Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=10,
        )

# ─── Singleton RAG ────────────────────────────────────────────────────────

_rag: RAGPipeline | None = None
_rag_lock  = threading.Lock()
_rag_ready = threading.Event()
_sync_lock = threading.Lock()  # empêche les syncs Notion concurrentes


def _init_rag() -> None:
    global _rag
    with _rag_lock:
        if _rag is not None:
            return
        _rag = RAGPipeline()
        _auto_ingest_notion(_rag)
        seed_default_topics(_rag)
    _rag_ready.set()


def _auto_ingest_notion(rag: RAGPipeline) -> None:
    """Synchronise Notion au démarrage (toujours, pour éviter les données périmées après un redémarrage)."""
    count = rag.vector_store.count()
    if count == 0:
        print("→ Base vectorielle vide — synchronisation depuis Notion…")
    else:
        print(f"→ Resync Notion au démarrage ({count} chunks existants)…")
    _sync_notion_blocking(rag)


def _sync_notion_blocking(rag: RAGPipeline) -> dict:
    """
    Resynchronise les documents Notion dans le vector store (thread-safe).
    Supprime les anciens chunks Notion puis réingère toutes les pages.
    """
    with _sync_lock:
        try:
            pages = load_notion_pages()
        except ValueError as exc:
            print(f"  ✗ Notion non configuré : {exc}")
            return {"status": "error", "detail": str(exc)}

        deleted = rag.vector_store.delete_notion_documents()
        if deleted:
            print(f"  → {deleted} anciens chunks Notion supprimés")

        total_chunks = 0
        total_pages = 0
        for chunks, metadatas, doc_id in pages:
            embeddings = rag.embed_texts_sync(chunks)
            rag.vector_store.add_documents(chunks, embeddings, metadatas, doc_id)
            total_chunks += len(chunks)
            total_pages += 1

        print(f"  ✓ Resync Notion terminé : {total_pages} pages, {total_chunks} chunks")
        return {"status": "ok", "pages": total_pages, "chunks": total_chunks}


def get_rag() -> RAGPipeline:
    if not _rag_ready.is_set():
        _rag_ready.wait()
    return _rag  # type: ignore[return-value]


# ─── Tâche de resync automatique toutes les 2h ────────────────────────────

async def _notion_sync_loop() -> None:
    """Tâche de fond : resync Notion toutes les 2 heures."""
    await asyncio.to_thread(_rag_ready.wait)
    while True:
        await asyncio.sleep(NOTION_SYNC_INTERVAL)
        print("→ Resync automatique Notion (toutes les 2h)…")
        try:
            rag = get_rag()
            await asyncio.to_thread(_sync_notion_blocking, rag)
        except Exception as exc:
            print(f"  ✗ Erreur resync automatique Notion : {exc}")


@app.on_event("startup")
async def startup_event() -> None:
    await asyncio.to_thread(init_vector_db)
    await asyncio.to_thread(init_db)
    print("→ Initialisation du pipeline RAG…")
    asyncio.create_task(asyncio.to_thread(_init_rag))
    asyncio.create_task(_notion_sync_loop())


# ─── Modèles Pydantic ─────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    email: str
    password: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []
    conversation_id: str = ""


class ResolveRequest(BaseModel):
    admin_response: str


class TopicCreateRequest(BaseModel):
    name: str


class MessageTopicRequest(BaseModel):
    topic_id: str


# ─── Logging du stream ────────────────────────────────────────────────────

async def _do_log(
    rag: RAGPipeline,
    conversation_id: str,
    question: str,
    full_text: list[str],
    sources: list,
) -> None:
    try:
        embs = await rag.embed_texts([question])
        topic_id = await asyncio.to_thread(assign_topic, embs[0])
        await asyncio.to_thread(
            log_message,
            conversation_id, question, "".join(full_text), sources, topic_id,
        )
    except Exception as exc:
        print(f"  ⚠ Erreur logging: {exc}")


async def _stream_with_logging(
    gen: AsyncGenerator, conversation_id: str, question: str, rag: RAGPipeline,
) -> AsyncGenerator:
    full_text: list[str] = []
    sources: list = []
    async for chunk in gen:
        if chunk.startswith("data: "):
            try:
                data = json.loads(chunk[6:].strip())
                t = data.get("type")
                if t == "text_delta":
                    full_text.append(data.get("content", ""))
                elif t == "sources":
                    sources = data.get("sources", [])
                elif t == "done" and conversation_id:
                    asyncio.create_task(
                        _do_log(rag, conversation_id, question, list(full_text), list(sources))
                    )
            except Exception:
                pass
        yield chunk


# ─── Routes API ───────────────────────────────────────────────────────────

@app.post("/api/admin/login")
async def admin_login(body: AdminLoginRequest):
    if not ADMIN_EMAIL or not ADMIN_PASSWORD or not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="Identifiants admin non configurés sur le serveur.")
    if body.email.strip().lower() == ADMIN_EMAIL and body.password == ADMIN_PASSWORD:
        return {"token": ADMIN_TOKEN}
    raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")


@app.get("/api/health")
async def health():
    ready = _rag_ready.is_set()
    return {
        "status":    "ready" if ready else "initializing",
        "model":     f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3.2')}",
        "documents": get_rag().vector_store.count() if ready else 0,
    }


@app.post("/api/chat")
@limiter.limit("10/minute")
async def chat(request: Request, body: ChatRequest):
    rag     = await asyncio.to_thread(get_rag)
    history = [{"role": m.role, "content": m.content} for m in body.history]
    stream  = _stream_with_logging(
        rag.generate_stream(body.question, history),
        body.conversation_id,
        body.question,
        rag,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/documents")
async def list_documents():
    rag  = await asyncio.to_thread(get_rag)
    docs = rag.vector_store.list_documents()
    return {"documents": docs, "total": len(docs)}


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(default="Général"),
    title: str = Form(default=""),
    _: None = Depends(verify_admin),
):
    ext = Path(file.filename or "file.txt").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté : {ext}. Formats acceptés : PDF, DOCX, TXT, MD.",
        )

    file_id   = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{file_id}{ext}"
    content   = await file.read()

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    try:
        chunks, metadatas, doc_id = process_document(
            str(file_path), title=title or None, category=category,
        )
        if not chunks:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="Document vide ou illisible.")

        rag        = await asyncio.to_thread(get_rag)
        embeddings = await rag.embed_texts(chunks)

        storage_path = f"{file_id}{ext}"
        stored = await _storage_upload(storage_path, content)
        if not stored:
            storage_path = None

        rag.vector_store.add_documents(
            chunks, embeddings, metadatas, doc_id,
            storage_path=storage_path,
        )

        return {
            "status":   "success",
            "doc_id":   doc_id,
            "title":    metadatas[0]["title"],
            "chunks":   len(chunks),
            "stored":   stored,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        file_path.unlink(missing_ok=True)


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, _: None = Depends(verify_admin)):
    rag = await asyncio.to_thread(get_rag)
    deleted, storage_path = rag.vector_store.delete_document(doc_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if storage_path:
        await _storage_delete(storage_path)
    return {"status": "deleted", "doc_id": doc_id, "chunks_removed": deleted}


# ─── Routes Admin Analytics ───────────────────────────────────────────────

@app.get("/api/admin/stats")
async def admin_stats(_: None = Depends(verify_admin)):
    return await asyncio.to_thread(get_stats)


@app.get("/api/admin/conversations")
async def admin_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: None = Depends(verify_admin),
):
    return await asyncio.to_thread(get_conversations, page, page_size)


@app.get("/api/admin/conversations/{conversation_id}/messages")
async def admin_conversation_messages(conversation_id: str, _: None = Depends(verify_admin)):
    return await asyncio.to_thread(get_conversation_messages, conversation_id)


@app.get("/api/admin/unanswered")
async def admin_unanswered(
    status: str = Query(default="pending"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: None = Depends(verify_admin),
):
    if status not in ("pending", "resolved"):
        raise HTTPException(status_code=400, detail="status doit être 'pending' ou 'resolved'")
    return await asyncio.to_thread(get_unanswered, status, page, page_size)


@app.delete("/api/admin/unanswered/{unanswered_id}")
async def admin_delete_unanswered(unanswered_id: str, _: None = Depends(verify_admin)):
    deleted = await asyncio.to_thread(delete_unanswered, unanswered_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Question introuvable.")
    return {"status": "deleted"}


@app.post("/api/admin/unanswered/{unanswered_id}/resolve")
async def admin_resolve(unanswered_id: str, body: ResolveRequest, _: None = Depends(verify_admin)):
    if not body.admin_response.strip():
        raise HTTPException(status_code=400, detail="La réponse ne peut pas être vide.")

    question = await asyncio.to_thread(
        resolve_unanswered, unanswered_id, body.admin_response
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable.")

    rag     = await asyncio.to_thread(get_rag)
    qa_text = f"Question : {question}\n\nRéponse : {body.admin_response}"
    doc_id  = str(uuid.uuid4())
    meta    = {
        "doc_id":      doc_id,
        "title":       f"FAQ — {question[:60]}",
        "source":      "Réponses admin",
        "category":    "FAQ",
        "chunk_index": 0,
    }
    embeddings = await rag.embed_texts([qa_text])
    rag.vector_store.add_documents([qa_text], embeddings, [meta], doc_id)

    return {"status": "resolved", "added_to_rag": True}


# ─── Routes Admin Topics ──────────────────────────────────────────────────

@app.get("/api/admin/topics")
async def admin_list_topics(_: None = Depends(verify_admin)):
    return await asyncio.to_thread(get_all_topics)


@app.get("/api/admin/topics/{topic_id}/messages")
async def admin_topic_messages(
    topic_id: str,
    page: int = Query(default=1, ge=1),
    _: None = Depends(verify_admin),
):
    return await asyncio.to_thread(get_topic_messages, topic_id, page)


@app.post("/api/admin/topics")
async def admin_create_topic(body: TopicCreateRequest, _: None = Depends(verify_admin)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Le nom du topic ne peut pas être vide.")
    rag  = await asyncio.to_thread(get_rag)
    embs = await rag.embed_texts([body.name.strip()])
    try:
        return await asyncio.to_thread(create_topic, body.name.strip(), embs[0])
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/api/admin/messages/{message_id}/topic")
async def admin_reassign_topic(
    message_id: str,
    body: MessageTopicRequest,
    _: None = Depends(verify_admin),
):
    ok = await asyncio.to_thread(reassign_message_topic, message_id, body.topic_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    return {"status": "updated"}


# ─── Routes Admin Notion ──────────────────────────────────────────────────

@app.get("/api/admin/notion-status")
async def notion_status(_: None = Depends(verify_admin)):
    """Vérifie la connexion à Notion et retourne le statut."""
    result = await asyncio.to_thread(check_notion_connection)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.post("/api/admin/sync-notion")
async def sync_notion(_: None = Depends(verify_admin)):
    """Déclenche un resync immédiat depuis Notion."""
    rag = await asyncio.to_thread(get_rag)
    result = await asyncio.to_thread(_sync_notion_blocking, rag)
    if result["status"] == "error":
        raise HTTPException(status_code=503, detail=result["detail"])
    return result


# ─── Frontend statique ────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

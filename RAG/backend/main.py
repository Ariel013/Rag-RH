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
    get_unanswered,
    init_db,
    log_message,
    resolve_unanswered,
)
from .document_processor import process_document
from .rag import RAGPipeline
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

# ─── Admin Auth ────────────────────────────────────────────────────────────

ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_TOKEN    = os.getenv("ADMIN_TOKEN", "").strip()


def verify_admin(authorization: str | None = Header(default=None)) -> None:
    """Dépendance FastAPI — vérifie le token Bearer sur les routes admin."""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN non configuré côté serveur.")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Non autorisé.")

# ─── Supabase Storage ─────────────────────────────────────────────────────

async def _storage_upload(path: str, data: bytes) -> bool:
    """Upload vers Supabase Storage. Retourne True si réussi."""
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
    """Supprime un fichier de Supabase Storage."""
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


def _init_rag() -> None:
    global _rag
    with _rag_lock:
        if _rag is not None:
            return
        _rag = RAGPipeline()
        _auto_ingest_samples(_rag)
    _rag_ready.set()


def _ingest_one(rag: RAGPipeline, doc_path: Path, retries: int = 3) -> bool:
    """Ingère un fichier avec retry. Retourne True si succès."""
    import time
    for attempt in range(1, retries + 1):
        try:
            chunks, metadatas, doc_id = process_document(str(doc_path))
            if not chunks:
                return False
            embeddings = rag.embed_texts_sync(chunks)
            rag.vector_store.add_documents(chunks, embeddings, metadatas, doc_id)
            print(f"  ✓ Ingéré : {doc_path.name} ({len(chunks)} chunks)")
            return True
        except Exception as exc:
            if attempt < retries:
                print(f"  ⚠ Erreur {doc_path.name} (tentative {attempt}/{retries}): {exc} — retry dans 3s…")
                time.sleep(3)
            else:
                print(f"  ✗ Échec définitif {doc_path.name}: {exc}")
    return False


def _auto_ingest_samples(rag: RAGPipeline) -> None:
    sample_dir = Path("sample_docs")
    if not sample_dir.exists():
        return

    # Récupère les titres déjà indexés pour ne pas réingérer ce qui existe
    existing = {doc["source"] for doc in rag.vector_store.list_documents()}

    failed = []
    for doc_path in sorted(sample_dir.iterdir()):
        if doc_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if doc_path.name in existing:
            continue
        if not _ingest_one(rag, doc_path):
            failed.append(doc_path)

    if failed:
        print(f"  ⚠ {len(failed)} document(s) non ingéré(s) définitivement : {[p.name for p in failed]}")


def get_rag() -> RAGPipeline:
    if not _rag_ready.is_set():
        _rag_ready.wait()
    return _rag  # type: ignore[return-value]


@app.on_event("startup")
async def startup_event() -> None:
    # Initialise les tables PostgreSQL
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(init_vector_db)
    print("→ Initialisation du pipeline RAG…")
    asyncio.create_task(asyncio.to_thread(_init_rag))


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


# ─── Logging du stream ────────────────────────────────────────────────────

async def _stream_with_logging(
    gen: AsyncGenerator, conversation_id: str, question: str
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
                    await asyncio.to_thread(
                        log_message,
                        conversation_id, question, "".join(full_text), sources,
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

    # Sauvegarde temporaire pour traitement
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

        # Upload vers Supabase Storage
        storage_path = f"{file_id}{ext}"
        stored = await _storage_upload(storage_path, content)
        if not stored:
            storage_path = None  # pas de storage configuré, on continue quand même

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
        # Supprime le fichier temporaire local (il est dans Supabase Storage)
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


@app.post("/api/admin/unanswered/{unanswered_id}/resolve")
async def admin_resolve(unanswered_id: str, body: ResolveRequest, _: None = Depends(verify_admin)):
    if not body.admin_response.strip():
        raise HTTPException(status_code=400, detail="La réponse ne peut pas être vide.")

    question = await asyncio.to_thread(
        resolve_unanswered, unanswered_id, body.admin_response
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable.")

    # Ajoute le Q&A à la base vectorielle
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


# ─── Frontend statique ────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

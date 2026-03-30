"""
API FastAPI — Assistant RH RAG
Endpoints:
  POST /api/chat                          → SSE streaming (question → réponse)
  GET  /api/documents                     → liste des documents indexés
  POST /api/documents/upload              → ingestion d'un nouveau document
  DELETE /api/documents/{id}              → suppression d'un document
  GET  /api/health                        → statut de l'API
  GET  /api/admin/stats                   → statistiques (admin)
  GET  /api/admin/conversations           → conversations paginées (admin)
  GET  /api/admin/conversations/{id}/messages → détail conversation (admin)
  GET  /api/admin/unanswered              → questions sans réponse (admin)
  POST /api/admin/unanswered/{id}/resolve → résoudre + ajouter au RAG (admin)
"""
import asyncio
import json
import os
import threading
import uuid
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

# ─── App ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Assistant RH RAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

# ─── Singleton RAG ────────────────────────────────────────────────────────

_rag: RAGPipeline | None = None
_rag_lock = threading.Lock()
_rag_ready = threading.Event()


def _init_rag() -> None:
    global _rag
    with _rag_lock:
        if _rag is not None:
            return
        _rag = RAGPipeline()
        _auto_ingest_samples(_rag)
    _rag_ready.set()


def _auto_ingest_samples(rag: RAGPipeline) -> None:
    if rag.vector_store.count() > 0:
        return
    sample_dir = Path("sample_docs")
    if not sample_dir.exists():
        return
    for doc_path in sorted(sample_dir.iterdir()):
        if doc_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                chunks, metadatas, doc_id = process_document(str(doc_path))
                if not chunks:
                    continue
                embeddings = rag.embed_texts_sync(chunks)
                rag.vector_store.add_documents(chunks, embeddings, metadatas, doc_id)
                print(f"  ✓ Ingéré : {doc_path.name} ({len(chunks)} chunks)")
            except Exception as exc:
                print(f"  ✗ Erreur ingestion {doc_path.name}: {exc}")


def get_rag() -> RAGPipeline:
    if not _rag_ready.is_set():
        _rag_ready.wait()
    return _rag  # type: ignore[return-value]


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    print("→ Chargement du modèle d'embedding (peut prendre 1-2 min au 1er démarrage)…")
    asyncio.get_event_loop().run_in_executor(None, _init_rag)


# ─── Modèles Pydantic ─────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []
    conversation_id: str = ""


class ResolveRequest(BaseModel):
    admin_response: str


# ─── Helpers ──────────────────────────────────────────────────────────────

async def _stream_with_logging(
    gen: AsyncGenerator,
    conversation_id: str,
    question: str,
) -> AsyncGenerator:
    """Passe le stream en transparence et logue l'échange à la fin."""
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
                        conversation_id,
                        question,
                        "".join(full_text),
                        sources,
                    )
            except Exception:
                pass
        yield chunk


# ─── Routes API ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    ready = _rag_ready.is_set()
    return {
        "status": "ready" if ready else "initializing",
        "model": f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3.2')}",
        "documents": get_rag().vector_store.count() if ready else 0,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    rag = await asyncio.to_thread(get_rag)
    history = [{"role": m.role, "content": m.content} for m in request.history]
    raw_stream = rag.generate_stream(request.question, history)
    stream = _stream_with_logging(raw_stream, request.conversation_id, request.question)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/documents")
async def list_documents():
    rag = await asyncio.to_thread(get_rag)
    docs = rag.vector_store.list_documents()
    return {"documents": docs, "total": len(docs)}


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(default="Général"),
    title: str = Form(default=""),
):
    ext = Path(file.filename or "file.txt").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté : {ext}. Formats acceptés : PDF, DOCX, TXT, MD.",
        )

    file_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{file_id}{ext}"

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    try:
        chunks, metadatas, doc_id = process_document(
            str(file_path), title=title or None, category=category,
        )
        if not chunks:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="Document vide ou illisible.")

        rag = await asyncio.to_thread(get_rag)
        embeddings = await rag.embed_texts(chunks)
        rag.vector_store.add_documents(chunks, embeddings, metadatas, doc_id)

        return {
            "status": "success",
            "doc_id": doc_id,
            "title": metadatas[0]["title"],
            "chunks": len(chunks),
        }
    except HTTPException:
        raise
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    rag = await asyncio.to_thread(get_rag)
    deleted = rag.vector_store.delete_document(doc_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    return {"status": "deleted", "doc_id": doc_id, "chunks_removed": deleted}


# ─── Routes Admin Analytics ───────────────────────────────────────────────

@app.get("/api/admin/stats")
async def admin_stats():
    return await asyncio.to_thread(get_stats)


@app.get("/api/admin/conversations")
async def admin_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await asyncio.to_thread(get_conversations, page, page_size)


@app.get("/api/admin/conversations/{conversation_id}/messages")
async def admin_conversation_messages(conversation_id: str):
    return await asyncio.to_thread(get_conversation_messages, conversation_id)


@app.get("/api/admin/unanswered")
async def admin_unanswered(
    status: str = Query(default="pending"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if status not in ("pending", "resolved"):
        raise HTTPException(status_code=400, detail="status doit être 'pending' ou 'resolved'")
    return await asyncio.to_thread(get_unanswered, status, page, page_size)


@app.post("/api/admin/unanswered/{unanswered_id}/resolve")
async def admin_resolve(unanswered_id: str, body: ResolveRequest):
    if not body.admin_response.strip():
        raise HTTPException(status_code=400, detail="La réponse ne peut pas être vide.")

    question = await asyncio.to_thread(
        resolve_unanswered, unanswered_id, body.admin_response
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable.")

    # Ajouter le Q&A à la base RAG pour les prochaines recherches
    rag = await asyncio.to_thread(get_rag)
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


# ─── Frontend statique (doit être APRÈS toutes les routes /api) ───────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

"""
API FastAPI — Assistant RH RAG
Endpoints:
  POST /api/chat                      → SSE streaming (question → réponse)
  GET  /api/documents                 → liste des documents indexés
  POST /api/documents/upload          → ingestion d'un nouveau document
  DELETE /api/documents/{id}          → suppression d'un document
  GET  /api/health                    → statut de l'API
  POST /api/admin/sync-notion         → resync manuel depuis Notion
  GET  /api/admin/notion-status       → vérifie la connexion Notion
"""
import asyncio
import os
import threading
import uuid
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .document_processor import process_document
from .notion_loader import check_notion_connection, load_notion_pages
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

NOTION_SYNC_INTERVAL = 2 * 60 * 60  # 2 heures en secondes

# ─── Singleton RAG (initialisation paresseuse + thread-safe) ──────────────

_rag: RAGPipeline | None = None
_rag_lock = threading.Lock()
_rag_ready = threading.Event()
_sync_lock = threading.Lock()  # empêche les syncs concurrentes


def _init_rag() -> None:
    """Initialise le pipeline RAG et ingère les docs Notion si la DB est vide."""
    global _rag
    with _rag_lock:
        if _rag is not None:
            return
        _rag = RAGPipeline()
        _auto_ingest_notion(_rag)
    _rag_ready.set()


def _auto_ingest_notion(rag: RAGPipeline) -> None:
    """Ingère les pages Notion si la base vectorielle est vide."""
    if rag.vector_store.count() > 0:
        return
    print("→ Base vectorielle vide — synchronisation depuis Notion…")
    _sync_notion_blocking(rag)


def _sync_notion_blocking(rag: RAGPipeline) -> dict:
    """
    Resynchronise les documents Notion dans le vector store (thread-safe).
    Supprime les anciens chunks Notion puis réingère toutes les pages.
    Retourne un dict de résultat.
    """
    with _sync_lock:
        try:
            pages = load_notion_pages()
        except ValueError as exc:
            print(f"  ✗ Notion non configuré : {exc}")
            return {"status": "error", "detail": str(exc)}

        # Supprime les anciens chunks Notion
        deleted = rag.vector_store.delete_by_source_type("notion")
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
    """Retourne le singleton RAG (bloque jusqu'à initialisation complète)."""
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
    print("→ Chargement du modèle d'embedding (peut prendre 1-2 min au 1er démarrage)…")
    asyncio.get_event_loop().run_in_executor(None, _init_rag)
    asyncio.create_task(_notion_sync_loop())


# ─── Modèles Pydantic ──────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []


# ─── Routes API ────────────────────────────────────────────────────────────

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

    return StreamingResponse(
        rag.generate_stream(request.question, history),
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
            str(file_path),
            title=title or None,
            category=category,
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


# ─── Admin Notion ──────────────────────────────────────────────────────────

@app.get("/api/admin/notion-status")
async def notion_status():
    """Vérifie la connexion à Notion et retourne le statut."""
    result = await asyncio.to_thread(check_notion_connection)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.post("/api/admin/sync-notion")
async def sync_notion():
    """Déclenche un resync immédiat depuis Notion (endpoint admin)."""
    rag = await asyncio.to_thread(get_rag)
    result = await asyncio.to_thread(_sync_notion_blocking, rag)
    if result["status"] == "error":
        raise HTTPException(status_code=503, detail=result["detail"])
    return result


# ─── Frontend statique (doit être APRÈS toutes les routes /api) ────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

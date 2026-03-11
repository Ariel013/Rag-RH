"""
API FastAPI — Assistant RH RAG
Endpoints:
  POST /api/chat           → SSE streaming (question → réponse Claude)
  GET  /api/documents      → liste des documents indexés
  POST /api/documents/upload → ingestion d'un nouveau document
  DELETE /api/documents/{id} → suppression d'un document
  GET  /api/health         → statut de l'API
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

# ─── Singleton RAG (initialisation paresseuse + thread-safe) ──────────────

_rag: RAGPipeline | None = None
_rag_lock = threading.Lock()
_rag_ready = threading.Event()


def _init_rag() -> None:
    """Initialise le pipeline RAG et ingère les docs samples si la DB est vide."""
    global _rag
    with _rag_lock:
        if _rag is not None:
            return
        _rag = RAGPipeline()
        _auto_ingest_samples(_rag)
    _rag_ready.set()


def _auto_ingest_samples(rag: RAGPipeline) -> None:
    """Ingère les documents sample_docs/ si la base vectorielle est vide."""
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
    """Retourne le singleton RAG (bloque jusqu'à initialisation complète)."""
    if not _rag_ready.is_set():
        _rag_ready.wait()
    return _rag  # type: ignore[return-value]


@app.on_event("startup")
async def startup_event() -> None:
    print("→ Chargement du modèle d'embedding (peut prendre 1-2 min au 1er démarrage)…")
    asyncio.get_event_loop().run_in_executor(None, _init_rag)


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


# ─── Frontend statique (doit être APRÈS toutes les routes /api) ────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

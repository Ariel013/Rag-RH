"""
Couche d'abstraction sur ChromaDB (stockage persistant local).
"""
from pathlib import Path
import chromadb

CHROMA_PATH = Path("data/chroma_db")


class VectorStore:
    def __init__(self):
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self._col = self._client.get_or_create_collection(
            name="hr_documents",
            metadata={"hnsw:space": "cosine"},
        )

    # ─── Écriture ──────────────────────────────────────────────────────────

    def add_documents(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        doc_id: str,
    ) -> None:
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        self._col.add(
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

    def delete_document(self, doc_id: str) -> int:
        results = self._col.get(where={"doc_id": doc_id})
        if results["ids"]:
            self._col.delete(ids=results["ids"])
            return len(results["ids"])
        return 0

    # ─── Lecture ───────────────────────────────────────────────────────────

    def search(
        self, query_embedding: list[float], n_results: int = 5
    ) -> list[dict]:
        total = self._col.count()
        if total == 0:
            return []
        n = min(n_results, total)
        results = self._col.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append(
                {
                    "content": doc,
                    "metadata": meta,
                    "score": round(1.0 - dist, 4),  # cosine similarity
                }
            )
        return output

    def list_documents(self) -> list[dict]:
        results = self._col.get(include=["metadatas"])
        seen: dict[str, dict] = {}
        for meta in results["metadatas"]:
            doc_id = meta.get("doc_id", "unknown")
            if doc_id not in seen:
                seen[doc_id] = {
                    "id": doc_id,
                    "title": meta.get("title", "Sans titre"),
                    "source": meta.get("source", ""),
                    "category": meta.get("category", "Général"),
                }
        return list(seen.values())

    def count(self) -> int:
        return self._col.count()

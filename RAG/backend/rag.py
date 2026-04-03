"""
Pipeline RAG — embeddings locaux via fastembed (ONNX), LLM via API OpenAI-compatible.

Embeddings  : fastembed (ONNX local, ~90 MB, aucun appel réseau)
Vector DB   : PostgreSQL + pgvector (Supabase)
LLM         : Groq / Ollama via API OpenAI-compatible
"""
import asyncio
import json
import os
from typing import AsyncGenerator

from fastembed import TextEmbedding
from openai import AsyncOpenAI

from .vector_store import VectorStore

EMBED_MODEL         = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RELEVANCE_THRESHOLD = 0.4

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")


class RAGPipeline:
    def __init__(self):
        self.vector_store = VectorStore()
        print(f"  Embeddings : fastembed ONNX local ({EMBED_MODEL})")
        self._embedder = TextEmbedding(EMBED_MODEL)
        self._llm = AsyncOpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=os.getenv("GROQ_API_KEY", "ollama"),
        )
        print(f"  LLM        : {OLLAMA_MODEL} — {OLLAMA_BASE_URL}")

    # ── Embeddings (fastembed ONNX local) ─────────────────────────────────

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        return [emb.tolist() for emb in self._embedder.embed(texts)]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode_sync, texts)

    def embed_texts_sync(self, texts: list[str]) -> list[list[float]]:
        return self._encode_sync(texts)

    # ── Recherche ──────────────────────────────────────────────────────────

    async def search(self, query: str, n_results: int = 8) -> list[dict]:
        embs    = await self.embed_texts([query])
        results = self.vector_store.search(embs[0], n_results)
        return [r for r in results if r["score"] >= RELEVANCE_THRESHOLD]

    # ── Génération streaming ───────────────────────────────────────────────

    async def generate_stream(
        self,
        question: str,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:

        # 1. Contexte documentaire
        results = await self.search(question, n_results=8)

        if results:
            context = "\n\n---\n\n".join(
                f"[{r['metadata'].get('title', 'Document')}]\n{r['content']}"
                for r in results[:6]
            )
            sources, seen = [], set()
            for r in results[:5]:
                t = r["metadata"].get("title", "Document")
                if t not in seen:
                    seen.add(t)
                    sources.append({
                        "title":    t,
                        "category": r["metadata"].get("category", "Général"),
                    })
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        else:
            context = "Aucun document pertinent trouvé dans la base de connaissances."

        # 2. Prompt système
        system = f"""Tu es l'assistant RH virtuel du groupe AEIG (African Education and Innovation Group). \
Tu aides les collaborateurs du groupe à trouver des informations sur l'organisation, \
les personnes, les procédures internes, les congés, la paie et la vie au sein du groupe.

RÈGLES ABSOLUES — respecte-les sans exception :

1. Réponds TOUJOURS en français.
2. INTERDIT ABSOLU — ces formulations sont BANNIES de tes réponses, ne les utilise JAMAIS :
   "selon le contexte", "selon le contexte documentaire", "d'après le contexte",
   "d'après les documents", "le contexte indique", "le contexte mentionne",
   "d'après les informations fournies", "les informations disponibles indiquent",
   "il est mentionné que", "il ressort du contexte", "d'après ce que j'ai",
   "les documents précisent", "selon les informations".
   Tu parles en ton propre nom, comme un assistant qui connaît l'entreprise.
3. Sois BREF et PRÉCIS : 2 à 4 phrases maximum, ou une courte liste à puces (•).
4. La section ci-dessous contient les données officielles d'AEIG. Utilise-les directement.
5. Si tu ne trouves pas la réponse : dis "Je ne dispose pas de cette information." \
   puis invite l'utilisateur à contacter la RH : jb.koffi@aeig.africa (Bénin) \
   ou cynthia.toure@aeig.africa (CI).
6. N'invente jamais d'informations.
7. Après ta réponse, pose UNE seule question courte si c'est pertinent.

--- Données AEIG ---
{context}
---"""

        # 3. Historique (max 3 échanges)
        messages = [{"role": "system", "content": system}]
        messages += list((history or []))[-6:]
        messages.append({"role": "user", "content": question})

        # 4. Streaming LLM
        try:
            stream = await self._llm.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                max_tokens=512,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text_delta', 'content': delta.content})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            msg = str(e)
            if "connection" in msg.lower() or "refused" in msg.lower():
                msg = (
                    "Impossible de joindre le LLM. "
                    "Vérifiez la variable OLLAMA_BASE_URL et que le service est démarré."
                )
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

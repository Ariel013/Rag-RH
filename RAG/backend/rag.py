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
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.40"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")

# Mots courts qui signalent une question de suivi (pas de sens seuls pour la recherche)
_FOLLOWUP_TRIGGERS = {
    "plus", "suite", "tout", "d'autre", "encore", "davantage",
    "complet", "complète", "entier", "entière", "reste", "restant",
    "more", "else", "all", "continue",
}


def _build_search_query(question: str, history: list[dict]) -> str:
    """
    Enrichit la requête de recherche avec le contexte de l'historique quand la
    question est trop courte ou vague pour trouver des résultats seule.
    Ex : "Dis moi-en plus" → reprend les derniers échanges pour construire une requête utile.
    """
    words = [w.strip("?.,!:;\"'").lower() for w in question.split()]
    is_vague = len(words) <= 6 or any(w in _FOLLOWUP_TRIGGERS for w in words)

    if not is_vague or not history:
        return question

    # Récupérer les 2 dernières questions de l'utilisateur
    recent = [m["content"] for m in history if m["role"] == "user"][-2:]
    if not recent:
        return question

    # Concaténer contexte + question actuelle comme requête enrichie
    return " ".join(recent) + " " + question


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

    async def search(
        self, query: str, n_results: int = 10, history: list[dict] | None = None
    ) -> list[dict]:
        effective_query = _build_search_query(query, history or [])
        embs    = await self.embed_texts([effective_query])
        results = self.vector_store.search(embs[0], n_results)
        filtered = [r for r in results if r["score"] >= RELEVANCE_THRESHOLD]
        return filtered[:5]

    # ── Génération streaming ───────────────────────────────────────────────

    async def generate_stream(
        self,
        question: str,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:

        # 1. Contexte documentaire (recherche enrichie avec l'historique)
        results = await self.search(question, history=history)

        if results:
            context_parts = []
            total_chars   = 0
            for r in results:
                content = r["content"]
                # Pas de troncature du contenu : le LLM doit recevoir les listes complètes
                part = f"[{r['metadata'].get('title', 'Document')}]\n{content}"
                if total_chars + len(part) > 6000:
                    break
                context_parts.append(part)
                total_chars += len(part)
            context = "\n\n---\n\n".join(context_parts)

            sources, seen = [], set()
            for r in results:
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
        system = f"""Tu es l'assistant RH virtuel du groupe AEIG (African Education and Innovation Group).
Tu aides les collaborateurs à trouver des informations sur l'organisation, les procédures internes, les congés, la paie et la vie au sein du groupe.

RÈGLES STRICTES — à respecter sans exception :

1. Réponds TOUJOURS en français.
2. Tu ne peux répondre QU'avec les informations présentes dans la section "Données AEIG" ci-dessous.
   Si l'information n'y figure PAS EXPLICITEMENT, réponds : "Je ne dispose pas de cette information."
   puis invite à contacter la RH : christelle.houssou@epitech.eu (Bénin) ou christelle.bohoussou@epitech.eu (CI).
3. INTERDIT ABSOLU d'inventer, déduire, estimer ou compléter une information manquante.
4. INTERDIT d'utiliser tes connaissances générales sur d'autres entreprises ou pratiques RH génériques.
5. Ces formulations sont BANNIES : "selon le contexte", "d'après les documents", "le contexte indique",
   "d'après les informations fournies", "il est mentionné que", "les documents précisent".
6. Si les données contiennent une liste (questions, étapes, points…), retranscris-la INTÉGRALEMENT.
   Ne résume pas, ne tronque pas : liste chaque point, même s'il y en a beaucoup.
7. Sois précis et complet. Pas de limite artificielle au nombre de points listés.
8. Pose UNE seule question courte de suivi si c'est pertinent.

--- Données AEIG ---
{context}
---"""

        # 3. Historique (max 4 échanges = 8 messages)
        messages = [{"role": "system", "content": system}]
        messages += list((history or []))[-8:]
        messages.append({"role": "user", "content": question})

        # 4. Streaming LLM
        try:
            stream = await self._llm.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                max_tokens=1024,
                temperature=0.1,
                top_p=0.9,
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

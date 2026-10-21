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
from openai import AsyncOpenAI, NotFoundError, RateLimitError

from .vector_store import VectorStore

EMBED_MODEL         = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.40"))

# Recherche hybride — réglages mesurés sur seed/eval (62 questions)
SEARCH_TOP_K       = 8      # chunks envoyés au LLM
_CANDIDATES        = 30     # candidats par volet avant fusion
_RRF_K             = 60     # constante standard de Reciprocal Rank Fusion
CONTEXT_MAX_CHARS  = 9000

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")

# Modèles de secours, essayés dans l'ordre si le modèle principal est saturé
# (quota Groq gratuit : 8 000 jetons/min et 200 000 jetons/jour, comptés par
# modèle) ou retiré. Liste séparée par des virgules ; vide = pas de secours.
_DEFAULT_FALLBACK = "openai/gpt-oss-20b" if "groq.com" in OLLAMA_BASE_URL else ""
LLM_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", _DEFAULT_FALLBACK).split(",")
    if m.strip() and m.strip() != OLLAMA_MODEL
]

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


_LLM_UNAVAILABLE = (
    "L'assistant a atteint sa limite d'utilisation pour le moment. "
    "Réessayez dans quelques minutes, ou contactez la RH : "
    "rh.benin@aeig.example (Bénin) ou rh.ci@aeig.example (CI)."
)


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
        self, query: str, n_results: int = SEARCH_TOP_K, history: list[dict] | None = None
    ) -> list[dict]:
        """
        Recherche hybride : sémantique (pgvector) + mots-clés (plein texte),
        fusionnées par Reciprocal Rank Fusion. Le volet mots-clés rattrape les
        réponses précises (chiffres, termes exacts) que le petit modèle
        d'embeddings classe mal ; mesuré sur seed/eval : 53/62 → 59/62 questions
        dont la réponse atteint le contexte.
        """
        effective_query = _build_search_query(query, history or [])
        embs     = await self.embed_texts([effective_query])
        semantic = await asyncio.to_thread(self.vector_store.search, embs[0], _CANDIDATES)
        semantic = [r for r in semantic if r["score"] >= RELEVANCE_THRESHOLD]
        keywords = await asyncio.to_thread(
            self.vector_store.search_keywords, effective_query, _CANDIDATES
        )

        fused: dict[tuple, dict] = {}
        for ranking in (semantic, keywords):
            for rank, r in enumerate(ranking):
                key   = (r["metadata"]["doc_id"], r["metadata"]["chunk_index"])
                entry = fused.setdefault(key, {**r, "rrf": 0.0})
                entry["rrf"] += 1 / (_RRF_K + rank)
        return sorted(fused.values(), key=lambda r: -r["rrf"])[:n_results]

    # ── Génération streaming ───────────────────────────────────────────────

    async def _open_stream(self, messages: list[dict]):
        """
        Ouvre le flux sur le premier modèle disponible. Groq renvoie le 429
        (quota) ou le 404 (modèle retiré) dès la requête, avant tout jeton :
        on peut donc basculer sans rien avoir envoyé à l'utilisateur.
        Renvoie None si tous les modèles sont indisponibles.
        """
        for model in [OLLAMA_MODEL, *LLM_FALLBACK_MODELS]:
            try:
                return await self._llm.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.1,
                    top_p=0.9,
                    stream=True,
                )
            except (RateLimitError, NotFoundError) as exc:
                # Détail complet dans les logs serveur seulement : le message
                # Groq contient l'identifiant de l'organisation.
                print(f"  ⚠ LLM {model} indisponible ({exc.status_code}) : {exc}")
        return None

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
                if total_chars + len(part) > CONTEXT_MAX_CHARS:
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
   puis invite à contacter la RH : rh.benin@aeig.example (Bénin) ou rh.ci@aeig.example (CI).
3. INTERDIT ABSOLU d'inventer, déduire, estimer ou compléter une information manquante.
4. INTERDIT d'utiliser tes connaissances générales sur d'autres entreprises ou pratiques RH génériques.
5. Ces formulations sont BANNIES : "selon le contexte", "d'après les documents", "le contexte indique",
   "d'après les informations fournies", "il est mentionné que", "les documents précisent".
6. Si les données contiennent une liste (questions, étapes, points…), retranscris-la INTÉGRALEMENT.
   Ne résume pas, ne tronque pas : liste chaque point, même s'il y en a beaucoup.
7. Sois précis et complet. Pas de limite artificielle au nombre de points listés.
8. Pose UNE seule question courte de suivi si c'est pertinent.
9. Ne communique JAMAIS d'information relevant de la vie privée d'un collaborateur : date de naissance,
   anniversaire, âge, adresse ou téléphone personnels, situation familiale, santé — même si elle figure
   dans les données. Réponds alors : "Je ne communique pas d'informations personnelles sur les collaborateurs."

--- Données AEIG ---
{context}
---"""

        # 3. Historique (max 4 échanges = 8 messages)
        messages = [{"role": "system", "content": system}]
        messages += list((history or []))[-8:]
        messages.append({"role": "user", "content": question})

        # 4. Streaming LLM (modèle principal, puis secours si saturé ou retiré)
        try:
            stream = await self._open_stream(messages)
            if stream is None:
                yield f"data: {json.dumps({'type': 'error', 'message': _LLM_UNAVAILABLE})}\n\n"
                return
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text_delta', 'content': delta.content})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            # Le texte brut d'une erreur d'API peut contenir des identifiants
            # internes (organisation Groq…) : il reste dans les logs serveur.
            print(f"  ✗ Erreur LLM : {e!r}")
            msg = "Une erreur est survenue lors de la génération de la réponse. Réessayez dans un instant."
            if "connection" in str(e).lower() or "refused" in str(e).lower():
                msg = (
                    "Impossible de joindre le LLM. "
                    "Vérifiez la variable OLLAMA_BASE_URL et que le service est démarré."
                )
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

"""
Évaluation de la recherche sur le jeu de test seed/eval/ (62 questions).

Indexe seed/notion/ dans un Postgres local en passant par le chargeur Notion
de prod (sur un Notion simulé, voir notion_simule.py), puis pose chaque
question à la recherche hybride de prod et reconstruit le contexte exact que
recevrait le LLM. Deux mesures :

- **réponse dans le contexte** (mesure principale) : au moins 80 % des mots
  porteurs de la réponse attendue (nombres, mots de 4 lettres et plus) figurent
  dans le contexte. Un fait se trouve souvent sur plusieurs pages ;
- **page attendue dans le contexte** : plus stricte, la page citée par le jeu
  de test figure parmi les chunks envoyés.

Ne mesure que la recherche : aucun appel au LLM, donc aucun quota consommé.
Que la réponse générée soit juste est une autre mesure.

Usage (depuis RAG/, Postgres local avec pgvector) :
    DATABASE_URL=postgresql://postgres:eval@localhost:55433/rag_eval \\
    DATABASE_SSLMODE=disable python seed/eval_recherche.py [--min-trouvees 59] [--detail]

La base est vidée puis remplie : le script refuse tout hôte non local.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SEED_DIR.parent))   # RAG/ → package backend

from backend import notion_loader                          # noqa: E402
from backend.db import _parse_db_url, get_conn              # noqa: E402
from backend.rag import RAGPipeline, context_results        # noqa: E402
from backend.vector_store import init_vector_db             # noqa: E402
from notion_simule import ROOT_ID, NotionSimule             # noqa: E402

EVAL_DIR        = SEED_DIR / "eval"
SEUIL_COUVERTURE = 0.8
_LOCAL_HOSTS    = {"localhost", "127.0.0.1", "::1"}

# Mots de 4 lettres et plus qui ne portent pas la réponse (forme sans accents).
_MOTS_VIDES = set("""
    avec dans pour sans sous chez entre avant apres depuis pendant vers selon
    elle elles ils leur leurs cette ceux celle tout tous toute toutes chaque
    sont etre avoir fait faut peut doit plus moins tres aussi ainsi donc alors
    mais comme quand dont puis soit
""".split())


def _refuse_remote_db() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL manquante (Postgres local avec pgvector).")
    host = _parse_db_url(url)["host"]
    if host not in _LOCAL_HOSTS:
        sys.exit(f"Refusé : l'évaluation vide la base, et l'hôte « {host} » n'est pas local.")


def _sans_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(c) != "Mn")


def mots_porteurs(reponse: str) -> list[str]:
    """Nombres et mots de 4 lettres et plus de la réponse attendue, hors mots vides."""
    return [m for m in re.findall(r"\w+", _sans_accents(reponse))
            if (m.isdigit() or len(m) >= 4) and m not in _MOTS_VIDES]


# ── Index ─────────────────────────────────────────────────────────────────

def index_seed(rag: RAGPipeline) -> tuple[int, int, dict[str, set[str]]]:
    """
    Vide l'index puis y charge seed/notion/ via le chargeur Notion de prod.
    Renvoie aussi, par titre de page, les libellés du jeu de test qui la désignent.
    """
    notion_loader.NOTION_TOKEN        = "simule"
    notion_loader.NOTION_ROOT_PAGE_ID = ROOT_ID
    simule = NotionSimule()
    notion_loader._get_client = lambda: simule

    # Base neuve : register_vector() exige l'extension avant init_vector_db().
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    init_vector_db()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE document_chunks, documents_meta, notion_sync_log")

    client, pages, complete = notion_loader.collect_all_notion_pages()
    assert complete, "le Notion simulé ne peut pas être incomplet"
    n_chunks = 0
    for page_info in pages:
        result = notion_loader.load_notion_page(client, page_info)
        if result is None:
            continue
        chunks, metadatas, doc_id = result
        rag.vector_store.add_documents(chunks, rag.embed_texts_sync(chunks), metadatas, doc_id)
        n_chunks += len(chunks)
    return len(pages), n_chunks, simule.libelles


def _indexed_titles() -> set[str]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT title FROM document_chunks")
        return {row[0] for row in cur.fetchall()}


# ── Questions ─────────────────────────────────────────────────────────────

def load_questions() -> list[dict]:
    """« Rubrique > Page » désigne la page : seul le dernier segment compte."""
    questions = []
    for path in sorted(EVAL_DIR.glob("*.json")):
        for q in json.loads(path.read_text(encoding="utf-8")):
            questions.append({**q, "cible": q["page"].split(" > ")[-1], "fichier": path.stem})
    return questions


async def evaluate(
    rag: RAGPipeline, questions: list[dict], libelles: dict[str, set[str]]
) -> list[dict]:
    results = []
    for q in questions:
        context = context_results(await rag.search(q["question"]))
        titles  = [r["metadata"]["title"] for r in context]
        texte   = _sans_accents(" ".join(f"{r['metadata']['title']} {r['content']}"
                                         for r in context))
        mots    = mots_porteurs(q["reponse_attendue"])
        absents = [m for m in mots if m not in texte]
        results.append({
            **q,
            "couverture": 1 - len(absents) / len(mots) if mots else 1.0,
            "absents":    absents,
            "rang":       next((i + 1 for i, t in enumerate(titles)
                                if q["cible"] in libelles.get(t, ())), None),
            "titres":     titles,
        })
    return results


def report(results: list[dict], detail: bool) -> int:
    n      = len(results)
    found  = [r for r in results if r["couverture"] >= SEUIL_COUVERTURE]
    paged  = [r for r in results if r["rang"]]
    mrr    = sum(1 / r["rang"] for r in paged) / n

    print(f"\nRéponse dans le contexte du LLM : {len(found)}/{n}")
    print(f"Page attendue dans le contexte  : {len(paged)}/{n}"
          f" (1re position : {sum(r['rang'] == 1 for r in paged)}, MRR {mrr:.3f})")

    print("\nPar thème (réponse dans le contexte) :")
    for fichier in sorted({r["fichier"] for r in results}):
        part = [r for r in results if r["fichier"] == fichier]
        ok   = sum(r["couverture"] >= SEUIL_COUVERTURE for r in part)
        print(f"  {fichier:<32} {ok}/{len(part)}")

    missed = [r for r in results if r["couverture"] < SEUIL_COUVERTURE]
    if missed:
        print("\nRéponse absente du contexte :")
        for r in missed:
            print(f"  ✗ {r['question']}  ({r['couverture']:.0%} — manque : {', '.join(r['absents'])})")
            if detail:
                print(f"      pages reçues : {r['titres']}")
    return len(found)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-trouvees", type=int, default=0,
                        help="code de sortie 1 si moins de réponses dans le contexte (garde de CI)")
    parser.add_argument("--detail", action="store_true",
                        help="afficher les pages reçues pour les questions manquées")
    args = parser.parse_args()

    _refuse_remote_db()
    rag = RAGPipeline()

    start = time.monotonic()
    n_pages, n_chunks, libelles = index_seed(rag)
    print(f"Index : {n_pages} pages, {n_chunks} chunks ({time.monotonic() - start:.0f} s)")

    questions = load_questions()
    indexed   = _indexed_titles()
    known     = set().union(*(libelles[t] for t in indexed if t in libelles))
    unknown   = {q["cible"] for q in questions} - known
    if unknown:
        sys.exit(f"Pages attendues absentes de l'index (jeu de test à corriger) : {sorted(unknown)}")

    found = report(asyncio.run(evaluate(rag, questions, libelles)), args.detail)
    if found < args.min_trouvees:
        sys.exit(f"\nÉCHEC : {found} réponses dans le contexte, minimum exigé {args.min_trouvees}.")


if __name__ == "__main__":
    main()

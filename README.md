---
title: Assistant RH RAG
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Assistant RH — RAG évalué, en production

[![Évaluation de la recherche](https://github.com/Ariel013/Rag-RH/actions/workflows/eval-recherche.yml/badge.svg)](https://github.com/Ariel013/Rag-RH/actions/workflows/eval-recherche.yml)

Assistant RH conversationnel pour **AEIG**, un groupe fictif de formation et
d'innovation (Bénin, Côte d'Ivoire, 53 collaborateurs). Les collaborateurs
posent leurs questions — congés, paie, procédures, organigramme — et
l'assistant répond **uniquement** à partir de la base documentaire de
l'entreprise, synchronisée depuis Notion. Sinon, il le dit et renvoie vers la RH.

**▶ Démo : [arieldev13-assistant-rh-rag.hf.space](https://arieldev13-assistant-rh-rag.hf.space)**
— essayez « Combien de jours de congé pour mon mariage ? » ou « Quel est le per
diem pour une mission en Côte d'Ivoire ? ». Après une période sans visite, le
Space peut mettre un moment à se réveiller.

![Conversation avec l'assistant RH : « Combien de jours de congé ai-je pour mon mariage ? », réponse « 4 jours »](https://raw.githubusercontent.com/Ariel013/Rag-RH/assets/captures/capture-chat.png)

## Ce qui est mesuré

| Mesure | Résultat | Comment |
| --- | --- | --- |
| Réponse attendue présente dans le contexte du LLM | **60 / 62** | `RAG/seed/eval_recherche.py`, rejoué en CI sur chaque PR |
| Page attendue présente dans le contexte | 50 / 62 (MRR 0,554) | même script, mesure plus stricte |
| Effet de la recherche hybride (ADR 0002) | 53 → 59 / 62 | banc local, 2026-10-22 |
| Effet du filtre des mots trop fréquents | 58 → 60 / 62 | `eval_recherche.py`, 2026-11-02 |
| Réponses justes en prod, relues à la main | ≈ 56 / 57 | 2026-10-22 ; 5 questions bloquées par le quota |

Le jeu de test (`RAG/seed/eval/`) compte 62 questions écrites avec leur réponse
attendue, sur cinq thèmes : groupe, organisation, politique RH, procédures, vie
interne. L'évaluation de la recherche n'appelle pas le LLM : elle tourne en CI
sans secret et sans quota. **La justesse des réponses générées n'est pas encore
mesurée automatiquement.**

## Architecture

```mermaid
flowchart LR
    N[Notion<br/>source principale] -- sync incrémental 2 h --> L[Chargeur Notion<br/>blocs, tables, OCR<br/>filtre vie privée]
    U[Upload admin<br/>PDF, DOCX, MD] --> C
    L --> C[Découpage<br/>paragraphes + overlap]
    C --> E[Embeddings locaux<br/>fastembed ONNX, 384 d]
    E --> P[(PostgreSQL<br/>pgvector + plein texte)]
    Q[Question] --> H{Recherche hybride}
    P --> H
    H -- sens : HNSW cosinus --> F[Fusion RRF<br/>8 chunks, 9 000 car.]
    H -- mots-clés : tsvector french --> F
    F --> G[LLM Groq<br/>gpt-oss-120b, secours 20b]
    G -- streaming SSE --> R[Réponse]
```

| Couche | Choix |
| --- | --- |
| API | FastAPI (Python 3.11), streaming SSE, limite de débit 10 req/min |
| Recherche | PostgreSQL + pgvector (Supabase) : HNSW cosinus + plein texte `french`, fusion RRF |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX, local, sans GPU) |
| LLM | API compatible OpenAI : Groq `openai/gpt-oss-120b`, bascule sur `gpt-oss-20b` en cas de quota ou de retrait |
| Sources | Notion (sync incrémental, OCR des images) + uploads admin |
| Front | HTML/JS sans framework, Tailwind |
| Déploiement | Docker → Hugging Face Spaces, déployé par GitHub Actions |

## Choix techniques

- **Recherche hybride plutôt qu'un modèle d'embeddings plus gros**
  ([ADR 0002](docs/decisions/0002-recherche-hybride-plutot-qu-un-modele-d-embeddings-plus-gros.md)).
  Le petit modèle multilingue classe mal les passages précis : chiffres, termes
  exacts, tableaux. Un volet plein texte fusionné par RRF les rattrape, sans
  changer l'image Docker ni réindexer : 53 → 59 questions sur 62. Le volet plein
  texte ignore ensuite les mots présents dans plus de la moitié des passages
  (« AEIG ») : sans pondération par la rareté, ils noyaient le mot utile de la
  question. Mesuré : 58 → 60.
- **Un jeu de test avant tout réglage.** Le seuil de pertinence avait été réglé
  plusieurs fois « à l'impression ». Désormais, toute modification de la recherche
  se mesure sur les 62 questions, et la CI bloque une régression.
- **Évaluer le vrai code, pas une copie.** L'évaluation fait tourner le chargeur
  Notion de prod sur un Notion simulé à partir des fichiers du dépôt. L'index
  obtenu est identique à celui de la prod (170 pages, 299 chunks), sans réseau.
- **Embeddings locaux** (ONNX, ~90 Mo) : calculés sur le serveur, sans coût par
  requête ni GPU — compatible avec l'offre CPU gratuite de Hugging Face.
- **Vie privée à l'import**
  ([ADR 0001](docs/decisions/0001-jeu-de-donnees-fictif-versionne-et-filtre-vie-privee.md)) :
  les lignes personnelles (naissance, domicile, situation familiale…) sont
  retirées avant l'indexation. Ce qui n'est pas dans l'index ne peut pas fuiter
  par le chat, quelle que soit la question.
- **Réponses ancrées** : le prompt système interdit de répondre hors contexte et
  refuse les questions sur la vie privée d'un collaborateur.

## Côté admin

Accès protégé :

- upload et suppression de documents ;
- synchronisation Notion manuelle (incrémentale ou complète) ;
- statistiques et classement des questions par thème ;
- questions restées sans réponse : la réponse de la RH est réinjectée dans la
  base comme une FAQ.

## Incidents traités en production

Le projet a été repris après trois mois de panne silencieuse. Chaque cause a été
corrigée à la racine et documentée (voir `JOURNAL.md`) :

- **toutes les bases Notion lues à vide pendant des mois** : une dépendance non
  figée avait retiré une méthode, et l'erreur était avalée. La version est
  désormais figée et toute erreur est journalisée ;
- **un rate-limit Notion pouvait effacer des pages de l'index** : une page non
  lue était prise pour une page supprimée. Les relances respectent
  `Retry-After`, et rien n'est supprimé si la liste des pages est incomplète ;
- **modèles LLM retirés par le fournisseur, quota quotidien épuisé** : bascule
  automatique vers un modèle de secours, sans exposer l'erreur brute de l'API ;
- **tables accessibles avec la clé publique Supabase** : RLS activé ;
- **base mise en pause sans alerte** : le garde-fou passait par l'application,
  qui dépend de la base. Il vise maintenant la base directement.

## Évaluer et lancer en local

```bash
# Évaluation de la recherche (Docker + Python 3.11 ou plus)
docker run -d --name rag-eval-pg -e POSTGRES_PASSWORD=eval -e POSTGRES_DB=rag_eval \
  -p 127.0.0.1:55433:5432 pgvector/pgvector:pg16
cd RAG && pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:eval@localhost:55433/rag_eval \
  DATABASE_SSLMODE=disable python seed/eval_recherche.py --detail

# Application (variables : RAG/.env.example)
./start.sh
```

Variables principales :

| Variable | Rôle |
| --- | --- |
| `DATABASE_URL` | PostgreSQL avec pgvector (Supabase en prod) |
| `NOTION_TOKEN` / `NOTION_ROOT_PAGE_ID` | Intégration Notion |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `GROQ_API_KEY` | LLM compatible OpenAI (Groq en prod, Ollama en local) |
| `LLM_FALLBACK_MODELS` | Modèles de secours sur quota ou retrait |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_TOKEN` | Accès admin |

## Limites connues

- Quota gratuit du LLM : environ 140 questions par jour, modèle de secours compris.
- Un seul compte admin, avec un jeton statique.
- Pas de tests unitaires ni de migrations de schéma versionnées : ce sont les
  prochaines étapes.
- Le déploiement n'attend pas encore le résultat de l'évaluation.

## Données

Entreprise, personnes et chiffres sont **entièrement fictifs**, versionnés dans
`RAG/seed/` et publiés dans Notion par un script. Les adresses utilisent le
domaine réservé `aeig.example`.

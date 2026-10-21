# Assistant RH RAG — AEIG

Document de référence du projet. Objectif : permettre à **n'importe quelle instance de Claude** (nouvelle conversation, nouvel environnement) de reprendre ce projet sans historique préalable. À tenir à jour à chaque changement structurant — voir la section Journal des décisions (§10).

## 1. Vue d'ensemble

Chatbot RH basé sur un pipeline **RAG (Retrieval-Augmented Generation)** pour le groupe fictif **AEIG (African Education and Innovation Group)**. Les collaborateurs posent des questions RH (congés, paie, procédures, organigramme…) et l'assistant répond **uniquement** à partir d'une base de connaissances vectorielle — jamais à partir des connaissances générales du LLM.

- **Statut** : déployé et fonctionnel (pas un simple POC). DB Supabase en prod, Notion connecté en prod, LLM Groq en prod.
- **Données** : le contenu métier est **fictif** et **versionné dans le dépôt** (`RAG/seed/`, voir §11 et ADR 0001). Il est publié dans un Notion personnel par `RAG/seed/push_notion.py`. Jusqu'au 2026-10-21, la prod lisait le Notion d'un ancien employeur (données réelles) : ce Notion n'est plus utilisé et ne doit plus l'être.
- **Finalité confirmée** : malgré le contenu fictif, **le projet est destiné à devenir la base d'un vrai déploiement** (vraie organisation, vraies données RH). Conséquence directe : la dette technique listée en §8 doit être traitée comme une vraie priorité, pas comme un confort optionnel — voir §9 pour l'ordre de traitement retenu.
- **Langue** : le code, les commentaires et les réponses de l'assistant sont en français.

## 2. Stack technique

| Couche | Techno | Détail |
| --- | --- | --- |
| Backend | FastAPI (Python 3.11) | API REST + streaming SSE |
| Vector DB | PostgreSQL + pgvector | Hébergé sur Supabase, remplace un ancien ChromaDB |
| Embeddings | fastembed (ONNX local) | `paraphrase-multilingual-MiniLM-L12-v2`, 384 dim, aucun appel réseau, ~90 Mo |
| Recherche | Hybride | pgvector (sens) + plein texte Postgres `french` (mots-clés), fusion RRF — voir ADR 0002 |
| LLM | API OpenAI-compatible | Groq en prod (`openai/gpt-oss-120b`, réglé par la **variable** HF `OLLAMA_MODEL`) ; Ollama local possible en dev. Les modèles llama de Groq ont été retirés le 2026-08-16 |
| Source de vérité documentaire | Notion API | Complétée par des uploads admin ponctuels — voir §5 |
| Stockage fichiers uploadés | Supabase Storage | Bucket `uploads` |
| Frontend | HTML/CSS/JS vanilla + Tailwind (CDN) | Pas de framework, pas de build step |
| Déploiement | Docker → Hugging Face Spaces | Auto-déployé via GitHub Actions à chaque push sur `main` |
| Rate limiting | slowapi | 10 req/min sur `/api/chat` |
| OCR (images Notion) | Vision LLM Groq (`GROQ_VISION_MODEL`, défaut `qwen/qwen3.6-27b`) puis fallback Tesseract | fra+eng — prise en charge des images par ce modèle non vérifiée |

## 3. Structure du repo

```text
Rag-RH/
├── Dockerfile                      # Build HF Spaces, port 7860
├── .github/workflows/deploy-hf.yml # git push --force vers le Space HF à chaque push main
├── README.md                       # Carte HF Space (front-matter YAML obligatoire)
└── RAG/
    ├── .env / .env.example         # Config — .env est gitignored (secrets réels dedans)
    ├── requirements.txt
    ├── start.sh                    # Lancement local (vérifie Ollama si local, sinon skip)
    ├── backend/
    │   ├── main.py                 # FastAPI app, routes, lifecycle, sync Notion en tâche de fond
    │   ├── rag.py                  # RAGPipeline : embeddings, recherche, prompt système, streaming LLM
    │   ├── vector_store.py         # Requêtes SQL pgvector (chunks, sync log Notion, CRUD documents)
    │   ├── db.py                   # Pool de connexions psycopg2 partagé (parsing manuel de DATABASE_URL)
    │   ├── notion_loader.py        # Parcours récursif Notion → texte → chunks
    │   ├── document_processor.py   # Extraction PDF/DOCX/TXT/MD + chunking par paragraphes avec overlap
    │   ├── topics.py               # Classification sémantique des questions (10 topics par défaut)
    │   └── analytics.py            # Logging conversations/messages, détection "sans réponse"
    ├── frontend/
    │   ├── index.html              # SPA unique, classes Tailwind, dark mode via classe `.dark`
    │   ├── css/styles.css
    │   └── js/
    │       ├── config.js           # Constantes + state global partagé (STORAGE_KEY, ADMIN_TOKEN_SK, `state`)
    │       ├── init.js             # Bootstrap au chargement
    │       ├── chat.js             # Envoi message, consommation du stream SSE
    │       ├── auth.js             # Login admin (token stocké en sessionStorage)
    │       ├── documents.js        # Upload/suppression documents (onglet admin)
    │       ├── conversations.js    # Historique des conversations (onglet admin)
    │       ├── analytics.js        # Stats, topics, questions sans réponse (onglet admin)
    │       ├── storage.js          # Persistance locale des conversations (localStorage, expiry 24h)
    │       ├── ui.js               # Helpers DOM génériques (sidebar, toggle, etc.)
    │       └── utils.js
    ├── seed/                        # Jeu de données fictif versionné (voir seed/README.md)
    │   ├── referentiel.md          # Faits de référence (53 collaborateurs, règles RH chiffrées…) — non publié
    │   ├── notion/                 # 81 pages + 4 bases, en Markdown/JSON, publiées dans Notion
    │   ├── eval/                   # 62 questions avec réponse attendue (mesure de la qualité)
    │   └── push_notion.py          # Publie seed/notion/ dans Notion (--dry-run, --reset)
    └── uploads/                     # Fichiers temporaires (gitignored, supprimés après traitement)
```

## 4. Nomenclature / conventions

- **`doc_id`** : UUID identifiant un document logique (un fichier uploadé, ou une page Notion). Un document produit plusieurs lignes dans `document_chunks` (une par chunk).
- **`chunk_index`** : position du chunk dans son document d'origine.
- **`source`** : champ texte qui préfixe l'origine — `notion:<page_id>` pour les pages Notion, ou le nom de fichier original pour un upload. C'est ce préfixe (`source LIKE 'notion:%'`) qui sert de filtre pour retrouver/purger les documents Notion (`delete_notion_documents`).
- **`notion_page_id`** vs **`doc_id`** : un `notion_page_id` est stable (identité Notion), un `doc_id` change à chaque ré-ingestion de la page (nouvel UUID généré à chaque `load_notion_page`). La table `notion_sync_log` fait le pont entre les deux pour permettre le sync incrémental et la suppression ciblée.
- **`topic_id`** : soit un des 10 topics par défaut (préfixe `topic_*`, ex. `topic_conges`), soit un topic custom créé par un admin (préfixe `topic_custom_<hex8>`).
- **`conversation_id`** : généré côté frontend (localStorage), transmis au backend à chaque message pour regrouper les tours dans `conversations`/`messages`.
- **Préfixes de commit Git** : `[ADD]`, `[FIX]`, `[REFACTOR]`, `[UPDATE]` — convention observée dans l'historique, à conserver.
- **Tables PostgreSQL** : `document_chunks`, `documents_meta`, `notion_sync_log`, `topics`, `conversations`, `messages`, `unanswered`. Toutes créées par `init_vector_db()` / `init_db()` en `CREATE TABLE IF NOT EXISTS` — pas de système de migration formel (voir §8).

## 5. Fonctionnalités

### Côté utilisateur (chat)

- Chat streaming (SSE) avec citations des sources (titre + catégorie du document).
- Enrichissement de requête pour les questions de suivi vagues (« dis-m'en plus », « et le reste ? ») en réinjectant les 2 derniers messages utilisateur — voir `_build_search_query` dans `rag.py`.
- Historique de conversation limité aux 4 derniers échanges (8 messages) envoyés au LLM.
- Persistance locale des conversations (24h, localStorage) côté frontend.
- Garde-fous stricts dans le prompt système : réponse uniquement à partir du contexte fourni, formulations d'attribution interdites (« selon le contexte », etc.), retranscription intégrale des listes, sinon réponse standard invitant à contacter la RH ; refus des questions sur la vie privée d'un collaborateur (règle 9).
- **Recherche hybride** (ADR 0002) : 30 candidats sémantiques (pgvector, filtrés par `RELEVANCE_THRESHOLD`) + 30 candidats plein texte (`tsv`, config `french`), fusionnés par RRF ; 8 chunks, 9000 caractères max envoyés au LLM.
- Le chat est disponible **dès le chargement du modèle**, pendant le sync Notion de démarrage (qui peut durer longtemps : OCR, rate-limit Notion).

### Côté admin (protégé par token)

- Login admin (email/password → token statique `ADMIN_TOKEN`, stocké en sessionStorage côté front).
- Upload/suppression de documents (PDF, DOCX, TXT, MD) avec stockage Supabase Storage optionnel.
- Sync Notion manuelle (incrémentale ou full) via bouton dédié.
- Dashboard analytics : nb questions, conversations, questions sans réponse, répartition par topic.
- Gestion des questions « sans réponse » : liste, suppression, résolution (la réponse admin est réinjectée dans le RAG comme une FAQ).
- Gestion des topics : liste, création de topic custom, réassignation manuelle du topic d'un message.

### Notion vs upload admin — rôle confirmé

Les deux sources **cohabitent normalement**, ce n'est pas un mode dégradé :

- **Notion** : contenu structuré et vivant (organigramme, procédures, culture d'entreprise…) — la source principale, synchronisée automatiquement.
- **Upload admin** : documents ponctuels qui ne vivent pas naturellement dans Notion (contrats types, annonces, PDF officiels…) — ajout complémentaire, pas un dépannage exceptionnel.

Implication pratique : ne jamais supposer que retirer le endpoint d'upload ou le simplifier serait sans risque — c'est un canal d'alimentation à part entière à conserver et à durcir au même titre que le sync Notion.

### Sync Notion (mécanisme central)

1. **Full sync** (bouton admin uniquement) : purge tous les chunks `source LIKE 'notion:%'` et le `notion_sync_log`, puis réingère tout. **Annulé avant purge** si la liste des pages est incomplète (erreur passagère Notion). Au démarrage, c'est un sync **incrémental**.
2. **Sync incrémental** (tâche de fond toutes les `NOTION_SYNC_INTERVAL_SECONDS`, défaut 7200s = 2h, + bouton manuel) : compare `last_edited_time` de chaque page Notion au log ; ne réingère que les pages nouvelles/modifiées ; supprime les chunks des pages retirées de Notion.
3. Parcours récursif de tous les blocs (colonnes, toggles, tables, callouts…), OCR sur les images embarquées, gestion des databases Notion (limite 200 lignes), retry jusqu'à 6 fois sur 429/5xx/réseau en respectant `Retry-After`. **Aucune suppression** lors d'un sync incrémental dont la liste est incomplète : une page non lue n'est pas une page supprimée.
5. **Vie privée** (ADR 0001) : à l'import, les pages dont le titre commence par « Anniversaire » sont exclues, et les lignes mentionnant date de naissance, anniversaire, téléphone/adresse personnels, domicile ou situation familiale sont retirées (`_PRIVATE_LINE_RE` dans `notion_loader.py`).
6. `notion-client` est **figé à 2.5.0** : à partir de 2.6.0, `databases.query` disparaît (API Notion 2025-09-03, `data_sources`). Une version non figée a vidé silencieusement toutes les bases Notion pendant des mois.
4. Le endpoint `/api/admin/notion-status` vérifie la connexion (token + accès à la page racine).

## 6. Modèle de données (PostgreSQL)

- `document_chunks(id, doc_id, title, source, category, chunk_index, content, embedding vector(384), tsv tsvector)` + index HNSW cosinus + index GIN sur `tsv` (colonne générée : `to_tsvector('french', title || content)`).
- **RLS activé sans policy** sur les 7 tables (`enable_rls` dans `db.py`) : la clé anon Supabase n'y a aucun accès ; le backend, propriétaire, n'est pas concerné.
- `documents_meta(doc_id, storage_path, uploaded_at)` — pour retrouver/supprimer le fichier dans Supabase Storage.
- `notion_sync_log(notion_page_id, doc_id, last_edited, synced_at)` — état du sync incrémental.
- `topics(id, name, embedding vector(384), is_custom)`.
- `conversations(id, started_at, message_count)`, `messages(id, conversation_id, question, answer, sources, had_answer, asked_at, topic_id)`.
- `unanswered(id, message_id, question, status, admin_response, resolved_at)`.

Détection « sans réponse » : recherche de phrases-clés françaises dans la réponse générée (`_NO_ANSWER` dans `analytics.py`) — fragile par nature (dépend du wording exact du prompt système, voir §8).

## 7. Configuration / variables d'environnement

Voir `RAG/.env.example` pour la liste complète. Points clés :

- `DATABASE_URL` : Postgres Supabase (parsing manuel dans `db.py` pour supporter les mots de passe à caractères spéciaux).
- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` : Storage des uploads (optionnel — si absent, upload fonctionne mais sans persistance du fichier source).
- `NOTION_TOKEN` / `NOTION_ROOT_PAGE_ID` : intégration Notion, source de vérité principale.
- `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `GROQ_API_KEY` : LLM (compatible OpenAI). Le nom `OLLAMA_*` est trompeur une fois pointé vers Groq — hérité de l'implémentation initiale 100% locale. Sur HF, `OLLAMA_MODEL` est une **variable** (pas un secret) : un secret et une variable de même nom bloquent le Space (`Collision on variables and secrets names`). Groq retire régulièrement des modèles : vérifier https://console.groq.com/docs/deprecations en cas d'erreur `model_not_found`.
- `LLM_FALLBACK_MODELS` : modèles de secours (liste séparée par des virgules), essayés si le modèle principal renvoie 429 (quota) ou 404 (retiré). Défaut `openai/gpt-oss-20b` quand l'URL pointe vers Groq. **Quota Groq gratuit, par modèle** : 8 000 jetons/min, 200 000 jetons/jour — environ 70 questions/jour à ~2 700 jetons. Ne pas rejouer les 62 questions de `seed/eval/` contre la prod : cela consomme la moitié du quota du jour.
- `GROQ_VISION_MODEL` : modèle vision pour l'OCR des images Notion (défaut `qwen/qwen3.6-27b` — absent de la page des limites Groq au 2026-10-22, qui liste `qwen/qwen3.8-27b` : à vérifier).
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_TOKEN` : auth admin — **un seul compte admin possible actuellement**.
- `ALLOWED_ORIGINS` : CORS, `*` par défaut.
- `RELEVANCE_THRESHOLD` : seuil de similarité cosinus pour filtrer les résultats de recherche (0–1). Le `.env` réel de prod ne définit pas cette clé, donc le défaut du code (`rag.py`, 0.40) s'applique — confirmé comme l'état voulu, pas un oubli.
- `NOTION_SYNC_INTERVAL_SECONDS` : intervalle du sync auto (défaut 7200).

## 8. Divergences / dette technique connues

- **`RELEVANCE_THRESHOLD`** : la valeur par défaut dans `rag.py` (0.40) diffère de celle documentée dans `.env.example` (0.45) ; l'historique Git montre plusieurs ajustements (0.15 → 0.5 → 0.45/0.40) — c'est un paramètre sensible qui a été tuné empiriquement, à ne pas changer sans tester sur des questions réelles.
- **Pas de système de migration DB** : les `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS` (ex. `topic_id` sur `messages`) servent de migration ad hoc. Fonctionne mais fragile si un changement de schéma nécessite une transformation de données existantes. À professionnaliser avant un vrai déploiement (voir §9).
- **Détection "sans réponse"** basée sur du pattern-matching de phrases dans `analytics.py::_NO_ANSWER` — couplée au wording exact du prompt système dans `rag.py`. Si le prompt change, penser à mettre à jour la liste (et vice-versa).
- **Un seul compte admin** (`ADMIN_EMAIL`/`ADMIN_PASSWORD` fixes dans l'env, token statique unique) — pas de multi-utilisateur, pas d'expiration de token. À revoir avant un vrai déploiement (voir §9).
- **Déploiement par force-push** : `deploy-hf.yml` fait un `git push hf main --force` à chaque push sur `main` — pas de rollback automatique, pas d'environnement de staging, pas de CI de test avant déploiement.
- **Aucun test automatisé** dans le repo actuellement — confirmé comme une lacune à combler prochainement, pas un choix définitif (voir §9). `RAG/seed/eval/` (62 questions) en est la première brique.
- **Dépendances non figées** (sauf `notion-client`) : un rebuild peut installer une version incompatible, comme notion-client 2.6 l'a fait. fastembed est passé en 0.9 le 2026-10-07. À figer.
- **API Notion ancienne** (2022-06-28, via notion-client 2.5.0) : migration vers `data_sources` à faire.
- **Keep-alive Supabase cassé** : `.github/workflows/keep-alive.yml` passe par l'appli (donc échoue quand la base dort) et GitHub l'a désactivé pour inactivité. Le projet Supabase (gratuit) s'est mis en pause en juillet 2026 sans que personne ne le voie. Remplacement prévu : cron externe interrogeant Supabase directement (voir `A-FAIRE.md`).

## 9. Roadmap — dette à combler en priorité

Le projet vise un vrai déploiement futur (§1), donc l'ordre de traitement retenu pour la dette technique est :

1. **Tests automatisés** (priorité immédiate) — au minimum : chunking (`document_processor.py`), sync Notion incrémental (cas nouveau/modifié/supprimé/inchangé dans `_sync_notion_blocking`), routes API critiques (`/api/chat`, `/api/documents/upload`, auth admin).
2. **Migrations DB formelles** — remplacer les `CREATE TABLE IF NOT EXISTS` ad hoc par un outil de migration (Alembic ou équivalent SQL versionné) avant tout changement de schéma qui toucherait des données existantes.
3. **Multi-admin / auth plus robuste** — sortir du couple email/password + token statique unique (ex. plusieurs comptes, expiration de token, rôles).
4. **Autres pistes à évaluer avec l'utilisateur le moment venu** : multi-langue au-delà du FR, multi-tenant (plusieurs organisations sur la même instance), export des conversations, notifications RH sur questions sans réponse. Ne pas anticiper l'architecture pour ces points tant qu'ils ne sont pas confirmés comme prioritaires.

## 10. Journal des décisions

*(résumé condensé de l'historique Git et des échanges avec l'utilisateur — à compléter à chaque changement structurant, ne pas dupliquer le détail déjà dans `git log`)*

- **pgvector remplace ChromaDB** : passage à PostgreSQL/Supabase pour la persistance vectorielle (pas de volume à gérer sur HF Spaces).
- **Notion devient la source de vérité principale**, en complément des uploads admin qui restent un canal légitime pour les documents ponctuels (confirmé le 2026-07-23 — ce n'est pas un mode dégradé, voir §5).
- **fastembed (ONNX) remplace sentence-transformers/PyTorch** pour les embeddings — plus léger, pas de dépendance GPU/PyTorch, adapté à HF Spaces CPU.
- **OCR images Notion** : vision LLM Groq en premier choix (llama-4-scout jusqu'à son retrait le 2026-07-17, puis modèle configurable), fallback Tesseract si pas de clé Groq ou échec.
- **Seuil de pertinence** ajusté plusieurs fois (0.15 → 0.5 → ~0.40/0.45) après tests empiriques sur la qualité des réponses.
- **Auth admin** ajoutée pour protéger l'upload/suppression de documents et les analytics (avant : accès libre).
- **Frontend éclaté** en 9 fichiers JS/CSS modulaires (avant : un seul `index.html` monolithique).
- **2026-10-21 — reprise après panne** : Supabase en pause, modèles Groq retirés, bases Notion lues à vide, Notion d'un ancien employeur. Remplacé par un jeu de données fictif versionné (ADR 0001), recherche hybride (ADR 0002), RLS, filtre vie privée. Détail dans `JOURNAL.md`.
- **2026-07-23** : confirmation que le projet vise un vrai déploiement futur (pas juste un portfolio figé) ; README.md corrigé pour refléter la stack réelle (Groq llama-3.3-70b-versatile, pgvector) au lieu de l'ancienne description (llama-3.1-8b-instant, ChromaDB) ; tests automatisés actés comme prochaine priorité.

## 11. Comment reprendre ce projet en pratique

- Lire `JOURNAL.md` en premier, puis ce fichier.
- Vérifier `RAG/.env` (local, gitignored) pour l'état de config réel — ne jamais commiter de secret.
- Lancer en local avec `RAG/start.sh` (installe les dépendances, vérifie Ollama si config locale, démarre uvicorn avec reload).
- Le déploiement prod se fait uniquement via push sur `main` (GitHub Actions → force-push vers le Space HF `arieldev13/assistant-rh-rag`). **Un push sur `main` déploie en prod immédiatement** — pas de CI de test avant.
- Pour enrichir la base de connaissances : modifier `RAG/seed/notion/` puis republier (`python seed/push_notion.py --reset`, depuis `RAG/`), ou upload via l'onglet admin du frontend — les deux canaux sont légitimes (§5). Une modification faite **seulement dans Notion** sera perdue au prochain `--reset`.
- Mesurer la qualité : `RAG/seed/eval/` contient 62 questions avec la réponse attendue ; toute modification de la recherche ou du prompt se mesure dessus avant d'être poussée.

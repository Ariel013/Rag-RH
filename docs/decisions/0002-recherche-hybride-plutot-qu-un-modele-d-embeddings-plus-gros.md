# 0002 — Recherche hybride (sens + plein texte) plutôt qu'un modèle d'embeddings plus gros

**Statut** : adopté (2026-10-22)

## Contexte

Sur les 62 questions de `RAG/seed/eval/`, le passage qui contient la réponse
n'atteignait le contexte du LLM que pour 53 questions. Le modèle répondait alors
« je ne dispose pas de cette information », alors que le contenu était bien indexé.

Le modèle d'embeddings (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions)
est petit, et classe mal les passages précis : chiffres, termes exacts, tableaux
aplatis.

Leviers mesurés sur un banc local, avec les 299 chunks réels :

| Variante | Réponse dans le contexte |
| --- | --- |
| Actuel (seuil 0,40, 5 chunks) | 53/62 |
| Titre de la page dans le texte embarqué | 52/62 |
| Chunks de 600 caractères | 49/62 |
| Seuil 0,30 | 55/62 |
| Seuil 0,30, 8 chunks | 59/62 |
| Hybride, 8 chunks (banc, BM25) | 62/62 |
| **Hybride, implémentation Postgres réelle** | **59/62** |

Un modèle plus gros (mpnet 768 dimensions, e5-large 1024 dimensions) obligeait à :

- changer le type de colonne `vector(384)` ;
- tout réindexer ;
- alourdir l'image HF (1 à 2,2 Go de modèle).

Et ce, sans gain mesuré à ce stade.

## Décision

La recherche combine deux volets :

- **sémantique** : pgvector, 30 candidats filtrés par `RELEVANCE_THRESHOLD` ;
- **plein texte** : colonne générée `tsv`, `to_tsvector('french', titre + contenu)`,
  index GIN, 30 candidats en « OU » des mots de la question.

Les deux classements sont fusionnés par Reciprocal Rank Fusion (k = 60). Le LLM
reçoit 8 chunks, avec un plafond de 9 000 caractères.

## Pourquoi

- C'est le seul levier qui atteint ce score **sans migration de schéma ni
  réindexation** : la colonne `tsv` est générée et s'ajoute au démarrage.
- Le plein texte rattrape ce que l'embedding rate (chiffres, noms propres,
  termes exacts), et l'embedding garde les reformulations.
- Plus de chunks dans le contexte coûte peu avec `gpt-oss-120b`.

## Conséquences

- Une question hors sujet reçoit désormais du contexte, via les mots-clés.
  C'est la règle 2 du prompt (« uniquement les données fournies ») qui doit faire
  refuser. À surveiller.
- Le score de 59/62 est probablement optimiste : les questions ont été écrites
  avec le contenu. Les vraies questions des utilisateurs restent la référence.
- Le changement de modèle d'embeddings reste ouvert. S'il redevient nécessaire,
  il passe par une vraie migration (roadmap §9, point 2).
- `RELEVANCE_THRESHOLD` ne filtre plus que le volet sémantique.

## Complément (2026-11-02) — mots trop fréquents ignorés par le volet plein texte

`ts_rank_cd` ne pondère pas les mots par leur rareté. Dans « Quelle part de la
mutuelle est prise en charge par AEIG ? », « AEIG » (présent dans 79 % des
chunks) classait en tête les chunks qui le répètent, et la page « Mutuelle
santé » finissait 15e du volet plein texte, hors du contexte. Le volet plein
texte ignore désormais les mots présents dans plus de 50 % des chunks
(`MAX_KEYWORD_DOC_FREQ`), sauf si tous les mots de la question le sont.

Mesuré avec `seed/eval_recherche.py` : 58 → 60/62 réponses dans le contexte,
48 → 50/62 pages attendues, MRR 0,519 → 0,554. Le résultat est le même entre 30 %
et 50 % (60/62), et 59/62 à 70 % : 50 % est retenu, le moins agressif du palier.

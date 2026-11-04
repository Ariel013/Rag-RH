# 🧭 Journal de bord — Assistant RH RAG (AEIG)

> **Nouvelle session : LIS CE FICHIER EN PREMIER**, puis `CLAUDE.md`. Tu sauras
> où on en est, quoi faire ensuite et quoi éviter — sans relire tout le code.
>
> **Discipline** :
> 1. Au **démarrage** : lire les trois sections ci-dessous, puis agir / proposer.
> 2. En **fin de session** : mettre à jour « État & prochaine action », ajouter
>    une entrée au journal des sessions, consigner toute erreur en « Leçons ».
> 3. Convertir les dates relatives en absolues. Rester concis.

Carte des documents :

- `CLAUDE.md` — les règles du projet, et quel document lire pour quel sujet.
- `A-FAIRE.md` — les actions manuelles hors code.
- `docs/decisions/` — les ADR (pourquoi tel choix).
- `RAG/seed/README.md` — le jeu de données fictif et sa publication.

---

## 📍 État actuel & prochaine action

*(Mis à jour le 2026-11-05.)*

- **En prod** : PR #1 `feat/vitrine-recruteur` fusionnée (`9ef85a8`), déployée
  le 2026-11-04 sur le Space HF `arieldev13/assistant-rh-rag`
  (`openai/gpt-oss-120b`, Notion personnel alimenté par `RAG/seed/`) :
  évaluation de la recherche en CI (verte), README vitrine, filtre des mots trop
  fréquents, passages consultés sous les réponses.
- **Vérifié en prod le 2026-11-05** (une question) : « Quelle part de la
  mutuelle… » → « 70 % de la cotisation », 8 sources avec leurs extraits,
  `had_answer` vrai. Le 2026-10-22, c'était la seule question sans réponse.
- **Qualité mesurée** (`seed/eval_recherche.py`, sans LLM) : réponse dans le
  contexte 60/62, page attendue 50/62, MRR 0,554. Échecs restants : « malade ce
  matin » (limite de la mesure, formes de mots) et la date du séminaire 2026.
  En prod, le 2026-10-22 : ≈ 56/57 bonnes réponses relues à la main.
- **Branches** : `dev` (52 commits de retard) et `feature_v2` sont abandonnées ;
  les branches de travail partent de `main`. `assets` (orpheline) héberge les
  images du README hors du déploiement HF.
- **Prochaine action** : refaire la capture du README avec un passage déplié.
  Ensuite, dans l'ordre : démo résistante au quota, admin en démo, widget
  intégrable (bulle de chat), citations [n] par le LLM, juge LLM.
- **Reste ouvert du 2026-10-22** : vérifier dans les logs HF qu'une saturation
  bascule bien vers `openai/gpt-oss-20b`. Offre Groq gratuite maintenue
  (≈ 140 questions/jour avec le secours), à revoir avant tout vrai déploiement.

## 📓 Journal des sessions

### 2026-11-02 / 04 — Vitrine pour recruteurs

Objectif : rendre le projet lisible par un recruteur (postes IA/ML et
backend/full stack). Fait, sur `feat/vitrine-recruteur` :

1. **Évaluation de la recherche rejouable** : le chargeur Notion de prod tourne
   sur un Notion simulé depuis `seed/notion/` (170 pages, 299 chunks, comme la
   prod), puis les 62 questions passent par la recherche de prod. CI sur chaque
   PR, minimum 60. Le contrôle a trouvé un titre faux dans le jeu de test.
2. **README refait** : démo, chiffres avec leur source, architecture, choix,
   incidents. Capture sur la branche `assets` (un lien d'image glissé dans un
   brouillon d'issue GitHub renvoie 404 aux visiteurs).
3. **Mots trop fréquents ignorés par le plein texte** : « AEIG » (79 % des
   chunks) noyait « mutuelle ». 58 → 60/62 (ADR 0002 complété).
4. **Passages consultés** sous les réponses, dépliables ; l'affichage des
   sources avait disparu à la refonte de mars. Masqués sous « sans réponse ».


### 2026-10-21 / 22 — Reprise après trois mois de panne

Symptôme de départ : « le projet ne tourne plus ». Pannes trouvées, de la plus
visible à la plus cachée :

1. **Supabase en pause** (plan gratuit) depuis l'été. Le Space HF plantait au
   démarrage (`tenant/user … not found`). Le keep-alive GitHub n'avait jamais
   réussi un seul ping : il passait par l'appli, qui a besoin de la base. GitHub
   l'a ensuite désactivé pour inactivité. Projet repris après avoir libéré une
   place gratuite.
2. **Modèles Groq retirés** : `llama-3.1-8b-instant` et `llama-3.3-70b-versatile`
   le 2026-08-16, `llama-4-scout` (OCR) le 2026-07-17. Le chat renvoyait
   `model_not_found` à chaque question. Le modèle de chat passe à
   `openai/gpt-oss-120b`, et l'OCR à un modèle configurable.
3. **Toutes les bases Notion lues à « 0 entrées »** depuis la sortie de
   notion-client 2.6.0 (octobre 2025). La dépendance n'était pas figée, et l'erreur
   était avalée en silence. La version est figée à 2.5.0, et les erreurs sont
   désormais journalisées.
4. **Rate-limit Notion pouvant effacer des pages** : une page non lue était
   traitée comme supprimée. Les relances respectent maintenant `Retry-After`, et
   aucune suppression n'est faite si la liste est incomplète.
5. **Chat bloqué pendant tout le sync de démarrage** : il est maintenant prêt dès
   le chargement du modèle.
6. **Données réelles d'un ancien employeur** (People Book de 81 personnes) dans
   un Space public. Elles sont remplacées par un jeu fictif versionné, avec un
   filtre vie privée (ADR 0001). Les e-mails réels de RH présents dans le prompt
   et l'interface sont remplacés.
7. **Tables Supabase accessibles avec la clé anon** : le RLS est activé, sans
   policy.
8. **Réponses « je ne dispose pas » alors que le contenu était indexé** : la
   recherche est devenue hybride (ADR 0002), mesurée sur 62 questions.
9. **Quota Groq épuisé par les tests** (200 000 jetons/jour pour le modèle) :
   des modèles de secours sont essayés en cas de 429 ou de 404, et le texte brut
   des erreurs d'API (qui contient l'identifiant d'organisation Groq) n'est plus
   envoyé à l'utilisateur.

Restent ouverts :

- les actions de `A-FAIRE.md` ;
- figer les autres dépendances ;
- migrer vers l'API Notion `data_sources` ;
- vérifier que `qwen/qwen3.6-27b` lit bien les images ;
- comprendre pourquoi Tesseract renvoie souvent exactement 23 caractères (bruit
  probable) ;
- la roadmap §9 de `CLAUDE.md` : tests, migrations, multi-admin.

## 🎓 Leçons apprises

### Un keep-alive qui passe par l'appli ne protège pas la base dont l'appli dépend (2026-10-21)
Symptôme : le keep-alive Supabase a échoué à chaque passage, du premier au
dernier, et Supabase s'est mis en pause quand même. Personne ne l'a remarqué.
Cause : le ping visait `/api/health`, qui a besoin de la base. Dès que la base
dort, le ping échoue sans rien réveiller.
Règle : un garde-fou de disponibilité vise directement la ressource à garder en
vie. Ses échecs doivent arriver à quelqu'un, sinon le garde-fou est muet.

### Une dépendance non figée, plus une erreur avalée, donne une panne invisible (2026-10-21)
Symptôme : toutes les bases Notion affichaient « 0 entrées », sans aucune erreur
dans les logs, pendant des mois.
Cause : `notion-client>=2.2.1` a installé la 2.6, qui n'a plus `databases.query`,
et `except Exception: break` cachait l'erreur.
Règle : figer les dépendances d'une image reconstruite à chaque déploiement, et
ne jamais avaler une exception sans la journaliser.

### Une liste partielle ne doit jamais servir à supprimer (2026-10-21)
Symptôme : sous rate-limit Notion, des sous-arbres entiers n'étaient pas lus.
Cause : le sync incrémental supprime ce qui manque à la liste. Or une page non
lue manquait aussi.
Règle : une suppression déduite d'une absence exige une liste dont on sait
qu'elle est complète.

### Un réglage de recherche se mesure sur un jeu de questions, pas à l'impression (2026-10-22)
Symptôme : « il n'apprend pas bien ». Le seuil de pertinence avait été réglé
plusieurs fois à la main (0,15 → 0,5 → 0,40).
Cause : sans jeu de questions de référence, chaque réglage était une impression.
Le banc local a montré que le seuil n'était pas le bon levier.
Règle : avant de toucher la recherche ou le prompt, mesurer sur `seed/eval/`.

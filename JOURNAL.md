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

*(Mis à jour le 2026-10-22.)*

- **En prod** : commit `4e4d038` (recherche hybride) sur le Space HF
  `arieldev13/assistant-rh-rag`. Le modèle est `openai/gpt-oss-120b`, et le Notion
  est le Notion personnel alimenté par `RAG/seed/` (170 pages, 299 chunks).
- **Qualité mesurée** :
  - Avant la recherche hybride, en prod, sur les 62 questions de `seed/eval/` :
    environ 49 bonnes réponses, 12 « je ne dispose pas », 1 fausse.
  - Banc local (code de prod sur un Postgres local) : la réponse atteint le
    contexte pour 59 questions sur 62, contre 53 avant.
  - Le score en prod après la recherche hybride reste à mesurer.
- **Branches** : `main` alignée avec `origin/main`.
- **Prochaine action** : relancer les 62 questions sur la prod, et vérifier
  qu'une question hors sujet est bien refusée (ADR 0002, conséquences). Critère :
  au plus 3 « je ne dispose pas », aucun hors sujet répondu.

## 📓 Journal des sessions

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

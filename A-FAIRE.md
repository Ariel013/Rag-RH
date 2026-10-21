# À faire — hors code

Les actions manuelles, qui ne se règlent pas par un commit. Chaque entrée est
datée, et se coche ou se supprime une fois faite.

- [ ] **2026-10-21 — Faire révoquer l'ancienne connexion Notion.** Demander à
  l'ancien employeur de révoquer la connexion d'intégration qui donnait accès à
  son espace Notion. Elle garde ses accès même après le départ de son créateur.
- [ ] **2026-10-21 — Nettoyer l'index.** Dans l'onglet admin **Documents**,
  supprimer les fichiers uploadés et les réponses FAQ (questions « sans réponse »
  résolues) qui datent de l'ancien employeur. La synchro Notion ne retire que les
  pages Notion.
- [ ] **2026-10-21 — Nettoyer les statistiques admin.** Les questions de test
  posées les 2026-10-21 et 2026-10-22 faussent les statistiques admin, et il y en
  a plus de 130 : 62 + 62 + 12, plus quelques questions isolées.
- [ ] **2026-10-21 — Mettre en place l'anti-pause Supabase.** Le plan gratuit
  met le projet en pause après environ 7 jours sans activité. À faire sur
  cron-job.org (compte gratuit) :
  1. Une tâche quotidienne `GET https://<ref>.supabase.co/rest/v1/topics?select=id&limit=1`,
     avec les en-têtes `apikey: <clé anon>` et `Authorization: Bearer <clé anon>`.
     Avec le RLS actif, la clé anon ne lit rien, mais la requête atteint Postgres.
  2. Une tâche quotidienne `GET https://arieldev13-assistant-rh-rag.hf.space/api/health`
     (garde le Space HF éveillé).

  Ensuite, supprimer `.github/workflows/keep-alive.yml`.
- [ ] **2026-10-21 — Supprimer l'ancien projet Supabase en pause** (celui mis en
  pause pour libérer une place) ou le migrer vers un autre compte, comme prévu.

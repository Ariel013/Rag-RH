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
- [x] **2026-10-22 — Anti-pause Supabase en place** sur cron-job.org, avec
  notification par e-mail en cas d'échec :
  - chaque jour à 06:00 : `GET …supabase.co/rest/v1/topics?select=id&limit=1`
    avec l'en-tête `apikey` (clé publique). Le 2026-10-22, le test a renvoyé
    `200 []`, ce qui confirme que le RLS est actif en prod ;
  - chaque jour à 06:15 : `GET …hf.space/api/health`.

  L'ancien workflow GitHub `keep-alive.yml` a été supprimé du dépôt.
- [ ] **2026-10-21 — Supprimer l'ancien projet Supabase en pause** (celui mis en
  pause pour libérer une place) ou le migrer vers un autre compte, comme prévu.

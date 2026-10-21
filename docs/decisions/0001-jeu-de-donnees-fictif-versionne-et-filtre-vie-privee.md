# 0001 — Base de connaissances fictive, versionnée dans le dépôt, avec un filtre vie privée à l'import

**Statut** : adopté (2026-10-21)

## Contexte

Jusqu'au 2026-10-21, l'assistant lisait le Notion d'un ancien employeur de
l'auteur : données réelles, dont 81 fiches de collaborateurs, exposées par un
Space Hugging Face public et un chat sans authentification. L'auteur n'avait plus
accès à ce Notion ; seul le jeton d'intégration fonctionnait encore (une
connexion Notion garde ses accès quand son créateur quitte l'espace).

Options envisagées :

1. Continuer avec ce Notion en filtrant les informations sensibles.
2. Rendre le Space privé et garder les données réelles.
3. Repartir sur un contenu fictif, saisi à la main dans un Notion personnel.
4. Repartir sur un contenu fictif **généré et versionné dans le dépôt**, publié
   dans un Notion personnel par script.

## Décision

On retient l'option 4. Le contenu vit dans `RAG/seed/` :

- un **référentiel** qui fixe les faits (53 collaborateurs, règles RH chiffrées) ;
- l'arborescence des pages en Markdown et JSON ;
- 62 questions de test ;
- `push_notion.py`, qui publie le tout dans Notion.

Les e-mails utilisent le domaine réservé `aeig.example`. En plus, un filtre vie
privée retire à l'import :

- les pages d'anniversaire ;
- les lignes qui mentionnent une date de naissance, une adresse ou un téléphone
  personnels, ou une situation familiale.

Une règle du prompt refuse aussi ces questions.

## Pourquoi

- Les options 1 et 2 continuaient d'utiliser des données qui ne sont plus à
  l'auteur, par un accès qu'il n'a plus à titre légitime.
- Le versionnement rend la base **reproductible** : la perte d'accès à un Notion,
  exactement la panne qu'on vient de subir, se répare en une commande.
- Le référentiel garantit la cohérence entre des pages écrites séparément, et les
  questions de test permettent de mesurer la qualité au lieu de l'estimer.
- Le filtre vie privée reste utile pour le futur vrai déploiement, où les fiches
  seront réelles.

## Conséquences

- Toute modification de contenu se fait dans `RAG/seed/notion/`, puis se republie.
  Une modification faite seulement dans Notion est perdue au prochain `--reset`.
- Le Notion de l'ancien employeur ne doit plus être utilisé. Son jeton a été
  retiré du Space. Il reste à demander à l'ancien employeur de révoquer la
  connexion (`A-FAIRE.md`).
- Le filtre est par mots-clés : une formulation libre (« fête ses 30 ans le
  3 mai ») passe à travers. La règle du prompt est le second filet, pas une
  garantie.
- Toute évolution de la recherche ou du prompt se mesure sur `seed/eval/`.

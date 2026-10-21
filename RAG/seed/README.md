# Jeu de données fictif AEIG — contenu Notion

Ce dossier contient **l'intégralité de la base de connaissances fictive** d'AEIG,
sous forme de fichiers texte versionnés, et le script qui la pousse dans Notion.
Tout y est inventé : entreprise, personnes, chiffres. Les adresses e-mail
utilisent le domaine réservé `aeig.example` (RFC 2606), qui n'appartient à personne.

Pourquoi des fichiers plutôt qu'une saisie directe dans Notion : si l'accès à
l'espace Notion est perdu, la base se recrée à l'identique en une commande.

## Contenu

- `referentiel.md` — la « bible » : faits, chiffres et personnes de référence.
  Toute page doit rester cohérente avec lui. **Il n'est pas poussé dans Notion.**
- `notion/` — l'arborescence des pages poussées dans Notion.
- `eval/` — questions de test avec la réponse attendue, pour mesurer la qualité
  des réponses de l'assistant.
- `push_notion.py` — le script de publication.

## Arborescence `notion/`

- `_page.md` à la racine : contenu de la page racine Notion.
- `NN-slug.md` : une page sans sous-page. `NN` fixe l'ordre.
- `NN-slug/` : une page avec sous-pages ; son contenu propre est dans `NN-slug/_page.md`.
- `NN-slug.db.json` : une base Notion (voir plus bas).

Chaque `.md` commence par `# Titre de la page` (ce titre devient le titre Notion),
éventuellement suivi d'une ligne `icon: 🏢`.

## Markdown accepté

| Syntaxe | Bloc Notion |
| --- | --- |
| `## Titre` / `### Titre` | Titre de niveau 2 / 3 (le `#` est réservé au titre de page) |
| `- texte` | Liste à puces |
| `1. texte` | Liste numérotée |
| `> texte` | Citation |
| `!> 💡 texte` | Encadré (callout) avec son emoji |
| `+ Titre` puis lignes indentées de 2 espaces | Bloc dépliable (toggle) et son contenu |
| `\| a \| b \|` (1re ligne = en-têtes, ligne `\|---\|` ignorée) | Tableau |
| `---` | Séparateur |
| `**gras**` | Gras dans le texte |
| autre ligne non vide | Paragraphe |

Une ligne vide sépare les blocs. Pas d'imbrication au-delà d'un niveau de toggle.

## Bases Notion (`.db.json`)

```json
{
  "title": "People Book",
  "icon": "👥",
  "properties": {
    "Nom": "title",
    "Poste": "rich_text",
    "Entité": {"select": ["AEIG Bénin", "AEIG Côte d'Ivoire"]},
    "Arrivée": "number",
    "Email": "email"
  },
  "rows": [
    {"Nom": "…", "Poste": "…", "Entité": "AEIG Bénin", "Arrivée": 2019,
     "Email": "…@aeig.example", "_body": "Markdown du contenu de la fiche"}
  ]
}
```

Le contenu `_body` est **indispensable** : l'assistant indexe le texte des pages,
pas les propriétés des bases.

## Publication

```bash
cd RAG && python seed/push_notion.py          # refuse si la page racine n'est pas vide
cd RAG && python seed/push_notion.py --reset  # archive d'abord le contenu existant
```

Lit `NOTION_TOKEN` et `NOTION_ROOT_PAGE_ID` dans `RAG/.env`.

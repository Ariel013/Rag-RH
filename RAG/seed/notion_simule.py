"""
Notion simulé à partir de seed/notion/, sans aucun appel réseau.

Expose les trois appels que lit backend/notion_loader.py (pages.retrieve,
blocks.children.list, databases.query) et renvoie les blocs que
push_notion.py publierait. Le chargeur Notion de prod tourne donc tel quel
dessus : même extraction de texte, même filtre vie privée, même découpage.

Limite connue : les blocs sont ceux que push_notion.py envoie, pas ceux que
Notion renvoie après publication. Les deux coïncident pour la syntaxe du
seed (voir seed/README.md), mais pas pour les images (OCR), absentes du seed.
"""
import itertools
from pathlib import Path

from push_notion import SEED_DIR, load_tree, markdown_to_blocks, parse_page_file

ROOT_ID = "seed-racine"
_LAST_EDITED = "2026-01-01T00:00:00.000Z"


def _with_plain_text(rich_text: list[dict]) -> list[dict]:
    """push_notion écrit text.content ; Notion renvoie aussi plain_text, que lit le chargeur."""
    return [{**rt, "plain_text": rt["text"]["content"]} for rt in rich_text]


def _title_prop(title: str) -> dict:
    return {"type": "title", "title": [{"plain_text": title}]}


class _Endpoint:
    def __init__(self, **fns):
        for name, fn in fns.items():
            setattr(self, name, fn)


class NotionSimule:
    def __init__(self, seed_dir: Path = SEED_DIR):
        self._ids      = itertools.count(1)
        self._children: dict[str, list[dict]] = {}   # id de bloc ou de page → blocs enfants
        self._pages:    dict[str, dict] = {}         # id de page → objet page Notion
        self._dbs:      dict[str, list[dict]] = {}   # id de base → lignes (objets page)
        # titre de page → noms sous lesquels le jeu de test seed/eval la désigne
        self.libelles:  dict[str, set[str]] = {}

        root = parse_page_file(seed_dir / "_page.md")
        self._pages[ROOT_ID] = self._page_object(ROOT_ID, {"Titre": _title_prop(root["title"])})
        self._children[ROOT_ID] = (
            self._register_blocks(root["blocks"]) + self._register_nodes(load_tree(seed_dir))
        )
        self._label(root["title"], root["title"])

        self.pages     = _Endpoint(retrieve=self._retrieve)
        self.blocks    = _Endpoint(children=_Endpoint(list=self._list_children))
        self.databases = _Endpoint(query=self._query)

    # ── Construction ──────────────────────────────────────────────────────

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    @staticmethod
    def _page_object(page_id: str, properties: dict) -> dict:
        return {"object": "page", "id": page_id, "properties": properties,
                "last_edited_time": _LAST_EDITED}

    def _register_blocks(self, blocks: list[dict]) -> list[dict]:
        """Donne un id à chaque bloc et range ses enfants (toggle, table) à part."""
        out = []
        for block in blocks:
            btype = block["type"]
            data  = dict(block.get(btype, {}))
            if "rich_text" in data:
                data["rich_text"] = _with_plain_text(data["rich_text"])
            if btype == "table_row":
                data["cells"] = [_with_plain_text(c) for c in data["cells"]]
            children = data.pop("children", [])
            block_id = self._new_id("bloc")
            if children:
                self._children[block_id] = self._register_blocks(children)
            out.append({"object": "block", "id": block_id, "type": btype, btype: data,
                        "has_children": bool(children)})
        return out

    def _label(self, title: str, *labels: str) -> None:
        self.libelles.setdefault(title, set()).update(labels)

    def _register_nodes(self, nodes: list[dict]) -> list[dict]:
        """
        Pages et bases d'un niveau → blocs child_page / child_database du parent.
        Libellés du jeu de test : « Page », « Base » (toute ligne de la base)
        ou « Base — Ligne ». La forme « Rubrique > Page » se ramène à « Page »
        (voir eval_recherche.py) : les rubriques y portent un nom abrégé.
        """
        out = []
        for node in nodes:
            if node["kind"] == "page":
                page_id = self._new_id("page")
                self._pages[page_id] = self._page_object(
                    page_id, {"Titre": _title_prop(node["title"])}
                )
                self._children[page_id] = (
                    self._register_blocks(node["blocks"])
                    + self._register_nodes(node["children"])
                )
                self._label(node["title"], node["title"])
                out.append({"object": "block", "id": page_id, "type": "child_page",
                            "child_page": {"title": node["title"]}, "has_children": True})
            else:
                db_id = self._new_id("base")
                self._dbs[db_id] = [self._register_row(node["properties"], row)
                                    for row in node["rows"]]
                for page in self._dbs[db_id]:
                    title = next(p["title"][0]["plain_text"] for p in page["properties"].values()
                                 if p["type"] == "title")
                    self._label(title, title, node["title"], f"{node['title']} — {title}")
                out.append({"object": "block", "id": db_id, "type": "child_database",
                            "child_database": {"title": node["title"]}, "has_children": False})
        return out

    def _register_row(self, schema: dict, row: dict) -> dict:
        props = {}
        for name, ptype in schema.items():
            value = row.get(name)
            if ptype == "title":
                props[name] = _title_prop(str(value or ""))
            elif isinstance(ptype, dict) and "select" in ptype and value:
                props[name] = {"type": "select", "select": {"name": value}}
            elif ptype == "rich_text" and value:
                props[name] = {"type": "rich_text", "rich_text": [{"plain_text": str(value)}]}
        page_id = self._new_id("ligne")
        page = self._page_object(page_id, props)
        self._pages[page_id] = page
        self._children[page_id] = self._register_blocks(
            markdown_to_blocks(row["_body"].splitlines())
        )
        return page

    # ── API Notion simulée ────────────────────────────────────────────────

    def _retrieve(self, page_id: str) -> dict:
        return self._pages[page_id]

    def _list_children(self, block_id: str, page_size: int = 100, start_cursor=None) -> dict:
        return {"results": self._children.get(block_id, []), "has_more": False}

    def _query(self, database_id: str, page_size: int = 100, start_cursor=None) -> dict:
        return {"results": self._dbs.get(database_id, []), "has_more": False}

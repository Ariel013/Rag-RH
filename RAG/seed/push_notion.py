"""
Publie le jeu de données fictif AEIG (dossier seed/notion/) dans Notion.

Usage (depuis RAG/) :
    python seed/push_notion.py --dry-run   # vérifie le contenu, aucun appel réseau
    python seed/push_notion.py             # refuse si la page racine n'est pas vide
    python seed/push_notion.py --reset     # supprime d'abord le contenu de la page racine

Lit NOTION_TOKEN et NOTION_ROOT_PAGE_ID dans RAG/.env. Format des fichiers : seed/README.md.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

SEED_DIR   = Path(__file__).resolve().parent / "notion"
ENV_FILE   = Path(__file__).resolve().parent.parent / ".env"

_MAX_RICH_TEXT = 2000   # caractères par segment de texte Notion
_MAX_CHILDREN  = 100    # blocs par requête Notion
_THROTTLE      = 0.35   # secondes entre deux appels (~3 req/s autorisées)


# ─── Markdown → blocs Notion ─────────────────────────────────────────────────

def _rich_text(text: str) -> list[dict]:
    """Texte avec **gras** → rich_text Notion, découpé à 2000 caractères."""
    segments = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        bold = i % 2 == 1
        for start in range(0, len(part), _MAX_RICH_TEXT):
            segments.append({
                "type": "text",
                "text": {"content": part[start:start + _MAX_RICH_TEXT]},
                "annotations": {"bold": bold},
            })
    return segments


def _block(btype: str, text: str, **extra) -> dict:
    return {"object": "block", "type": btype, btype: {"rich_text": _rich_text(text), **extra}}


def _table(rows: list[list[str]]) -> dict:
    width = max(len(r) for r in rows)
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": [
                {
                    "object": "block",
                    "type": "table_row",
                    "table_row": {"cells": [_rich_text(c) for c in r + [""] * (width - len(r))]},
                }
                for r in rows
            ],
        },
    }


def _parse_table_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        raw  = lines[i]
        line = raw.strip()
        i += 1
        if not line:
            continue
        if line.startswith("|"):
            rows = [_parse_table_row(line)]
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.fullmatch(r"\|[\s:|-]+\|?", lines[i].strip()):
                    rows.append(_parse_table_row(lines[i]))
                i += 1
            blocks.append(_table(rows))
        elif line.startswith("+ "):
            children_lines = []
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                # une ligne vide suivie d'une ligne non indentée termine le toggle
                if not lines[i].strip() and (i + 1 >= len(lines) or not lines[i + 1].startswith("  ")):
                    break
                children_lines.append(lines[i][2:])
                i += 1
            children = markdown_to_blocks(children_lines)
            blocks.append(_block("toggle", line[2:], children=children))
        elif line.startswith("### "):
            blocks.append(_block("heading_3", line[4:]))
        elif line.startswith("## "):
            blocks.append(_block("heading_2", line[3:]))
        elif line.startswith("# "):
            blocks.append(_block("heading_1", line[2:]))
        elif line == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif line.startswith("!> "):
            emoji, _, text = line[3:].partition(" ")
            blocks.append(_block("callout", text, icon={"type": "emoji", "emoji": emoji}))
        elif line.startswith("> "):
            blocks.append(_block("quote", line[2:]))
        elif line.startswith("- "):
            blocks.append(_block("bulleted_list_item", line[2:]))
        elif re.match(r"\d+\. ", line):
            blocks.append(_block("numbered_list_item", line.split(". ", 1)[1]))
        else:
            blocks.append(_block("paragraph", line))
    return blocks


def parse_page_file(path: Path) -> dict:
    """Lit un .md : titre (# …), icône facultative (icon: …), blocs."""
    lines = path.read_text(encoding="utf-8").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{path} : la première ligne doit être « # Titre »")
    title = lines.pop(0)[2:].strip()
    icon  = None
    if lines and lines[0].startswith("icon:"):
        icon = lines.pop(0).split(":", 1)[1].strip()
    return {"title": title, "icon": icon, "blocks": markdown_to_blocks(lines)}


# ─── Arborescence ────────────────────────────────────────────────────────────

def load_tree(directory: Path) -> list[dict]:
    """Liste ordonnée des nœuds (page, page avec sous-pages, base) d'un dossier."""
    nodes = []
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("_"):
            continue
        if entry.is_dir():
            page = parse_page_file(entry / "_page.md")
            page["kind"]     = "page"
            page["children"] = load_tree(entry)
            nodes.append(page)
        elif entry.name.endswith(".db.json"):
            db = json.loads(entry.read_text(encoding="utf-8"))
            db["kind"] = "database"
            _check_database(db, entry)
            nodes.append(db)
        elif entry.suffix == ".md":
            page = parse_page_file(entry)
            page["kind"]     = "page"
            page["children"] = []
            nodes.append(page)
    return nodes


def _check_database(db: dict, path: Path) -> None:
    titles = [k for k, v in db["properties"].items() if v == "title"]
    if len(titles) != 1:
        raise ValueError(f"{path} : il faut exactement une propriété de type title")
    for n, row in enumerate(db["rows"], 1):
        if not row.get(titles[0]):
            raise ValueError(f"{path} : ligne {n} sans titre")
        if not row.get("_body", "").strip():
            raise ValueError(f"{path} : ligne {n} sans _body (le texte est ce que l'assistant indexe)")
        unknown = set(row) - set(db["properties"]) - {"_body"}
        if unknown:
            raise ValueError(f"{path} : ligne {n}, propriétés inconnues {sorted(unknown)}")


# ─── Bases Notion ────────────────────────────────────────────────────────────

def _schema(properties: dict) -> dict:
    schema = {}
    for name, spec in properties.items():
        if isinstance(spec, str):
            schema[name] = {spec: {}}
        else:
            (ptype, options), = spec.items()
            schema[name] = {ptype: {"options": [{"name": o} for o in options]}}
    return schema


def _row_properties(properties: dict, row: dict) -> dict:
    values = {}
    for name, spec in properties.items():
        if name not in row:
            continue
        ptype = spec if isinstance(spec, str) else next(iter(spec))
        value = row[name]
        if ptype == "title":
            values[name] = {"title": _rich_text(str(value))}
        elif ptype == "rich_text":
            values[name] = {"rich_text": _rich_text(str(value))}
        elif ptype == "number":
            values[name] = {"number": value}
        elif ptype == "email":
            values[name] = {"email": value}
        elif ptype == "date":
            values[name] = {"date": {"start": value}}
        elif ptype == "select":
            values[name] = {"select": {"name": value}}
        elif ptype == "multi_select":
            values[name] = {"multi_select": [{"name": v} for v in value]}
        else:
            raise ValueError(f"Type de propriété non géré : {ptype}")
    return values


# ─── Publication ─────────────────────────────────────────────────────────────

class Publisher:
    def __init__(self, client):
        self.client = client
        self.calls  = 0

    def _call(self, fn, **kwargs):
        from notion_client.errors import APIResponseError
        for attempt in range(6):
            time.sleep(_THROTTLE)
            self.calls += 1
            try:
                return fn(**kwargs)
            except APIResponseError as exc:
                if exc.status != 429 and exc.status < 500 or attempt == 5:
                    raise
                retry_after = exc.headers.get("retry-after") if exc.headers else None
                time.sleep(min(float(retry_after or 2 ** (attempt + 1)), 30))
        raise RuntimeError("unreachable")

    def append(self, block_id: str, blocks: list[dict]) -> None:
        for start in range(0, len(blocks), _MAX_CHILDREN):
            self._call(self.client.blocks.children.append,
                       block_id=block_id, children=blocks[start:start + _MAX_CHILDREN])

    def create_page(self, parent: dict, title: str, icon: str | None, blocks: list[dict],
                    properties: dict | None = None) -> str:
        kwargs = {
            "parent": parent,
            "properties": properties or {"title": {"title": _rich_text(title)}},
            "children": blocks[:_MAX_CHILDREN],
        }
        if icon:
            kwargs["icon"] = {"type": "emoji", "emoji": icon}
        page_id = self._call(self.client.pages.create, **kwargs)["id"]
        self.append(page_id, blocks[_MAX_CHILDREN:])
        return page_id

    def publish(self, parent_id: str, nodes: list[dict], depth: int = 0) -> int:
        count = 0
        for node in nodes:
            indent = "  " * depth
            if node["kind"] == "page":
                page_id = self.create_page({"page_id": parent_id}, node["title"],
                                           node.get("icon"), node["blocks"])
                print(f"{indent}✓ {node['title']}")
                count += 1 + self.publish(page_id, node["children"], depth + 1)
            else:
                kwargs = {
                    "parent": {"type": "page_id", "page_id": parent_id},
                    "title": _rich_text(node["title"]),
                    "properties": _schema(node["properties"]),
                }
                if node.get("icon"):
                    kwargs["icon"] = {"type": "emoji", "emoji": node["icon"]}
                db_id = self._call(self.client.databases.create, **kwargs)["id"]
                for row in node["rows"]:
                    self.create_page(
                        {"database_id": db_id}, "", None,
                        markdown_to_blocks(row["_body"].splitlines()),
                        properties=_row_properties(node["properties"], row),
                    )
                print(f"{indent}✓ Base « {node['title']} » ({len(node['rows'])} lignes)")
                count += len(node["rows"])
        return count


def _count(nodes: list[dict]) -> tuple[int, int]:
    pages = rows = 0
    for n in nodes:
        if n["kind"] == "page":
            pages += 1
            p, r = _count(n["children"])
            pages, rows = pages + p, rows + r
        else:
            rows += len(n["rows"])
    return pages, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="vérifier le contenu sans rien publier")
    parser.add_argument("--reset", action="store_true", help="supprimer le contenu existant de la page racine")
    args = parser.parse_args()

    root_page = parse_page_file(SEED_DIR / "_page.md")
    tree      = load_tree(SEED_DIR)
    pages, rows = _count(tree)
    print(f"Contenu : {pages} pages, {rows} lignes de bases")
    if args.dry_run:
        return

    load_dotenv(ENV_FILE)
    token   = os.getenv("NOTION_TOKEN", "").strip()
    root_id = os.getenv("NOTION_ROOT_PAGE_ID", "").strip()
    if not token or not re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}", root_id):
        sys.exit("NOTION_TOKEN absent ou NOTION_ROOT_PAGE_ID invalide (32 caractères hexadécimaux) dans RAG/.env")

    from notion_client import Client
    pub = Publisher(Client(auth=token))

    existing = pub._call(pub.client.blocks.children.list, block_id=root_id)["results"]
    if existing and not args.reset:
        sys.exit(f"La page racine contient déjà {len(existing)} bloc(s). Relancer avec --reset pour les supprimer.")
    if args.reset:
        while existing:
            for block in existing:
                pub._call(pub.client.blocks.delete, block_id=block["id"])
            existing = pub._call(pub.client.blocks.children.list, block_id=root_id)["results"]
        print("Contenu existant supprimé (corbeille Notion).")

    pub.append(root_id, root_page["blocks"])
    total = pub.publish(root_id, tree)
    print(f"Terminé : {total} pages et lignes créées, {pub.calls} appels API.")


if __name__ == "__main__":
    main()

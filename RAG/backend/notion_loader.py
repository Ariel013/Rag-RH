"""
Notion Loader — synchronisation des pages Notion vers le vector store.
Parcourt récursivement toutes les pages à partir d'une page racine,
en traversant tous les types de blocs conteneurs (columns, toggles, etc.).
"""
import io
import os
import uuid

import httpx
from notion_client import Client
from notion_client.errors import APIResponseError

from .document_processor import chunk_text

NOTION_TOKEN        = os.getenv("NOTION_TOKEN", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")

# Blocs qui peuvent contenir d'autres blocs (y compris des child_page)
_CONTAINER_TYPES = {
    "column_list", "column", "toggle", "bulleted_list_item",
    "numbered_list_item", "quote", "callout", "synced_block",
    "template", "table", "table_row",
}


def _get_client() -> Client:
    return Client(auth=NOTION_TOKEN)


# ─── Extraction de texte depuis les blocs ────────────────────────────────────

def _image_ocr(url: str) -> str:
    """Télécharge une image Notion et en extrait le texte via OCR (tesseract)."""
    try:
        import pytesseract
        from PIL import Image

        with httpx.Client(timeout=20) as client:
            resp = client.get(url)
            resp.raise_for_status()
        img  = Image.open(io.BytesIO(resp.content))
        text = pytesseract.image_to_string(img, lang="fra+eng")
        return text.strip()
    except Exception as exc:
        print(f"  ⚠ OCR image échoué : {exc}")
        return ""


def _rich_text_to_str(rich_texts: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def _block_to_text(block: dict) -> str:
    btype = block.get("type", "")
    data  = block.get(btype, {})

    if btype in ("paragraph", "quote", "callout"):
        return _rich_text_to_str(data.get("rich_text", []))
    elif btype in ("heading_1", "heading_2", "heading_3"):
        prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### "}.get(btype, "")
        return prefix + _rich_text_to_str(data.get("rich_text", []))
    elif btype in ("bulleted_list_item", "numbered_list_item", "to_do"):
        return "• " + _rich_text_to_str(data.get("rich_text", []))
    elif btype == "toggle":
        return _rich_text_to_str(data.get("rich_text", []))
    elif btype == "code":
        return _rich_text_to_str(data.get("rich_text", []))
    elif btype == "image":
        url = (
            block.get("image", {}).get("file", {}).get("url")
            or block.get("image", {}).get("external", {}).get("url")
            or ""
        )
        if url:
            return _image_ocr(url)
    return ""


def _extract_blocks(client: Client, block_id: str) -> str:
    """Récupère récursivement tout le texte d'une page, en traversant tous les conteneurs."""
    lines  = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.blocks.children.list(**kwargs)

        for block in response.get("results", []):
            btype = block.get("type", "")

            # Ne jamais descendre dans une child_page — elle est indexée séparément
            if btype == "child_page":
                continue

            text = _block_to_text(block)
            if text:
                lines.append(text)

            # Descendre dans tous les blocs qui peuvent contenir des enfants
            if block.get("has_children"):
                child_text = _extract_blocks(client, block["id"])
                if child_text:
                    lines.append(child_text)

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return "\n\n".join(filter(None, lines))


# ─── Collecte récursive de toutes les child_page ─────────────────────────────

def _collect_child_pages(client: Client, block_id: str, depth: int = 0) -> list[dict]:
    """
    Parcourt tous les blocs (y compris column_list, column, toggle…)
    pour trouver les child_page à tous les niveaux.
    """
    if depth > 8:
        return []
    pages  = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.blocks.children.list(**kwargs)

        for block in response.get("results", []):
            btype = block.get("type", "")

            if btype == "child_page":
                child_id    = block["id"]
                child_title = block.get("child_page", {}).get("title", "Page sans titre")
                pages.append({"id": child_id, "title": child_title})
                # Récursion dans la sous-page
                pages.extend(_collect_child_pages(client, child_id, depth + 1))

            elif block.get("has_children"):
                # Descendre dans les conteneurs (column_list, column, toggle, etc.)
                pages.extend(_collect_child_pages(client, block["id"], depth + 1))

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return pages


# ─── Métadonnées des pages ────────────────────────────────────────────────────

def _get_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title = _rich_text_to_str(prop.get("title", []))
            if title:
                return title
    return "Page sans titre"


def _get_page_category(page: dict) -> str:
    props = page.get("properties", {})
    for key in ("Catégorie", "Category", "categorie", "category", "Type"):
        prop = props.get(key)
        if not prop:
            continue
        ptype = prop.get("type")
        if ptype == "select" and prop.get("select"):
            return prop["select"]["name"]
        elif ptype == "multi_select" and prop.get("multi_select"):
            return prop["multi_select"][0]["name"]
        elif ptype == "rich_text":
            text = _rich_text_to_str(prop.get("rich_text", []))
            if text:
                return text
    return "Général"


# ─── Interface publique ───────────────────────────────────────────────────────

def load_notion_pages() -> list[tuple[list[str], list[dict], str]]:
    """
    Charge toutes les pages depuis Notion et les découpe en chunks.
    Retourne une liste de (chunks, metadatas, doc_id).
    """
    if not NOTION_TOKEN or not NOTION_ROOT_PAGE_ID:
        raise ValueError("NOTION_TOKEN et NOTION_ROOT_PAGE_ID doivent être définis dans .env")

    client = _get_client()

    try:
        root_page     = client.pages.retrieve(NOTION_ROOT_PAGE_ID)
        root_title    = _get_page_title(root_page)
        root_category = _get_page_category(root_page)
    except APIResponseError as exc:
        raise ValueError(f"Impossible d'accéder à la page Notion racine : {exc}") from exc

    # Collecte toutes les sous-pages (traversée complète de l'arborescence)
    all_pages = [{"id": NOTION_ROOT_PAGE_ID, "title": root_title, "category": root_category}]
    for cp in _collect_child_pages(client, NOTION_ROOT_PAGE_ID):
        try:
            page_data = client.pages.retrieve(cp["id"])
            category  = _get_page_category(page_data)
        except APIResponseError:
            category = "Général"
        all_pages.append({"id": cp["id"], "title": cp["title"], "category": category})

    print(f"  → {len(all_pages)} pages Notion trouvées")

    results = []
    for page_info in all_pages:
        try:
            text = _extract_blocks(client, page_info["id"])
            if not text.strip():
                continue
            chunks = chunk_text(text)
            if not chunks:
                continue
            doc_id    = str(uuid.uuid4())
            metadatas = [
                {
                    "doc_id":      doc_id,
                    "title":       page_info["title"],
                    "source":      f"notion:{page_info['id']}",
                    "category":    page_info["category"],
                    "chunk_index": i,
                }
                for i in range(len(chunks))
            ]
            results.append((chunks, metadatas, doc_id))
            print(f"  ✓ {page_info['title']} ({len(chunks)} chunks)")
        except APIResponseError as exc:
            print(f"  ✗ Erreur '{page_info['title']}': {exc}")

    return results


def check_notion_connection() -> dict:
    if not NOTION_TOKEN:
        return {"ok": False, "error": "NOTION_TOKEN manquant dans .env"}
    if not NOTION_ROOT_PAGE_ID:
        return {"ok": False, "error": "NOTION_ROOT_PAGE_ID manquant dans .env"}
    try:
        client = _get_client()
        page   = client.pages.retrieve(NOTION_ROOT_PAGE_ID)
        title  = _get_page_title(page)
        return {"ok": True, "root_page": title}
    except APIResponseError as exc:
        return {"ok": False, "error": str(exc)}

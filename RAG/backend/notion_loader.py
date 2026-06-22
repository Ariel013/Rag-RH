"""
Notion Loader — synchronisation des pages Notion vers le vector store.
Parcourt récursivement toutes les pages à partir d'une page racine,
en traversant tous les types de blocs conteneurs (columns, toggles, etc.).
"""
import io
import os
import time
import uuid

import httpx
from notion_client import Client
from notion_client.errors import APIResponseError

from .document_processor import chunk_text

NOTION_TOKEN        = os.getenv("NOTION_TOKEN", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")

_CONTAINER_TYPES = {
    "column_list", "column", "toggle", "bulleted_list_item",
    "numbered_list_item", "quote", "callout", "synced_block",
    "template", "table", "table_row",
}

_MAX_DB_ROWS = 200


def _get_client() -> Client:
    return Client(auth=NOTION_TOKEN)


# ─── Wrapper retry Notion API ────────────────────────────────────────────────

def _notion_call(fn, *args, **kwargs):
    """Retry jusqu'à 3 fois avec backoff exponentiel sur rate-limit et erreurs 5xx."""
    for attempt in range(3):
        try:
            return fn(*args, **kwargs)
        except APIResponseError as exc:
            if exc.status in (429,) or exc.status >= 500:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            raise
        except httpx.TimeoutException:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("_notion_call: unreachable")


# ─── OCR images ──────────────────────────────────────────────────────────────

def _image_ocr(url: str, page_title: str = "") -> str:
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url)
        if resp.status_code in (401, 403, 410):
            short_url = url[:80] + "…" if len(url) > 80 else url
            print(f"  ⚠ Image URL expirée (HTTP {resp.status_code}) — page « {page_title} » — {short_url}")
            return ""
        resp.raise_for_status()
        image_bytes  = resp.content
        content_type = resp.headers.get("content-type", "image/png").split(";")[0]
    except httpx.HTTPStatusError as exc:
        short_url = url[:80] + "…" if len(url) > 80 else url
        print(f"  ⚠ Téléchargement image échoué HTTP {exc.response.status_code} — page « {page_title} » — {short_url}")
        return ""
    except Exception as exc:
        print(f"  ⚠ Téléchargement image échoué : {exc}")
        return ""

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key and groq_key.lower() != "ollama":
        try:
            import base64
            b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
            payload = {
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{content_type};base64,{b64}"},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Extrait tout le contenu textuel de cette image sous forme de texte structuré. "
                                    "Si c'est un tableau, liste chaque ligne avec ses colonnes clairement associées "
                                    "(ex: 'Rituel: X | Lead: Y | Lieu: Z | Fréquence: W'). "
                                    "Ne résume pas, retranscris fidèlement toutes les informations."
                                ),
                            },
                        ],
                    }
                ],
                "max_tokens": 1024,
            }
            with httpx.Client(timeout=30) as client:
                r = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                )
                r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text:
                print(f"  ✓ OCR vision LLM réussi ({len(text)} chars)")
                return text
        except Exception as exc:
            print(f"  ⚠ OCR vision LLM échoué : {exc}")

    try:
        import pytesseract
        from PIL import Image
        img  = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang="fra+eng")
        text = text.strip()
        if text:
            print(f"  ✓ OCR tesseract réussi ({len(text)} chars)")
        return text
    except Exception as exc:
        print(f"  ⚠ OCR tesseract échoué : {exc}")
        return ""


# ─── Extraction de texte depuis les blocs ────────────────────────────────────

def _rich_text_to_str(rich_texts: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def _block_to_text(block: dict, page_title: str = "") -> str:
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
            return _image_ocr(url, page_title=page_title)
    return ""


def _extract_blocks(client: Client, block_id: str, page_title: str = "") -> str:
    """
    Récupère récursivement tout le texte d'une page en traversant tous les conteneurs.
    Préfixe les chunks avec le contexte de section (heading courant).
    Formate les tables Notion de façon structurée.
    """
    lines          = []
    current_heading = ""
    cursor         = None

    while True:
        kwargs: dict = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = _notion_call(client.blocks.children.list, **kwargs)

        for block in response.get("results", []):
            btype = block.get("type", "")

            # Ne jamais descendre dans child_page (indexée séparément) ni child_database (API interdit)
            if btype in ("child_page", "child_database"):
                continue

            # Traitement spécial des tables : collecter toutes les table_row
            if btype == "table":
                table_lines = _extract_table(client, block["id"])
                if table_lines:
                    lines.extend(table_lines)
                continue

            text = _block_to_text(block, page_title=page_title)

            if btype in ("heading_1", "heading_2", "heading_3"):
                raw = text.lstrip("# ").strip()
                if raw:
                    current_heading = raw
                if text:
                    lines.append(text)
            elif text:
                lines.append(text)

            if block.get("has_children") and btype not in ("child_page", "child_database", "table"):
                child_text = _extract_blocks(client, block["id"], page_title=page_title)
                if child_text:
                    lines.append(child_text)

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return "\n\n".join(filter(None, lines))


def _extract_table(client: Client, table_block_id: str) -> list[str]:
    """Extrait un tableau Notion et le formate en lignes structurées."""
    try:
        response = _notion_call(
            client.blocks.children.list, block_id=table_block_id, page_size=100
        )
    except Exception:
        return []

    table_lines = []
    for block in response.get("results", []):
        if block.get("type") != "table_row":
            continue
        cells = block.get("table_row", {}).get("cells", [])
        cell_texts = [_rich_text_to_str(cell) for cell in cells]
        if any(cell_texts):
            table_lines.append("Tableau — [" + " | ".join(cell_texts) + "]")

    return table_lines


# ─── Collecte des entrées d'une database Notion ───────────────────────────────

def _collect_database_pages(client: Client, database_id: str) -> list[dict]:
    pages  = []
    cursor = None
    total  = 0
    while total < _MAX_DB_ROWS:
        kwargs: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = _notion_call(client.databases.query, **kwargs)
        except Exception:
            break
        for entry in response.get("results", []):
            title = _get_page_title(entry)
            pages.append({"id": entry["id"], "title": title})
            total += 1
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return pages


# ─── Collecte récursive de toutes les child_page ─────────────────────────────

def _collect_child_pages(
    client: Client,
    block_id: str,
    depth: int = 0,
    visited_ids: set | None = None,
) -> list[dict]:
    """
    Parcourt tous les blocs (y compris column_list, column, toggle, child_database…)
    pour trouver les child_page à tous les niveaux.
    visited_ids évite les boucles infinies dues aux synced_blocks.
    """
    if visited_ids is None:
        visited_ids = set()
    if depth > 8 or block_id in visited_ids:
        return []
    visited_ids.add(block_id)

    pages  = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = _notion_call(client.blocks.children.list, **kwargs)
        except Exception:
            break

        for block in response.get("results", []):
            btype = block.get("type", "")

            if btype == "child_page":
                child_id    = block["id"]
                child_title = block.get("child_page", {}).get("title", "Page sans titre")
                if child_id not in visited_ids:
                    pages.append({"id": child_id, "title": child_title})
                    pages.extend(
                        _collect_child_pages(client, child_id, depth + 1, visited_ids)
                    )

            elif btype == "child_database":
                db_id    = block["id"]
                db_title = block.get("child_database", {}).get("title", "Base de données")
                db_pages = _collect_database_pages(client, db_id)
                pages.extend(db_pages)
                print(f"    → Base Notion « {db_title} » : {len(db_pages)} entrées")

            elif block.get("has_children"):
                pages.extend(
                    _collect_child_pages(client, block["id"], depth + 1, visited_ids)
                )

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
        root_page     = _notion_call(client.pages.retrieve, NOTION_ROOT_PAGE_ID)
        root_title    = _get_page_title(root_page)
        root_category = _get_page_category(root_page)
        root_last_edited = root_page.get("last_edited_time", "")
    except APIResponseError as exc:
        raise ValueError(f"Impossible d'accéder à la page Notion racine : {exc}") from exc

    all_pages = [{
        "id":          NOTION_ROOT_PAGE_ID,
        "title":       root_title,
        "category":    root_category,
        "last_edited": root_last_edited,
    }]

    visited = {NOTION_ROOT_PAGE_ID}
    for cp in _collect_child_pages(client, NOTION_ROOT_PAGE_ID, visited_ids=visited):
        try:
            page_data    = _notion_call(client.pages.retrieve, cp["id"])
            category     = _get_page_category(page_data)
            last_edited  = page_data.get("last_edited_time", "")
        except APIResponseError:
            category    = "Général"
            last_edited = ""
        all_pages.append({
            "id":          cp["id"],
            "title":       cp["title"],
            "category":    category,
            "last_edited": last_edited,
        })

    print(f"  → {len(all_pages)} pages Notion trouvées")

    results = []
    for page_info in all_pages:
        try:
            text = _extract_blocks(client, page_info["id"], page_title=page_info["title"])
            if not text.strip():
                continue
            chunks = chunk_text(text)
            if not chunks:
                continue
            doc_id    = str(uuid.uuid4())
            metadatas = [
                {
                    "doc_id":          doc_id,
                    "title":           page_info["title"],
                    "source":          f"notion:{page_info['id']}",
                    "category":        page_info["category"],
                    "chunk_index":     i,
                    "notion_page_id":  page_info["id"],
                    "notion_last_edited": page_info.get("last_edited", ""),
                }
                for i in range(len(chunks))
            ]
            results.append((chunks, metadatas, doc_id))
            print(f"  ✓ {page_info['title']} ({len(chunks)} chunks)")
        except APIResponseError as exc:
            print(f"  ✗ Erreur '{page_info['title']}': {exc}")

    return results


def load_notion_page(
    client: Client, page_info: dict
) -> tuple[list[str], list[dict], str] | None:
    """Charge et découpe une seule page Notion. Retourne None si vide."""
    try:
        text = _extract_blocks(client, page_info["id"], page_title=page_info["title"])
        if not text.strip():
            return None
        chunks = chunk_text(text)
        if not chunks:
            return None
        doc_id    = str(uuid.uuid4())
        metadatas = [
            {
                "doc_id":             doc_id,
                "title":              page_info["title"],
                "source":             f"notion:{page_info['id']}",
                "category":           page_info.get("category", "Général"),
                "chunk_index":        i,
                "notion_page_id":     page_info["id"],
                "notion_last_edited": page_info.get("last_edited", ""),
            }
            for i in range(len(chunks))
        ]
        return chunks, metadatas, doc_id
    except APIResponseError as exc:
        print(f"  ✗ Erreur '{page_info['title']}': {exc}")
        return None


def collect_all_notion_pages() -> tuple[Client, list[dict]]:
    """
    Collecte la liste de toutes les pages Notion (sans extraction de texte).
    Retourne (client, [page_info dict avec id/title/category/last_edited]).
    """
    if not NOTION_TOKEN or not NOTION_ROOT_PAGE_ID:
        raise ValueError("NOTION_TOKEN et NOTION_ROOT_PAGE_ID doivent être définis dans .env")

    client = _get_client()

    try:
        root_page    = _notion_call(client.pages.retrieve, NOTION_ROOT_PAGE_ID)
        root_title   = _get_page_title(root_page)
        root_category = _get_page_category(root_page)
        root_last_edited = root_page.get("last_edited_time", "")
    except APIResponseError as exc:
        raise ValueError(f"Impossible d'accéder à la page Notion racine : {exc}") from exc

    all_pages = [{
        "id":          NOTION_ROOT_PAGE_ID,
        "title":       root_title,
        "category":    root_category,
        "last_edited": root_last_edited,
    }]

    visited = {NOTION_ROOT_PAGE_ID}
    for cp in _collect_child_pages(client, NOTION_ROOT_PAGE_ID, visited_ids=visited):
        try:
            page_data   = _notion_call(client.pages.retrieve, cp["id"])
            category    = _get_page_category(page_data)
            last_edited = page_data.get("last_edited_time", "")
        except APIResponseError:
            category    = "Général"
            last_edited = ""
        all_pages.append({
            "id":          cp["id"],
            "title":       cp["title"],
            "category":    category,
            "last_edited": last_edited,
        })

    print(f"  → {len(all_pages)} pages Notion trouvées")
    return client, all_pages


def check_notion_connection() -> dict:
    if not NOTION_TOKEN:
        return {"ok": False, "error": "NOTION_TOKEN manquant dans .env"}
    if not NOTION_ROOT_PAGE_ID:
        return {"ok": False, "error": "NOTION_ROOT_PAGE_ID manquant dans .env"}
    try:
        client = _get_client()
        page   = _notion_call(client.pages.retrieve, NOTION_ROOT_PAGE_ID)
        title  = _get_page_title(page)
        return {"ok": True, "root_page": title}
    except APIResponseError as exc:
        return {"ok": False, "error": str(exc)}

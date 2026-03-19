"""
Document processor: extraction de texte + découpage en chunks.
Formats supportés: PDF, DOCX, TXT, MD.
"""
import re
import uuid
from pathlib import Path


# ─── Extracteurs ────────────────────────────────────────────────────────────

def _extract_pdf(path: str) -> str:
    import pypdf
    reader = pypdf.PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext in (".docx", ".doc"):
        return _extract_docx(path)
    else:
        return _extract_txt(path)


# ─── Chunker ────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """
    Découpe le texte en chunks en respectant les frontières de paragraphes.
    Ajoute un overlap entre chunks consécutifs pour préserver le contexte.
    """
    # Suppression des lignes de décoration (===, ---, *** seuls sur une ligne)
    text = re.sub(r"^[ \t]*[=\-\*]{3,}[ \t]*$", "", text, flags=re.MULTILINE)
    # Normalisation
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()

    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # Si le paragraphe seul dépasse chunk_size → le découper par phrases
        if len(para) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) + 1 <= chunk_size:
                    buf = (buf + " " + sent).strip()
                else:
                    if buf:
                        chunks.append(buf)
                    buf = sent
            if buf:
                chunks.append(buf)
        elif len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para

    if current:
        chunks.append(current)

    # Overlap : ajoute les N derniers mots du chunk précédent au début du suivant
    if overlap > 0 and len(chunks) > 1:
        overlap_words = max(1, overlap // 6)
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = " ".join(chunks[i - 1].split()[-overlap_words:])
            result.append((prev_tail + " " + chunks[i]).strip())
        return result

    return chunks


# ─── Point d'entrée principal ────────────────────────────────────────────────

def process_document(
    file_path: str,
    title: str | None = None,
    category: str = "Général",
) -> tuple[list[str], list[dict], str]:
    """
    Retourne (chunks, metadatas, doc_id).
    """
    doc_id = str(uuid.uuid4())
    filename = Path(file_path).name
    if not title:
        title = Path(file_path).stem.replace("_", " ").replace("-", " ").title()

    text = extract_text(file_path)
    chunks = chunk_text(text)

    metadatas = [
        {
            "doc_id": doc_id,
            "title": title,
            "source": filename,
            "category": category,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    return chunks, metadatas, doc_id

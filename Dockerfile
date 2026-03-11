FROM python:3.11-slim

WORKDIR /app

# Dépendances système pour compiler certains packages Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
COPY RAG/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-télécharger le modèle d'embedding pour l'inclure dans l'image
# (évite un long chargement au 1er démarrage)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Copier le code applicatif
COPY RAG/backend/ ./backend/
COPY RAG/frontend/ ./frontend/
COPY RAG/sample_docs/ ./sample_docs/

# Créer les répertoires de données (éphémères sur HF Spaces)
RUN mkdir -p data/chroma_db uploads

# HF Spaces impose le port 7860
EXPOSE 7860

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]

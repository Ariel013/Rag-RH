FROM python:3.11-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
COPY RAG/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-télécharger le modèle d'embedding au build (évite le délai au 1er démarrage)
RUN python3 -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Copier le code applicatif (plus de sample_docs — Notion est la source de vérité)
COPY RAG/backend/ ./backend/
COPY RAG/frontend/ ./frontend/

# Répertoire d'uploads temporaires
RUN mkdir -p uploads

# HF Spaces impose le port 7860
EXPOSE 7860

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]

---
title: Assistant RH RAG
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Assistant RH — RAG

Chatbot RH basé sur un pipeline RAG (Retrieval-Augmented Generation).

## Stack technique

- **Backend** : FastAPI + ChromaDB + sentence-transformers
- **LLM** : Groq API (llama-3.1-8b-instant)
- **Embeddings** : paraphrase-multilingual-MiniLM-L12-v2 (multilingue)
- **Frontend** : HTML/CSS/JS vanilla (Tailwind)

## Configuration

Définir les variables d'environnement dans les **Secrets** du Space :

| Variable | Description |
|---|---|
| `OLLAMA_BASE_URL` | `https://api.groq.com/openai/v1` |
| `OLLAMA_MODEL` | `llama-3.1-8b-instant` |
| `GROQ_API_KEY` | Votre clé API Groq |

## Fonctionnalités

- Chat streaming avec l'assistant RH
- Upload de documents (PDF, DOCX, TXT, MD)
- Base de connaissances vectorielle persistante
- Documents samples RH pré-chargés au démarrage

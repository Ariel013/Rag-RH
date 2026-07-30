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

- **Backend** : FastAPI + PostgreSQL/pgvector (Supabase) + fastembed (ONNX local)
- **LLM** : Groq API (llama-3.3-70b-versatile)
- **Embeddings** : paraphrase-multilingual-MiniLM-L12-v2 (multilingue, local via fastembed)
- **Frontend** : HTML/CSS/JS vanilla (Tailwind)

## Configuration

Définir les variables d'environnement dans les **Secrets** du Space (liste complète : `RAG/.env.example`) :

| Variable | Description |
|---|---|
| `DATABASE_URL` | Connexion PostgreSQL (Supabase) |
| `NOTION_TOKEN` / `NOTION_ROOT_PAGE_ID` | Intégration Notion — source de vérité documentaire |
| `OLLAMA_BASE_URL` | `https://api.groq.com/openai/v1` |
| `OLLAMA_MODEL` | `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | Votre clé API Groq |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_TOKEN` | Accès admin |

## Fonctionnalités

- Chat streaming avec l'assistant RH
- Base de connaissances synchronisée automatiquement depuis Notion (source principale)
- Upload de documents complémentaires par l'admin (PDF, DOCX, TXT, MD)
- Base de connaissances vectorielle persistante (PostgreSQL/pgvector)
- Dashboard admin : analytics, topics, questions sans réponse

Documentation complète du fonctionnement du projet : voir [CLAUDE.md](CLAUDE.md).

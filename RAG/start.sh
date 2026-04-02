#!/bin/bash
set -e

echo "=== Assistant RH - Démarrage ==="

# Créer .env depuis l'exemple si absent
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ Fichier .env créé depuis .env.example"
fi

# Charger les variables
export $(grep -v '^#' .env | grep -v '^$' | xargs 2>/dev/null || true)

OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434/v1}"
# URL de base sans /v1 pour les endpoints natifs Ollama
OLLAMA_BASE="${OLLAMA_URL%/v1}"

# Vérifier Ollama uniquement si on utilise une instance locale
if [[ "$OLLAMA_BASE" == *"localhost"* || "$OLLAMA_BASE" == *"127.0.0.1"* ]]; then
    echo "→ Vérification d'Ollama local ($OLLAMA_URL)…"
    if ! curl -sf "$OLLAMA_BASE/api/tags" > /dev/null 2>&1; then
        echo ""
        echo "⚠  Ollama n'est pas démarré !"
        echo "   Lancez-le dans un autre terminal avec : ollama serve"
        echo "   Puis installez le modèle            : ollama pull $OLLAMA_MODEL"
        echo ""
        exit 1
    fi
    if ! curl -sf "$OLLAMA_BASE/api/tags" | grep -q "\"$OLLAMA_MODEL\"" 2>/dev/null; then
        echo "→ Modèle '$OLLAMA_MODEL' non trouvé, téléchargement…"
        ollama pull "$OLLAMA_MODEL"
    fi
    echo "✓ Ollama prêt (modèle : $OLLAMA_MODEL)"
else
    echo "✓ API distante configurée : $OLLAMA_URL (modèle : $OLLAMA_MODEL)"
fi

# Installer les dépendances Python
echo "→ Installation des dépendances Python…"
pip install -r requirements.txt -q

echo "✓ Dépendances installées"
echo "→ Démarrage du serveur sur http://localhost:8000"
echo "  (1er démarrage : téléchargement du modèle d'embedding ~470 MB)"
echo ""

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
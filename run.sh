#!/usr/bin/env bash
# Start the local Ebook RAG web app on http://localhost:8000
set -e
cd "$(dirname "$0")"

if ! curl -sf http://localhost:11434/api/version >/dev/null; then
  echo "Starting Ollama..."; (ollama serve >/dev/null 2>&1 &); sleep 2
fi
for m in "${EMBED_MODEL:-nomic-embed-text}" "${LLM_MODEL:-llama3}"; do
  ollama list | awk '{print $1}' | grep -q "^$m" || ollama pull "$m"
done

[ -d .venv ] || { uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt; }
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"

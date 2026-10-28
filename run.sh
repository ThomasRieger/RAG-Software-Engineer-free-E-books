#!/usr/bin/env bash
# Start the local Ebook RAG web app on http://localhost:8000
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

# Only one server may use data/ at a time (two would both write to the Chroma index).
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -sf "http://localhost:$PORT/api/health" >/dev/null; then
    echo "Ebook RAG is already running at http://localhost:$PORT"
    echo "Stop it with: kill $(lsof -tiTCP:"$PORT" -sTCP:LISTEN)"
  else
    echo "Port $PORT is used by another program. Free it, or run: PORT=8001 ./run.sh"
  fi
  exit 1
fi

if ! curl -sf http://localhost:11434/api/version >/dev/null; then
  echo "Starting Ollama..."; (ollama serve >/dev/null 2>&1 &); sleep 2
fi
for m in "${EMBED_MODEL:-nomic-embed-text}" "${LLM_MODEL:-llama3}"; do
  ollama list | awk '{print $1}' | grep -q "^$m" || ollama pull "$m"
done

[ -d .venv ] || { uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt; }
echo "Ebook RAG: http://localhost:$PORT  (Ctrl+C to stop)"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"

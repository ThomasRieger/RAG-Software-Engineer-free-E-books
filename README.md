# RAG for Software Engineering Ebooks

A private, fully local question-answering system over a library of software engineering, AI and data ebooks. Ask a question in the browser and get an answer grounded in your books, with numbered citations down to the page.

Nothing leaves your machine: the LLM, the embeddings and the vector database all run locally.

| Component      | Choice |
|----------------|--------|
| LLM            | `llama3` (8B) via [Ollama](https://ollama.com) |
| Embeddings     | `nomic-embed-text` via Ollama, used through LangChain `OllamaEmbeddings` |
| Vector DB      | ChromaDB, persisted on disk |
| Orchestration  | LangChain |
| Web app        | FastAPI + plain HTML/JS (no build step) |

## How it works

```
 upload / import ──► loaders.py ──► text splitter ──► nomic-embed-text ──► ChromaDB
 (PDF, EPUB,          page / chapter   1200-char chunks                      data/chroma
  TXT, MD)            metadata         200 overlap

 question ──► nomic-embed-text ──► top-6 similar chunks ──► llama3 + prompt ──► streamed answer
                                   (optionally filtered        with citations [1]..[6]
                                    to selected books)
```

## Requirements

- macOS or Linux, about 8 GB RAM free for llama3
- [Ollama](https://ollama.com/download)
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- About 6 GB of disk: models 5 GB, plus the books, index and uploaded copies

## Quick start

```bash
git clone git@github.com:ThomasRieger/RAG-Software-Engineer-free-E-books.git
cd RAG-Software-Engineer-free-E-books
./run.sh          # starts Ollama, pulls missing models, creates .venv, serves the app
```

Open **http://localhost:8000**. The first start downloads llama3 (4.7 GB) and nomic-embed-text (274 MB).

The search index isn't stored in git. On a fresh clone, rebuild it from the books in `sources/` (with the server running, in a second terminal):

```bash
.venv/bin/python import_folder.py sources
```

Indexing the full library takes several minutes to an hour on a laptop, one book at a time. Each book becomes searchable as soon as it finishes, and you can follow progress in the **Library** tab.

## Using the app

- **Ask** tab: chat with your books. Answers stream in with citations like `[1]`; expand **sources** under an answer to read the retrieved passages, with book title and page or chapter. With two or more books indexed, chips at the top limit a search to specific books. ⟲ starts a new conversation, and the last few turns are sent as context for follow-up questions.
- **Library** tab: drag and drop PDF, EPUB, TXT or MD files anywhere on the page, or click to browse. Each book shows its indexing progress and chunk count; × deletes the book and its vectors. Re-uploading an identical file is detected by SHA-256 hash and skipped.
- The dot at the top right shows Ollama and model status.

## The library (`sources/`)

109 books, organized by subject:

| Folder | Books | Covers |
|---|---:|---|
| `AI Engineering and LLMs/` | 21 | Building LLM apps, RAG, prompt engineering, fine-tuning, LangChain, AI governance |
| `AI Agents/` | 7 | Agent design, AgentOps, running agents in production |
| `MLOps and ML Systems/` | 12 | ML system design, MLOps / LLMOps, MLflow, feature stores, GenAI on Kubernetes |
| `Machine Learning and Deep Learning/` | 9 | Scikit-Learn, TensorFlow, deep learning fundamentals, GANs, contrastive learning |
| `NLP/` | 9 | Classic and transformer-based NLP, NLTK, annotation |
| `Data Science and Statistics/` | 9 | pandas / NumPy, statistics, data mining, visualization |
| `Data Engineering and Lakehouse/` | 19 | Spark, Delta Lake, ETL pipelines, lakehouse architecture, governance, database internals |
| `Software Engineering/` | 4 | Design patterns (GoF), FastAPI, Python for DevOps, serverless on AWS |
| `Research Papers/` | 15 | BART, Codex, DeBERTaV3, Sleeper Agents, LLM-as-a-Judge, Graph RAG survey, benchmarks |
| `Research Skills/` | 4 | Reading and writing research papers |

Files are named `Title - Author (Publisher).pdf`, and papers `Title (arXiv ID).pdf`. **The filename is the book's title in the app** (library list and citations). Only when a filename has no spaces, like `2408.08921v1.pdf` or `big-book-agentops.pdf`, does the app fall back to the title embedded in the PDF.

To add books, either drop them into the web UI, or save them under `sources/<Subject>/` with a descriptive name and run `.venv/bin/python import_folder.py sources`; books already in the library are skipped. Only `sources/` is kept in git. The app stores its own copies in `data/`, which is not committed, so to keep the two in sync, add books through `sources/`.

**Known issue:** `Exploratory Data Analysis with R (scanned).pdf` has no text layer, so it can't be indexed until it's OCR'd (`brew install ocrmypdf && ocrmypdf in.pdf out.pdf`).

## Scripts

### `import_folder.py`: bulk import

```bash
.venv/bin/python import_folder.py <folder> [--url http://localhost:8000]
```

Uploads every PDF, EPUB, TXT and MD file under the folder (recursively, skipping README files) to the running server, which indexes them in the background. It's safe to run repeatedly because duplicates are skipped. It goes through the server's API because Chroma doesn't support two processes writing to the same store.

### `fetch_databricks.py`: download Databricks ebooks

Databricks ebooks are behind a sign-up form. This script opens each ebook page in a headless Chromium (Playwright), fills the form with your details, and saves the PDF into the matching `sources/<Subject>/` folder. Web-only ebooks are saved as Markdown.

One-time setup:

```bash
.venv/bin/playwright install chromium
cat > .env <<'EOF'
DBX_FIRST_NAME=...
DBX_LAST_NAME=...
DBX_EMAIL=...
DBX_COMPANY=...
DBX_JOB_TITLE=...
DBX_COUNTRY=...
DBX_PHONE=...
EOF
```

```bash
.venv/bin/python fetch_databricks.py --list     # engineering-topic ebooks only (default filter)
.venv/bin/python fetch_databricks.py            # download them (skips ones already done)
.venv/bin/python fetch_databricks.py --retry    # retry failures
.venv/bin/python fetch_databricks.py --all      # every ebook (~190)
.venv/bin/python fetch_databricks.py URL ...    # specific ebook pages
.venv/bin/python import_folder.py sources       # index the new ones (existing books are skipped)
```

Each download goes straight into the matching subject folder (AI Agents, AI Engineering and LLMs, MLOps and ML Systems, or Data Engineering and Lakehouse), chosen from keywords in the ebook's URL. It's named `<Title> (Databricks).pdf`, using the PDF's embedded title or, when that's missing, the URL slug; check the names afterwards and tidy them if needed. If the same PDF is already somewhere in `sources/`, the download is discarded. Every form submission registers you as a Databricks sales lead. Progress is tracked in `data/databricks_state.json`, so ebooks you already have aren't downloaded again. Some older assets are retired and land on a generic "thank you" page; the script reports those as failed.

## Configuration

Set these as environment variables, e.g. `LLM_MODEL=llama3.1:8b ./run.sh`.

| Variable | Default | Notes |
|---|---|---|
| `LLM_MODEL` | `llama3` | Any Ollama chat model. `llama3.1:8b` has a 128k context window. |
| `EMBED_MODEL` | `nomic-embed-text` | Changing it requires re-indexing: delete `data/` and re-import. |
| `TOP_K` | `6` | Passages retrieved per question |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | In characters; applies to newly indexed books |
| `NUM_CTX` | `8192` | LLM context window (tokens) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `RAG_DATA_DIR` | `./data` | Where uploads, manifest and index are stored |
| `PORT` | `8000` | |

## Project layout

```
app/
  config.py        settings (env vars above)
  loaders.py       PDF / EPUB / TXT / MD → LangChain Documents with page / chapter metadata
  rag.py           library manifest, background ingestion into Chroma, retrieval, streaming answers
  main.py          FastAPI routes
  static/          web UI (index.html, app.js, style.css)
import_folder.py   bulk import a folder into the running server
fetch_databricks.py  Databricks ebook downloader
run.sh             one-command start
sources/           the ebook library (committed)
data/              runtime state, git-ignored:
  books/           copies of uploaded files
  books.json       library manifest (status, progress, chunk counts)
  chroma/          vector index
  server.log
```

## API

| Method | Path | |
|---|---|---|
| `GET` | `/api/health` | Ollama and model availability |
| `GET` | `/api/books` | Library with indexing status |
| `POST` | `/api/books` | Multipart upload (`files`) |
| `DELETE` | `/api/books/{id}` | Remove a book and its vectors |
| `POST` | `/api/ask` | `{"question", "history"?, "book_ids"?}` → NDJSON stream: one `sources` event, then `token` events |

## Troubleshooting

- **Red status dot / "missing model":** run `ollama serve`, then `ollama pull llama3 nomic-embed-text`.
- **Book shows "error":** usually a scanned PDF with no text, so OCR it first. Delete the entry and re-upload once it's fixed.
- **First answer is slow (~30–40 s):** llama3 is loading into memory; later answers start within a few seconds.
- **Server restarted mid-indexing:** interrupted books are re-queued automatically on startup.
- **Reset everything:** stop the server, `rm -rf data/`, start it, and re-run `import_folder.py sources`.

## Notes

This repository holds third-party ebooks for personal study and must stay **private**. Don't make it public or redistribute the books.

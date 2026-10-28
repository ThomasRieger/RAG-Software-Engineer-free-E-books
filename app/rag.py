"""Library manifest, ingestion into Chroma, and retrieval-augmented answering."""
import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

from langchain_chroma import Chroma
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config
from .loaders import load_book

# ---------------------------------------------------------------- manifest

_lock = threading.Lock()


def _read_manifest() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text())
    return {}


def _write_manifest(data: dict) -> None:
    tmp = config.MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(config.MANIFEST_PATH)


def _update_book(book_id: str, **fields) -> None:
    with _lock:
        data = _read_manifest()
        if book_id in data:
            data[book_id].update(fields)
            _write_manifest(data)


def list_books() -> list[dict]:
    with _lock:
        books = list(_read_manifest().values())
    return sorted(books, key=lambda b: b["added_at"], reverse=True)


def recover_interrupted() -> None:
    """Re-queue books that were mid-ingestion when the server stopped."""
    for book in list_books():
        if book["status"] in ("queued", "processing"):
            _delete_vectors(book["id"])
            _update_book(book["id"], status="queued", progress=0)
            _executor.submit(_ingest, book["id"])


# ---------------------------------------------------------------- vector store

_embeddings = OllamaEmbeddings(model=config.EMBED_MODEL, base_url=config.OLLAMA_BASE_URL)
_store = Chroma(
    collection_name=config.COLLECTION_NAME,
    embedding_function=_embeddings,
    persist_directory=str(config.CHROMA_DIR),
    collection_metadata={"hnsw:space": "cosine"},
)
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
)
_executor = ThreadPoolExecutor(max_workers=1)  # ingest one book at a time


def _delete_vectors(book_id: str) -> None:
    ids = _store.get(where={"book_id": book_id}, include=[])["ids"]
    for i in range(0, len(ids), 5000):
        _store.delete(ids=ids[i : i + 5000])


# ---------------------------------------------------------------- ingestion


def add_book(filename: str, content: bytes) -> dict:
    """Save an uploaded file and queue it for ingestion. Returns the manifest entry."""
    digest = hashlib.sha256(content).hexdigest()
    with _lock:
        data = _read_manifest()
        for book in data.values():
            if book["sha256"] == digest:
                return {**book, "duplicate": True}

        book_id = uuid.uuid4().hex[:12]
        safe_name = Path(filename).name.replace("/", "_")
        path = config.BOOKS_DIR / f"{book_id}_{safe_name}"
        path.write_bytes(content)
        book = {
            "id": book_id,
            "filename": safe_name,
            "title": Path(safe_name).stem,
            "path": str(path),
            "sha256": digest,
            "size": len(content),
            "status": "queued",
            "progress": 0,
            "chunks": 0,
            "error": None,
            "added_at": time.time(),
        }
        data[book_id] = book
        _write_manifest(data)

    _executor.submit(_ingest, book_id)
    return book


def _ingest(book_id: str) -> None:
    book = _read_manifest().get(book_id)
    if not book:
        return
    try:
        _update_book(book_id, status="processing", progress=0)
        pages, embedded_title = load_book(Path(book["path"]))
        # The filename is the title, unless it looks like an ID or slug ("2408.08921v1", "big-book-agentops")
        title = book["title"] if " " in book["title"] or not embedded_title else embedded_title.strip()
        for p in pages:
            p.metadata.update(book_id=book_id, title=title, filename=book["filename"])
        chunks = _splitter.split_documents(pages)
        if not chunks:
            raise ValueError("No extractable text found (scanned PDF? try OCR first).")
        _update_book(book_id, title=title)

        batch = 64
        for i in range(0, len(chunks), batch):
            if book_id not in _read_manifest():  # deleted mid-ingest
                _delete_vectors(book_id)
                return
            part = chunks[i : i + batch]
            ids = [f"{book_id}-{i + j}" for j in range(len(part))]
            _store.add_documents(part, ids=ids)
            _update_book(book_id, progress=round(100 * (i + len(part)) / len(chunks)))

        if book_id not in _read_manifest():
            _delete_vectors(book_id)
            return
        _update_book(book_id, status="ready", progress=100, chunks=len(chunks))
    except Exception as e:  # surface the error in the UI
        _update_book(book_id, status="error", error=str(e))


def delete_book(book_id: str) -> bool:
    with _lock:
        data = _read_manifest()
        book = data.pop(book_id, None)
        if not book:
            return False
        _write_manifest(data)
    _delete_vectors(book_id)
    Path(book["path"]).unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------- answering

SYSTEM_PROMPT = """You are a senior software engineer and a helpful study assistant. \
Answer the user's question using the excerpts from their software engineering ebooks below.

Rules:
- Base your answer on the excerpts. If they don't contain the answer, say so plainly, \
then give your best general knowledge answer and label it as such.
- Cite sources inline like [1], [2] matching the excerpt numbers.
- Use Markdown. Put code in fenced code blocks with a language tag.
- Be concise and practical."""


def _llm() -> ChatOllama:
    return ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0.2,
        num_ctx=config.NUM_CTX,
    )


def retrieve(question: str, book_ids: list[str] | None = None, k: int = config.TOP_K):
    where = {"book_id": {"$in": book_ids}} if book_ids else None
    results = _store.similarity_search_with_relevance_scores(question, k=k, filter=where)
    sources = []
    for doc, score in results:
        m = doc.metadata
        location = f"p. {m['page']}" if "page" in m else m.get("chapter") or (
            f"section {m['section']}" if "section" in m else ""
        )
        sources.append(
            {
                "book_id": m.get("book_id"),
                "title": m.get("title", m.get("filename", "Unknown")),
                "location": location,
                "score": round(score, 3),
                "text": doc.page_content,
            }
        )
    return sources


def answer_stream(
    question: str, history: list[dict] | None = None, book_ids: list[str] | None = None
) -> Iterator[dict]:
    """Yields {"type": "sources", ...} once, then {"type": "token", ...} events."""
    sources = retrieve(question, book_ids)
    yield {"type": "sources", "sources": sources}

    if sources:
        context = "\n\n".join(
            f"[{i}] {s['title']} ({s['location']})\n{s['text']}"
            for i, s in enumerate(sources, start=1)
        )
    else:
        context = "(No matching excerpts — the library may be empty.)"

    messages = [SystemMessage(SYSTEM_PROMPT)]
    for turn in (history or [])[-6:]:
        cls = HumanMessage if turn.get("role") == "user" else AIMessage
        messages.append(cls(turn.get("content", "")))
    messages.append(HumanMessage(f"Excerpts:\n\n{context}\n\n---\nQuestion: {question}"))

    for chunk in _llm().stream(messages):
        if chunk.content:
            yield {"type": "token", "content": chunk.content}


def health() -> dict:
    import httpx

    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = {m["name"] for m in r.json().get("models", [])}
        ok = lambda name: any(m == name or m.startswith(name + ":") for m in models)  # noqa: E731
        return {
            "ollama": True,
            "llm": {"name": config.LLM_MODEL, "available": ok(config.LLM_MODEL)},
            "embeddings": {"name": config.EMBED_MODEL, "available": ok(config.EMBED_MODEL)},
        }
    except Exception:
        return {"ollama": False, "llm": {"name": config.LLM_MODEL, "available": False},
                "embeddings": {"name": config.EMBED_MODEL, "available": False}}

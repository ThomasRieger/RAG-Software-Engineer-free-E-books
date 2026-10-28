import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, dbview, rag

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    rag.recover_interrupted()
    yield


app = FastAPI(title="Ebook RAG", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return rag.health()


@app.get("/api/books")
def books():
    return rag.list_books()


@app.post("/api/books")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in config.SUPPORTED_EXTENSIONS:
            results.append({"filename": f.filename, "error": f"Unsupported type {ext or '?'}"})
            continue
        results.append(rag.add_book(f.filename, await f.read()))
    return results


@app.delete("/api/books/{book_id}")
def delete(book_id: str):
    if not rag.delete_book(book_id):
        raise HTTPException(404, "Book not found")
    return {"ok": True}


@app.get("/api/index")
def index_stats():
    return rag.index_stats()


@app.get("/api/chunks")
def chunks(book_id: str | None = None, q: str | None = None, offset: int = 0, limit: int = 50):
    return rag.list_chunks(book_id, q.strip() if q else None, max(offset, 0), min(max(limit, 1), 200))


@app.get("/api/chunks/{chunk_id}/embedding")
def chunk_embedding(chunk_id: str):
    vector = rag.chunk_embedding(chunk_id)
    if vector is None:
        raise HTTPException(404, "Chunk not found")
    return {"id": chunk_id, "dimensions": len(vector), "embedding": vector}


@app.get("/api/db/tables")
def db_tables():
    return dbview.tables()


@app.get("/api/db/tables/{name}")
def db_table_rows(name: str, offset: int = 0, limit: int = 100):
    result = dbview.table_rows(name, max(offset, 0), min(max(limit, 1), 500))
    if result is None:
        raise HTTPException(404, "No such table")
    return result


@app.get("/api/db/files")
def db_files():
    return dbview.files()


class AskRequest(BaseModel):
    question: str
    history: list[dict] = []
    book_ids: list[str] = []


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty")

    def events():
        try:
            for event in rag.answer_stream(req.question, req.history, req.book_ids or None):
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")

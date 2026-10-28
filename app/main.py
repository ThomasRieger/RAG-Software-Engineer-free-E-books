import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, rag

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

"""Read-only raw view of the Chroma SQLite database and the files next to it."""
import sqlite3

from . import config

SQLITE_PATH = config.CHROMA_DIR / "chroma.sqlite3"
MAX_CELL = 2000  # characters per cell sent to the browser


def _connect() -> sqlite3.Connection:
    # mode=ro: this connection can never write, so browsing can't damage the index
    return sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)


def _cell(value):
    if isinstance(value, bytes):
        return f"<{len(value):,} bytes> {value[:24].hex()}{'…' if len(value) > 24 else ''}"
    if isinstance(value, str) and len(value) > MAX_CELL:
        return value[:MAX_CELL] + f"… (+{len(value) - MAX_CELL:,} chars)"
    return value


def tables() -> list[dict]:
    with _connect() as db:
        rows = db.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
        out = []
        for name, kind in rows:
            count = db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            columns = [c[1] for c in db.execute(f'PRAGMA table_info("{name}")')]
            out.append({"name": name, "type": kind, "rows": count, "columns": columns})
    return out


def table_rows(name: str, offset: int = 0, limit: int = 100) -> dict | None:
    with _connect() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (name,)
        ).fetchone()
        if not exists:  # only names that really exist are put into SQL below
            return None
        total = db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        cur = db.execute(f'SELECT * FROM "{name}" LIMIT ? OFFSET ?', (limit, offset))
        columns = [d[0] for d in cur.description]
        rows = [[_cell(v) for v in row] for row in cur.fetchall()]
    return {"name": name, "total": total, "offset": offset, "columns": columns, "rows": rows}


def files() -> list[dict]:
    return [
        {"path": str(f.relative_to(config.CHROMA_DIR)), "bytes": f.stat().st_size}
        for f in sorted(config.CHROMA_DIR.rglob("*"))
        if f.is_file()
    ]

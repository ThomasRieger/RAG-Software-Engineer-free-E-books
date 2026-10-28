"""Bulk-upload every ebook in a folder (recursively) to the running Ebook RAG server.

Usage: .venv/bin/python import_folder.py <folder> [--url http://localhost:8000]
"""
import argparse
import sys
from pathlib import Path

import httpx

from app.config import SUPPORTED_EXTENSIONS


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("folder", type=Path)
    p.add_argument("--url", default="http://localhost:8000")
    args = p.parse_args()

    files = sorted(
        f for f in args.folder.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS and ".git" not in f.parts
        and f.name.lower() != "readme.md"
    )
    if not files:
        sys.exit(f"No {', '.join(sorted(SUPPORTED_EXTENSIONS))} files found in {args.folder}")

    print(f"Uploading {len(files)} file(s) to {args.url}")
    with httpx.Client(base_url=args.url, timeout=300) as client:
        for i, f in enumerate(files, 1):
            with f.open("rb") as fh:
                r = client.post("/api/books", files={"files": (f.name, fh)})
            r.raise_for_status()
            res = r.json()[0]
            note = res.get("error") or ("already in library" if res.get("duplicate") else "queued")
            print(f"[{i}/{len(files)}] {f.name}: {note}")
    print("Done. Indexing continues in the background; watch progress in the Library tab.")


if __name__ == "__main__":
    main()

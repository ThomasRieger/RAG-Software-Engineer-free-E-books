"""Turn ebook files into LangChain Documents (one per page / chapter)."""
import re
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from langchain_core.documents import Document

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def _clean(text: str) -> str:
    text = text.replace("\x00", "").encode("utf-8", "ignore").decode("utf-8")  # drop lone surrogates
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_pdf(path: Path) -> tuple[list[Document], str | None]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    title = (reader.metadata.title if reader.metadata else None) or None
    docs = []
    for i, page in enumerate(reader.pages):
        try:
            text = _clean(page.extract_text() or "")
        except Exception:
            continue
        if text:
            docs.append(Document(page_content=text, metadata={"page": i + 1}))
    return docs, title


def load_epub(path: Path) -> tuple[list[Document], str | None]:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    titles = book.get_metadata("DC", "title")
    title = titles[0][0] if titles else None
    docs = []
    for n, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), start=1):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        heading = soup.find(["h1", "h2", "h3"])
        text = _clean(soup.get_text("\n"))
        if len(text) < 50:
            continue
        meta = {"section": n}
        if heading and heading.get_text(strip=True):
            meta["chapter"] = heading.get_text(strip=True)[:200]
        docs.append(Document(page_content=text, metadata=meta))
    return docs, title


def load_text(path: Path) -> tuple[list[Document], str | None]:
    text = _clean(path.read_text(encoding="utf-8", errors="ignore"))
    return [Document(page_content=text, metadata={})], None


LOADERS = {".pdf": load_pdf, ".epub": load_epub, ".txt": load_text, ".md": load_text}


def load_book(path: Path) -> tuple[list[Document], str | None]:
    return LOADERS[path.suffix.lower()](path)

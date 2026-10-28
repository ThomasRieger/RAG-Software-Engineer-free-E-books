"""Download Databricks ebooks by filling their sign-up form with your details (from .env).

Usage:
  .venv/bin/python fetch_databricks.py --list                 # show which ebooks match the filter
  .venv/bin/python fetch_databricks.py                        # download the filtered set
  .venv/bin/python fetch_databricks.py --all                  # download every ebook
  .venv/bin/python fetch_databricks.py URL [URL ...]          # download specific ebook pages
Each ebook is saved straight into the matching sources/<Subject>/ folder as "<Title> (Databricks).pdf".
Then index them with: .venv/bin/python import_folder.py sources
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent
SOURCES = BASE / "sources"
TMP_DIR = BASE / "data" / "downloads"
STATE_FILE = BASE / "data" / "databricks_state.json"
SITEMAP_INDEX = "https://www.databricks.com/en-resources-assets/sitemap/sitemap-index.xml"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Engineering-relevant topics; anything matching SKIP (marketing, industry briefs) is dropped.
INCLUDE = re.compile(
    r"spark|delta|lakehouse|data-engineer|etl|pipeline|mlops|llmops|machine-learning|\bml\b|"
    r"llm|genai|generative|rag|agent|streaming|sql|architect|pattern|oreilly|definitive|"
    r"guide|feature-store|python|scala|unity-catalog|governance|apps|ai-",
    re.I,
)
SKIP = re.compile(
    r"survey|report|state-of|request-access|roi|tco|forrester|gartner|idc|cio|ceo|executive|"
    r"retail|healthcare|financial-services|banking|insurance|public-sector|manufacturing|"
    r"media|telecom|energy|life-sciences|migration-guide|partner|emea|leaders|martech|defense|"
    r"security|value|success|maturity|buyer|wisdom|potential|redefine|power-|optimize|how-|"
    r"future|unseen|missing-layer|strategies|google-cloud|aws|azure|hls|clinical|marketing|"
    r"transformation|"
    r"-form$|-track$|-asset\d+",  # duplicate landing pages for the same asset
    re.I,
)


# Subject folder by slug keywords; first match wins.
SUBJECTS = [
    (r"agent", "AI Agents"),
    (r"ai-governance|genai|gen-ai|generative|llm|rag\b|prompt", "AI Engineering and LLMs"),
    (r"mlops|mlflow|machine-learning|\bml\b|feature-store", "MLOps and ML Systems"),
    (r"spark|delta|lakehouse|etl|data-engineer|pipeline|governance|sql|warehouse|data-sharing|apps",
     "Data Engineering and Lakehouse"),
]
DEFAULT_SUBJECT = "AI Engineering and LLMs"


def subject_for(slug: str) -> str:
    return next((folder for pattern, folder in SUBJECTS if re.search(pattern, slug, re.I)), DEFAULT_SUBJECT)


def title_for(path: Path, slug: str) -> str:
    title = ""
    if path.suffix == ".pdf":
        try:
            title = ((PdfReader(str(path)).metadata or {}).get("/Title") or "").strip()
        except Exception:
            pass
    if len(title) < 8 or " " not in title or "databricks" in title.lower():  # missing or junk metadata
        title = slug.replace("-", " ").strip().capitalize()
    return re.sub(r'[/\\:*?"<>|]', "", title)[:150]


def file_into_sources(tmp: Path, slug: str) -> tuple[str, str]:
    """Move a downloaded file into its subject folder, unless the same file is already in sources/."""
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    for existing in SOURCES.rglob(f"*{tmp.suffix}"):
        if hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
            tmp.unlink()
            return "ok", f"duplicate of {existing.relative_to(SOURCES)}"
    dest = SOURCES / subject_for(slug) / f"{title_for(tmp, slug)} (Databricks){tmp.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.rename(dest)
    return "ok", str(dest.relative_to(SOURCES))


def ebook_urls() -> list[str]:
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as c:
        maps = re.findall(r"<loc>([^<]+)</loc>", c.get(SITEMAP_INDEX).text)
        urls = set()
        for m in maps:
            urls |= set(re.findall(r"<loc>(https://www\.databricks\.com/resources/ebook/[^<]+)</loc>", c.get(m).text))
    return sorted(urls)


def wanted(url: str) -> bool:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return bool(INCLUDE.search(slug)) and not SKIP.search(slug)


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fill_form(page, me: dict) -> None:
    form = page.locator("form.mktoForm").first
    form.wait_for(timeout=45000)
    page.wait_for_selector("form.mktoForm input[name=Email]", timeout=45000)
    for name, value in [
        ("FirstName", me["first"]), ("LastName", me["last"]), ("Email", me["email"]),
        ("Company", me["company"]), ("Title", me["title"]), ("Phone", me["phone"]),
    ]:
        field = form.locator(f"input[name={name}]")
        if field.count():
            field.fill(value)
    country = form.locator("select[name=Country]")
    if country.count():
        country.select_option(label=me["country"])
    page.wait_for_timeout(500)  # Marketo may reveal extra fields after country is chosen
    form.locator("button[type=submit], button.mktoButton").first.click()


def _hrefs(page) -> list[str]:
    try:
        return page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    except PWError:  # page is mid-navigation
        return []


def download(page, url: str, me: dict, dest: Path) -> tuple[str, str]:
    """Returns (status, detail). status: ok | email | failed."""
    pdf_urls: list[str] = []
    page.on("response", lambda r: pdf_urls.append(r.url)
            if "application/pdf" in (r.headers.get("content-type") or "") else None)

    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.context.on("page", lambda p: p.on("download", lambda d: downloads.append(d)))

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
    except PWError as e:
        if "Download is starting" not in str(e):  # some ungated ebooks download straight away
            raise
        for _ in range(20):
            if downloads:
                break
            page.wait_for_timeout(500)
    if not downloads:
        if "/resources/ebook/" not in page.url:
            return "failed", f"page redirected to {page.url}"
        fill_form(page, me)

    # Wait for whatever the site does after submit: a download, a PDF tab, or a thank-you page.
    for _ in range(40):
        page.wait_for_timeout(500)
        if downloads or pdf_urls:
            break
        links = [l for p in page.context.pages for l in _hrefs(p) if re.search(r"\.pdf($|\?)", l, re.I)]
        if links:
            pdf_urls.extend(links)
            break

    if downloads:
        downloads[0].save_as(dest)
        return "ok", downloads[0].suggested_filename
    if pdf_urls:
        r = httpx.get(pdf_urls[0], headers={"User-Agent": UA}, follow_redirects=True, timeout=120)
        if r.is_success and r.content[:4] == b"%PDF":
            dest.write_bytes(r.content)
            return "ok", pdf_urls[0]
        return "failed", f"PDF link {pdf_urls[0]} returned {r.status_code}"

    page.wait_for_load_state("domcontentloaded")
    # Some ebooks are web-only: the "thank you" page renders the content itself. Save it as Markdown.
    if re.search(r"/resources/ebook/[^/]+/(content|thank-you)", page.url):
        page.wait_for_timeout(3000)
        body = page.locator("main").first if page.locator("main").count() else page.locator("body")
        text = body.inner_text()
        if len(text) > 3000:
            dest.with_suffix(".md").write_text(f"# {page.title()}\n\nSource: {page.url}\n\n{text}")
            return "ok", "web-only ebook saved as Markdown"
    text = " ".join(p.inner_text("body") for p in page.context.pages)[:20000].lower()
    if re.search(r"check your (e-?mail|inbox)|sent to your (e-?mail|inbox)|we.ve emailed", text):
        return "email", "delivered by email"
    return "failed", f"no PDF found after submit (ended on {page.url})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--all", action="store_true", help="every ebook, not just engineering topics")
    ap.add_argument("--list", action="store_true", help="only print the ebooks that would be fetched")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry", action="store_true", help="retry ebooks that previously failed")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args()

    urls = args.urls or [u for u in ebook_urls() if args.all or wanted(u)]
    if args.list:
        print("\n".join(urls), f"\n{len(urls)} ebooks", sep="")
        return

    load_dotenv(BASE / ".env")
    keys = dict(first="DBX_FIRST_NAME", last="DBX_LAST_NAME", email="DBX_EMAIL", company="DBX_COMPANY",
                title="DBX_JOB_TITLE", country="DBX_COUNTRY", phone="DBX_PHONE")
    me = {k: os.getenv(v, "") for k, v in keys.items()}
    if missing := [keys[k] for k, v in me.items() if not v]:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    todo = [u for u in urls if state.get(u, {}).get("status") not in ({"ok", "email"} if args.retry else {"ok", "email", "failed"})]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} to fetch ({len(urls) - len(todo)} already done) -> {SOURCES}/<Subject>/")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        for i, url in enumerate(todo, 1):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            ctx = browser.new_context(user_agent=UA, accept_downloads=True)
            tmp = TMP_DIR / f"{slug}.pdf"
            try:
                status, detail = download(ctx.new_page(), url, me, tmp)
                saved = next((f for f in (tmp, tmp.with_suffix(".md")) if f.exists()), None)
                if status == "ok" and saved:
                    status, detail = file_into_sources(saved, slug)
            except PWError as e:
                status, detail = "failed", str(e).splitlines()[0]
            finally:
                ctx.close()
            state[url] = {"status": status, "detail": detail}
            save_state(state)
            print(f"[{i}/{len(todo)}] {status:6} {slug}  {detail}")
        browser.close()

    by = {s: [u for u, v in state.items() if v["status"] == s] for s in ("ok", "email", "failed")}
    print(f"\nok: {len(by['ok'])}  emailed: {len(by['email'])}  failed: {len(by['failed'])}")
    if by["email"]:
        print("Emailed to you; save these PDFs into the matching sources/<Subject>/ folder:\n  "
              + "\n  ".join(by["email"]))


if __name__ == "__main__":
    main()

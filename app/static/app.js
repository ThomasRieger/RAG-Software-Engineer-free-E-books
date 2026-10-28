const $ = (s) => document.querySelector(s);
const state = { books: [], history: [], busy: false };

// ------------------------------------------------------------------ helpers
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 3000);
}

// Small Markdown renderer: fenced code, inline code, headings, lists, bold/italic, links.
function md(src) {
  const blocks = [];
  src = src.replace(/```(\w*)\n?([\s\S]*?)(```|$)/g, (_, lang, code) => {
    blocks.push(`<pre><code class="lang-${esc(lang)}">${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of src.split("\n")) {
    let m;
    if ((m = line.match(/^\u0000(\d+)\u0000$/))) { closeList(); out.push(blocks[m[1]]); }
    else if ((m = line.match(/^(#{1,4})\s+(.*)/))) { closeList(); out.push(`<h${m[1].length + 2}>${inline(m[2])}</h${m[1].length + 2}>`); }
    else if ((m = line.match(/^\s*[-*+]\s+(.*)/))) { if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (!line.trim()) { closeList(); }
    else { closeList(); out.push(`<p>${inline(line)}</p>`); }
  }
  closeList();
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
}

// ------------------------------------------------------------------ tabs
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab, .view").forEach((el) => el.classList.remove("active"));
    tab.classList.add("active");
    $(`#view-${tab.dataset.view}`).classList.add("active");
    if (tab.dataset.view === "explore") openExplore();
  })
);

// ------------------------------------------------------------------ health
async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const el = $("#health");
    $("#llm-name").textContent = h.llm.name;
    if (!h.ollama) { el.className = "health bad"; el.textContent = "● Ollama not running"; }
    else if (!h.llm.available || !h.embeddings.available) {
      const missing = [h.llm, h.embeddings].filter((m) => !m.available).map((m) => m.name).join(", ");
      el.className = "health bad"; el.textContent = `● missing model: ${missing}`;
    } else { el.className = "health ok"; el.textContent = `● ${h.llm.name} · ${h.embeddings.name}`; }
  } catch { $("#health").className = "health bad"; }
}

// ------------------------------------------------------------------ library
async function loadBooks() {
  state.books = await (await fetch("/api/books")).json();
  renderBooks();
  renderLibSize();
  if (state.books.some((b) => b.status === "queued" || b.status === "processing")) {
    clearTimeout(loadBooks._t);
    loadBooks._t = setTimeout(loadBooks, 1500);
  }
}

function renderBooks() {
  $("#book-count").textContent = state.books.filter((b) => b.status === "ready").length;
  const el = $("#books");
  if (!state.books.length) { el.innerHTML = '<p class="muted" style="text-align:center">No ebooks yet.</p>'; return; }
  el.innerHTML = state.books.map((b) => `
    <div class="book">
      <div>
        <div class="title" title="${esc(b.filename)}">${esc(b.title)}</div>
        <div class="meta">${esc(b.filename)} · ${(b.size / 1048576).toFixed(1)} MB${b.chunks ? ` · ${b.chunks} chunks` : ""}</div>
      </div>
      <div>
        <span class="status ${b.status}">${b.status === "processing" ? `indexing ${b.progress}%` : b.status}</span>
        <button class="del" data-id="${b.id}" title="Delete">×</button>
      </div>
      ${b.status === "processing" || b.status === "queued" ? `<div class="bar"><div style="width:${b.progress}%"></div></div>` : ""}
      ${b.error ? `<div class="err">${esc(b.error)}</div>` : ""}
    </div>`).join("");
}

$("#books").addEventListener("click", async (e) => {
  const id = e.target.dataset?.id;
  if (!id) return;
  const book = state.books.find((b) => b.id === id);
  if (!confirm(`Delete "${book.title}" and its vectors?`)) return;
  await fetch(`/api/books/${id}`, { method: "DELETE" });
  loadBooks();
});

async function upload(files) {
  if (!files.length) return;
  const form = new FormData();
  for (const f of files) form.append("files", f);
  toast(`Uploading ${files.length} file(s)…`);
  const res = await fetch("/api/books", { method: "POST", body: form });
  const results = await res.json();
  const msgs = results.map((r) => r.error ? `${r.filename}: ${r.error}` : r.duplicate ? `${r.filename}: already in library` : null).filter(Boolean);
  toast(msgs.length ? msgs.join(" · ") : `Queued ${results.length} ebook(s) for indexing`);
  loadBooks();
}

const dz = $("#dropzone");
$("#file-input").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => upload([...e.dataTransfer.files]));
// Dropping anywhere on the page also works
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => { e.preventDefault(); if (!dz.contains(e.target)) upload([...e.dataTransfer.files]); });

// ------------------------------------------------------------------ greeting
function renderLibSize() {
  const n = state.books.filter((b) => b.status === "ready").length;
  $("#lib-size").textContent = `your ${n} book${n === 1 ? "" : "s"}`;
}

// ------------------------------------------------------------------ chat
const q = $("#question");
q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = q.scrollHeight + "px"; });
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); } });
document.querySelectorAll(".suggestions button").forEach((b) => b.addEventListener("click", () => { q.value = b.textContent; $("#ask-form").requestSubmit(); }));
$("#clear").addEventListener("click", () => {
  state.history = [];
  $("#chat").querySelectorAll(".msg").forEach((m) => m.remove());
  $("#chat-empty").style.display = "";
});

function addMsg(role, html) {
  $("#chat-empty").style.display = "none";
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  msg.innerHTML = role === "bot"
    ? `<div class="avatar">AI</div><div class="body"><div class="bubble">${html}</div></div>`
    : `<div class="bubble">${html}</div>`;
  $("#chat").appendChild(msg);
  msg.scrollIntoView({ block: "end" });
  return msg;
}

function renderSources(msg, sources) {
  if (!sources.length) return;
  const d = document.createElement("details");
  d.className = "sources";
  d.innerHTML = `<summary>${sources.length} sources</summary>` + sources.map((s, i) => `
    <div class="source" onclick="this.classList.toggle('open')">
      <div class="head">[${i + 1}] ${esc(s.title)} <span>${esc(s.location || "")} · relevance ${s.score}</span></div>
      <div class="text">${esc(s.text)}</div>
    </div>`).join("");
  msg.querySelector(".body").appendChild(d);
}

$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = q.value.trim();
  if (!question || state.busy) return;
  state.busy = true;
  $("#send").disabled = true;
  q.value = ""; q.style.height = "auto";

  addMsg("user", esc(question));
  const msg = addMsg("bot", '<span class="dots"><i></i><i></i><i></i></span>');
  const bubble = msg.querySelector(".bubble");
  bubble.classList.add("typing");
  let answer = "";
  const chat = $("#chat");

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: state.history }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let sources = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "sources") sources = ev.sources;
        else if (ev.type === "token") {
          answer += ev.content;
          const atBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 60;
          bubble.innerHTML = md(answer);
          if (atBottom) chat.scrollTop = chat.scrollHeight;
        } else if (ev.type === "error") throw new Error(ev.message);
      }
    }
    renderSources(msg, sources);
    state.history.push({ role: "user", content: question }, { role: "assistant", content: answer });
  } catch (err) {
    bubble.innerHTML = md(answer) + `<p style="color:var(--err)">⚠ ${esc(err.message)}</p>`;
  } finally {
    if (bubble.querySelector(".dots")) bubble.innerHTML = '<p class="muted">No answer was generated.</p>';
    bubble.classList.remove("typing");
    state.busy = false;
    $("#send").disabled = false;
    q.focus();
  }
});

// ------------------------------------------------------------------ explore (read-only view of the index)
const ix = { bookId: null, q: "", offset: 0, loaded: false, req: 0 };
const PAGE = 50;
const mb = (bytes) => `${(bytes / 1048576).toFixed(0)} MB`;

async function openExplore() {
  renderIxBooks();
  if (ix.loaded) return;
  ix.loaded = true;
  const s = await (await fetch("/api/index")).json();
  $("#ix-stats").innerHTML = [
    ["Passages", s.chunks.toLocaleString()],
    ["Books", s.books],
    ["Embedding model", s.embed_model],
    ["Vector size", `${s.dimensions} numbers`],
    ["Chunking", `${s.chunk_size} chars, ${s.chunk_overlap} overlap`],
    ["On disk", `${mb(s.sqlite_bytes)} text + ${mb(s.vectors_bytes)} vectors`],
  ].map(([k, v]) => `<div><div class="muted">${k}</div><b>${esc(String(v))}</b></div>`).join("");
  loadChunks(true);
}

function renderIxBooks() {
  const term = $("#ix-book-filter").value.trim().toLowerCase();
  const ready = state.books.filter((b) => b.status === "ready").sort((a, b) => a.title.localeCompare(b.title));
  const total = ready.reduce((n, b) => n + b.chunks, 0);
  $("#ix-book-list").innerHTML =
    `<button class="ix-book ${ix.bookId ? "" : "on"}" data-id=""><span>All books</span><span class="muted">${total.toLocaleString()}</span></button>` +
    ready.filter((b) => !term || b.title.toLowerCase().includes(term)).map((b) =>
      `<button class="ix-book ${ix.bookId === b.id ? "on" : ""}" data-id="${b.id}" title="${esc(b.title)}">
         <span>${esc(b.title)}</span><span class="muted">${b.chunks.toLocaleString()}</span></button>`).join("");
}

async function loadChunks(reset) {
  if (reset) { ix.offset = 0; $("#ix-chunks").innerHTML = ""; }
  const req = ++ix.req; // ignore responses that arrive after a newer request
  const params = new URLSearchParams({ offset: ix.offset, limit: PAGE });
  if (ix.bookId) params.set("book_id", ix.bookId);
  if (ix.q) params.set("q", ix.q);
  $("#ix-more").hidden = true;
  $("#ix-sub").textContent = "Loading…";
  const res = await (await fetch(`/api/chunks?${params}`)).json();
  if (req !== ix.req) return;

  const book = state.books.find((b) => b.id === ix.bookId);
  $("#ix-title").textContent = book ? book.title : "All books";
  ix.offset += res.chunks.length;
  $("#ix-sub").textContent = `${res.total.toLocaleString()} passage${res.total === 1 ? "" : "s"}` +
    (ix.q ? ` containing "${ix.q}"` : "") + (res.total ? ` · showing ${ix.offset.toLocaleString()}` : "") +
    (book ? ` · ${book.filename}` : "");
  $("#ix-chunks").insertAdjacentHTML("beforeend", res.chunks.map((c) => `
    <article class="ix-chunk">
      <div class="ix-meta">
        <code>${esc(c.id)}</code>
        ${ix.bookId ? "" : `<span class="ix-book-name">${esc(c.title || "")}</span>`}
        <span>${c.page ? `p. ${c.page}` : esc(c.chapter || (c.section ? `section ${c.section}` : ""))}</span>
        <span class="muted">${c.text.length.toLocaleString()} chars</span>
        <button class="link ix-vec" data-id="${esc(c.id)}">Show vector</button>
      </div>
      <div class="ix-text">${esc(c.text)}</div>
      <div class="ix-vector" hidden></div>
    </article>`).join("") || '<p class="muted">Nothing found.</p>');
  $("#ix-more").hidden = ix.offset >= res.total;
}

$("#ix-book-filter").addEventListener("input", renderIxBooks);
$("#ix-book-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".ix-book");
  if (!btn) return;
  ix.bookId = btn.dataset.id || null;
  renderIxBooks();
  loadChunks(true);
});
$("#ix-search-form").addEventListener("submit", (e) => { e.preventDefault(); ix.q = $("#ix-search").value.trim(); loadChunks(true); });
$("#ix-search").addEventListener("search", () => { if (!$("#ix-search").value) { ix.q = ""; loadChunks(true); } });
$("#ix-more").addEventListener("click", () => loadChunks(false));
$("#ix-chunks").addEventListener("click", async (e) => {
  const btn = e.target.closest(".ix-vec");
  if (!btn) return;
  const box = btn.closest(".ix-chunk").querySelector(".ix-vector");
  if (!box.hidden) { box.hidden = true; btn.textContent = "Show vector"; return; }
  const v = await (await fetch(`/api/chunks/${encodeURIComponent(btn.dataset.id)}/embedding`)).json();
  box.textContent = `${v.dimensions} dimensions:\n[${v.embedding.map((x) => x.toFixed(5)).join(", ")}]`;
  box.hidden = false;
  btn.textContent = "Hide vector";
});

// ------------------------------------------------------------------ explore: raw database tables
const db = { tables: null, name: null, offset: 0, total: 0 };
const DB_PAGE = 100;
const FILES = "__files__";

document.querySelectorAll(".ix-mode").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".ix-mode").forEach((b) => b.classList.toggle("on", b === btn));
    $("#ix-passages").hidden = btn.dataset.mode !== "passages";
    $("#ix-tables").hidden = btn.dataset.mode !== "tables";
    if (btn.dataset.mode === "tables" && !db.tables) loadDbTables();
  })
);

async function loadDbTables() {
  $("#db-table-list").innerHTML = '<p class="muted">Counting rows…</p>';
  db.tables = await (await fetch("/api/db/tables")).json();
  renderDbTables();
  showTable(db.tables.find((t) => t.name === "embedding_metadata")?.name || db.tables[0].name);
}

function renderDbTables() {
  $("#db-table-list").innerHTML = db.tables.map((t) =>
    `<button class="ix-book ${db.name === t.name ? "on" : ""}" data-name="${esc(t.name)}">
       <span>${esc(t.name)}</span><span class="muted">${t.rows.toLocaleString()}</span></button>`).join("") +
    `<button class="ix-book ${db.name === FILES ? "on" : ""}" data-name="${FILES}"><span>📁 Files on disk</span></button>`;
}

async function showTable(name, offset = 0) {
  db.name = name;
  db.offset = offset;
  renderDbTables();
  const grid = $("#db-grid");
  if (name === FILES) {
    const files = await (await fetch("/api/db/files")).json();
    $("#db-title").textContent = "Files in data/chroma";
    $("#db-sub").textContent = "The vectors live in the binary files of the segment folder (HNSW index), not in SQLite.";
    $("#db-prev").hidden = $("#db-next").hidden = true;
    grid.innerHTML = "<thead><tr><th>file</th><th>size</th></tr></thead><tbody>" +
      files.map((f) => `<tr><td>${esc(f.path)}</td><td>${mb(f.bytes)} (${f.bytes.toLocaleString()} bytes)</td></tr>`).join("") + "</tbody>";
    return;
  }
  $("#db-sub").textContent = "Loading…";
  const t = await (await fetch(`/api/db/tables/${encodeURIComponent(name)}?offset=${offset}&limit=${DB_PAGE}`)).json();
  if (db.name !== name || db.offset !== offset) return; // a newer click won
  db.total = t.total;
  $("#db-title").textContent = name;
  $("#db-sub").textContent = t.total
    ? `rows ${(offset + 1).toLocaleString()}–${(offset + t.rows.length).toLocaleString()} of ${t.total.toLocaleString()} · ${t.columns.length} columns · click a cell to expand it`
    : "empty table";
  $("#db-prev").hidden = $("#db-next").hidden = t.total <= DB_PAGE;
  $("#db-prev").disabled = offset === 0;
  $("#db-next").disabled = offset + DB_PAGE >= t.total;
  const cell = (v) => v === null ? '<td class="null">NULL</td>' : `<td>${esc(String(v))}</td>`;
  grid.innerHTML = `<thead><tr>${t.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    t.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("") + "</tbody>";
  $(".db-grid-wrap").scrollTop = 0;
}

$("#db-table-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".ix-book");
  if (btn) showTable(btn.dataset.name);
});
$("#db-prev").addEventListener("click", () => showTable(db.name, Math.max(0, db.offset - DB_PAGE)));
$("#db-next").addEventListener("click", () => showTable(db.name, db.offset + DB_PAGE));
$("#db-grid").addEventListener("click", (e) => e.target.closest("td")?.classList.toggle("open"));

checkHealth();
setInterval(checkHealth, 15000);
loadBooks();

const $ = (s) => document.querySelector(s);
const state = { books: [], selected: new Set(), history: [], busy: false };

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
  renderFilter();
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
  state.selected.delete(id);
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

// ------------------------------------------------------------------ book filter
function renderFilter() {
  const ready = state.books.filter((b) => b.status === "ready");
  $("#filter").innerHTML = ready.length < 2 ? "" :
    `<span class="muted" style="align-self:center">Search in:</span>
     <button class="chip ${state.selected.size ? "" : "on"}" data-all>All books</button>` +
    ready.map((b) => `<button class="chip ${state.selected.has(b.id) ? "on" : ""}" data-id="${b.id}" title="${esc(b.title)}">${esc(b.title)}</button>`).join("");
}
$("#filter").addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset.all !== undefined) state.selected.clear();
  else if (t.dataset.id) state.selected.has(t.dataset.id) ? state.selected.delete(t.dataset.id) : state.selected.add(t.dataset.id);
  else return;
  renderFilter();
});

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
  msg.innerHTML = `<div class="bubble">${html}</div>`;
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
  msg.appendChild(d);
}

$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = q.value.trim();
  if (!question || state.busy) return;
  state.busy = true;
  $("#send").disabled = true;
  q.value = ""; q.style.height = "auto";

  addMsg("user", esc(question));
  const msg = addMsg("bot", "");
  const bubble = msg.querySelector(".bubble");
  bubble.classList.add("typing");
  let answer = "";
  const chat = $("#chat");

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: state.history, book_ids: [...state.selected] }),
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
    bubble.classList.remove("typing");
    state.busy = false;
    $("#send").disabled = false;
    q.focus();
  }
});

checkHealth();
setInterval(checkHealth, 15000);
loadBooks();

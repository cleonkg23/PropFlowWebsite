// Property Workflow demo — guided flow controller.
//
// Architecture:
//   refresh()       — pulls /api/state, re-renders everything (used by polling
//                     and outside the guided flow).
//   runGuidedFlow() — replaces direct triggering for scenario buttons; pauses
//                     polling, then walks the user through inbox → detail →
//                     action → board with sequenced reveals & section emphasis.
//   render*Staged() — variants of the panel renderers that wrap fields in
//                     `.stage` elements (hidden until `.show` is added). The
//                     guided flow reveals stages one-by-one.
//
// Security: every untrusted string is wrapped through esc() before being
// inserted via innerHTML. Multi-line drafts go via textContent.
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let state = { items: [], tasks: [] };
let selectedItemId = null;
let pollHandle = null;
let flowRunning = false;

const URGENCY_PILL = { urgent: "pill-urgent", high: "pill-high", normal: "pill-normal" };
const STEPS = ["received", "classified", "assigned", "reply", "tracked"];
const SECTIONS = ["section-inbox", "section-detail", "section-action", "section-board"];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const wait = (ms) => new Promise(r => setTimeout(r, ms));

const NEXT_STATUSES = {
  new: [["in_progress", "Start work"]],
  in_progress: [["awaiting_reply", "Mark replied"], ["done", "Mark done"]],
  awaiting_reply: [["done", "Mark done"]],
  done: [],
};

// ---------- network ----------------------------------------------------------

async function fetchState() {
  const r = await fetch("/api/state");
  state = await r.json();
}

async function refresh() {
  if (flowRunning) return;
  await fetchState();
  // Re-check after the await: if a guided flow started while the fetch was
  // in flight, skip the render so we don't clobber the staged reveal.
  if (flowRunning) return;
  if (!selectedItemId && state.items.length) {
    selectedItemId = state.items[state.items.length - 1].id;
  }
  render();
}

function pausePolling() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
}
function resumePolling() {
  if (!pollHandle) pollHandle = setInterval(refresh, 4000);
}

async function transition(itemId, status) {
  await fetch(`/api/items/${itemId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await refresh();
}

async function reset() {
  // Reset is allowed mid-flow: it cancels the current sequence cleanly so the
  // demo never feels stuck. We force the flow flag down before re-rendering.
  flowRunning = false;
  clearActive();
  await fetch("/api/reset", { method: "POST" });
  selectedItemId = null;
  resetSteps();
  setHint("Trigger a scenario to start.");
  $("#board-summary").classList.remove("show");
  $$(".scenario-btn").forEach(b => b.classList.remove("is-active"));
  await fetch("/api/seed-pressure", { method: "POST" });
  await refresh();
  resumePolling();
}

// ---------- step indicator ---------------------------------------------------

function resetSteps() {
  STEPS.forEach(s => {
    const el = document.querySelector(`.step[data-step="${s}"]`);
    el?.classList.remove("active", "done");
  });
}
function setStep(name) {
  const idx = STEPS.indexOf(name);
  STEPS.forEach((s, i) => {
    const el = document.querySelector(`.step[data-step="${s}"]`);
    if (!el) return;
    el.classList.toggle("active", i === idx);
    el.classList.toggle("done", i < idx);
  });
}
function setHint(text) { $("#step-hint").textContent = text; }

// ---------- section emphasis -------------------------------------------------

function setActive(id) {
  SECTIONS.forEach(s => {
    const el = document.getElementById(s);
    if (!el) return;
    el.classList.toggle("active", s === id);
    el.classList.toggle("dim", id ? s !== id : false);
  });
}
function clearActive() {
  SECTIONS.forEach(s => document.getElementById(s)?.classList.remove("active", "dim"));
}

// ---------- formatting -------------------------------------------------------

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function pill(urgency) {
  const cls = URGENCY_PILL[urgency] || "pill-normal";
  return `<span class="pill ${cls}">${esc(urgency)}</span>`;
}

// ---------- rendering --------------------------------------------------------

function renderInbox() {
  const list = $("#inbox-list");
  $("#inbox-count").textContent = `${state.items.length} item${state.items.length === 1 ? "" : "s"}`;
  if (!state.items.length) {
    list.innerHTML = `<li class="py-6 text-sm text-center" style="color:#6b7268">No items yet — trigger a scenario above.</li>`;
    return;
  }
  list.innerHTML = [...state.items].reverse().map(it => `
    <li>
      <button data-item="${esc(it.id)}" class="inbox-row w-full text-left py-3 hover:bg-black/5 rounded px-2 ${it.id === selectedItemId ? 'bg-black/5' : ''}">
        <div class="flex items-center justify-between">
          <span class="font-medium text-sm">${esc(it.from_name)}</span>
          ${pill(it.urgency)}
        </div>
        <div class="text-xs mt-1 truncate" style="color:#5a6259">${esc(it.message)}</div>
        <div class="text-[0.65rem] mt-1 uppercase tracking-widest" style="color:#6b7268">${esc(it.category.replace('_',' '))} · ${esc(fmtTime(it.created_at))}</div>
      </button>
    </li>
  `).join("");

  $$('#inbox-list [data-item]').forEach(b => {
    b.addEventListener('click', () => { selectedItemId = b.dataset.item; render(); });
  });
}

// detailHTML: builds the classification panel with each row wrapped in a
// .stage element. When `revealAll` is true (default outside flow), every
// stage is rendered already showing.
function detailHTML(it, revealAll) {
  const cls = revealAll ? "stage show" : "stage";
  return `
    <div class="space-y-3">
      <div>
        <div class="col-head mb-1">From</div>
        <div class="font-medium">${esc(it.from_name)}</div>
        <div class="text-xs" style="color:#6b7268">${esc(it.property || '')}</div>
      </div>
      <div>
        <div class="col-head mb-1">Original message</div>
        <div class="text-sm leading-relaxed">${esc(it.message)}</div>
      </div>
      <div class="grid grid-cols-2 gap-3 pt-2 border-t" style="border-color:var(--rule)">
        <div class="${cls}" data-stage="category">
          <div class="col-head mb-1">Category</div>
          <div class="font-medium">${esc(it.category.replace('_',' '))}</div>
          <div class="text-[0.7rem] mt-0.5" style="color:#6b7268">Detected from message content</div>
        </div>
        <div class="${cls}" data-stage="urgency">
          <div class="col-head mb-1">Urgency</div>
          <div>${pill(it.urgency)}</div>
          <div class="text-[0.7rem] mt-0.5" style="color:#6b7268">Set by keyword + SLA rules</div>
        </div>
        <div class="${cls}" data-stage="owner">
          <div class="col-head mb-1">Owner</div>
          <div class="font-medium">${esc(it.owner || '—')}</div>
          <div class="text-[0.7rem] mt-0.5" style="color:#6b7268">Assigned by workflow rules</div>
        </div>
        <div class="${cls}" data-stage="action">
          <div class="col-head mb-1">Next action</div>
          <div class="font-medium">${esc(it.next_action || '—')}</div>
          <div class="text-[0.7rem] mt-0.5" style="color:#6b7268">Suggested automatically</div>
        </div>
      </div>
    </div>
  `;
}

function renderDetail({ revealAll = true } = {}) {
  const panel = $("#detail-panel");
  const it = state.items.find(x => x.id === selectedItemId);
  if (!it) {
    panel.innerHTML = `<div style="color:#6b7268">Select an item from the inbox to see how it was classified.</div>`;
    return;
  }
  panel.innerHTML = detailHTML(it, revealAll);
}

function actionHTML(it, task, revealAll) {
  const cls = revealAll ? "stage show" : "stage";
  const transitions = NEXT_STATUSES[it.status] || [];
  const buttons = transitions.map(([s, label]) =>
    `<button data-transition="${esc(s)}" class="text-xs font-medium px-3 py-1.5 rounded border hover:bg-black/5" style="border-color:var(--rule)">${esc(label)}</button>`
  ).join("");

  return `
    <div class="space-y-4">
      <div class="${cls}" data-stage="task">
        <div class="rounded border p-3" style="border-color:var(--rule); background:#f8f3e8">
          <div class="col-head mb-1">Task created</div>
          <div class="text-sm font-medium">${esc(task ? task.description : '—')}</div>
          <div class="text-xs mt-1" style="color:#6b7268">
            ${task ? `Assigned to <span class="font-medium" style="color:var(--ink)">${esc(task.assigned_to)}</span> · due ${esc(fmtTime(task.due_date))}` : ''}
          </div>
        </div>
      </div>
      <div class="${cls}" data-stage="draft">
        <div class="col-head mb-1">Draft reply <span class="font-normal normal-case tracking-normal italic" style="color:#6b7268">— prepared from the workflow decision</span></div>
        <pre class="text-sm whitespace-pre-wrap leading-relaxed font-sans" style="color:var(--ink)" id="draft-body"></pre>
      </div>
      ${buttons ? `<div class="${cls} flex flex-wrap gap-2 pt-2 border-t" data-stage="actions" style="border-color:var(--rule)"><span class="col-head self-center mr-1">Status</span>${buttons}</div>` : ''}
    </div>
  `;
}

function renderAction({ revealAll = true } = {}) {
  const panel = $("#action-panel");
  const it = state.items.find(x => x.id === selectedItemId);
  if (!it) {
    panel.innerHTML = `<div style="color:#6b7268">The created task and a draft response will appear here.</div>`;
    return;
  }
  const task = state.tasks.find(t => t.item_id === it.id);
  panel.innerHTML = actionHTML(it, task, revealAll);
  $("#draft-body").textContent = it.draft || "";
  $$('[data-transition]').forEach(b => {
    b.addEventListener('click', () => transition(selectedItemId, b.dataset.transition));
  });
}

function renderBoard({ newArrivalId = null } = {}) {
  const grouped = { new: [], in_progress: [], awaiting_reply: [], done: [] };
  state.items.forEach(it => {
    const bucket = grouped[it.status] ? it.status : 'in_progress';
    grouped[bucket].push(it);
  });
  Object.entries(grouped).forEach(([status, items]) => {
    const ul = document.querySelector(`[data-status="${status}"]`);
    if (!ul) return;
    if (!items.length) {
      ul.innerHTML = `<li class="text-xs" style="color:#9aa097">—</li>`;
      return;
    }
    ul.innerHTML = items.map(it => {
      const arrival = it.id === newArrivalId ? " new-arrival" : "";
      return `
        <li class="board-card${arrival} rounded border bg-white/60 p-2" style="border-color:var(--rule)">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium truncate">${esc(it.from_name)}</span>
            ${pill(it.urgency)}
          </div>
          <div class="text-[0.65rem] mt-1 uppercase tracking-widest" style="color:#6b7268">${esc(it.category.replace('_',' '))}</div>
        </li>
      `;
    }).join("");
  });
}

function render() {
  renderInbox();
  renderDetail();
  renderAction();
  renderBoard();
}

// ---------- guided flow ------------------------------------------------------

const FINAL_LINES = [
  "From inbox message to tracked workflow in seconds. Nothing gets missed.",
  "Classified, assigned, and visible — your team knows exactly what's open.",
  "Everything has an owner. Everything has a next step.",
];

async function runGuidedFlow(key) {
  if (flowRunning) return;
  flowRunning = true;
  pausePolling();

  // Step 0: prep — clear prior state, mark scenario active
  $$(".scenario-btn").forEach(b => b.classList.toggle("is-active", b.dataset.scenario === key));
  $("#board-summary").classList.remove("show");
  resetSteps();
  setHint("Working through the flow…");

  // Trigger backend ingest, then pull fresh state. Guard: HTTP non-OK,
  // network error, or a malformed response all collapse cleanly back to idle.
  let resp;
  try {
    const r = await fetch(`/demo/${key}`, { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    resp = await r.json();
    if (!resp || !resp.item_id) throw new Error("missing item_id");
  } catch (e) {
    console.error("scenario trigger failed", e);
    flowRunning = false;
    clearActive();
    $$(".scenario-btn").forEach(b => b.classList.remove("is-active"));
    setHint("Could not trigger scenario — try again or hit Reset.");
    resumePolling();
    return;
  }
  selectedItemId = resp.item_id;
  await fetchState();

  // Step 1: inbox — show new message arriving
  setStep("received");
  setActive("section-inbox");
  renderInbox();
  const newRow = document.querySelector(`#inbox-list [data-item="${selectedItemId}"]`);
  if (newRow) {
    newRow.classList.add("flash");
    newRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  await wait(900);

  // Step 2: focus the message — dim siblings
  document.querySelectorAll("#inbox-list [data-item]").forEach(b => {
    if (b.dataset.item !== selectedItemId) b.classList.add("dim");
  });
  await wait(700);

  // Step 3: classification — reveal each field with stagger
  setStep("classified");
  setActive("section-detail");
  renderDetail({ revealAll: false });
  $("#section-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
  await wait(250);
  for (const stage of ["category", "urgency", "owner", "action"]) {
    document.querySelector(`#detail-panel [data-stage="${stage}"]`)?.classList.add("show");
    await wait(360);
  }
  await wait(300);

  // Step 4: task created
  setStep("assigned");
  setActive("section-action");
  renderAction({ revealAll: false });
  await wait(250);
  document.querySelector(`#action-panel [data-stage="task"]`)?.classList.add("show");
  await wait(800);

  // Step 5: draft reply
  setStep("reply");
  document.querySelector(`#action-panel [data-stage="draft"]`)?.classList.add("show");
  await wait(450);
  document.querySelector(`#action-panel [data-stage="actions"]`)?.classList.add("show");
  await wait(600);

  // Step 6: workflow board — item appears in destination column
  setStep("tracked");
  setActive("section-board");
  renderBoard({ newArrivalId: selectedItemId });
  $("#section-board").scrollIntoView({ behavior: "smooth", block: "nearest" });
  await wait(1100);

  // Step 7: final value caption
  const summary = $("#board-summary");
  summary.textContent = FINAL_LINES[Math.floor(Math.random() * FINAL_LINES.length)];
  summary.classList.add("show");
  setHint("Trigger another scenario or reset to replay.");
  await wait(900);
  clearActive();

  flowRunning = false;
  resumePolling();
}

// ---------- boot -------------------------------------------------------------

async function boot() {
  // Seed pressure messages on first view (idempotent server-side).
  try { await fetch("/api/seed-pressure", { method: "POST" }); } catch (_) {}
  await refresh();
  resumePolling();
}

document.addEventListener("DOMContentLoaded", () => {
  $$("[data-scenario]").forEach(b => {
    b.addEventListener("click", () => runGuidedFlow(b.dataset.scenario));
  });
  $("#reset-btn").addEventListener("click", reset);
  boot();
});

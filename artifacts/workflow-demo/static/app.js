// Tiny client: trigger scenarios, poll state, render three panels + board.
// All untrusted strings (item.message, from_name, property, etc.) are
// inserted via textContent or via the esc() helper -- never raw innerHTML.
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let state = { items: [], tasks: [] };
let selectedItemId = null;

const URGENCY_PILL = { urgent: "pill-urgent", high: "pill-high", normal: "pill-normal" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const NEXT_STATUSES = {
  new: [["in_progress", "Start work"]],
  in_progress: [["awaiting_reply", "Mark replied"], ["done", "Mark done"]],
  awaiting_reply: [["done", "Mark done"]],
  done: [],
};

async function refresh() {
  const r = await fetch("/api/state");
  state = await r.json();
  if (!selectedItemId && state.items.length) {
    selectedItemId = state.items[state.items.length - 1].id;
  }
  render();
}

async function trigger(key) {
  const r = await fetch(`/demo/${key}`, { method: "POST" });
  const data = await r.json();
  selectedItemId = data.item_id;
  await refresh();
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
  await fetch("/api/reset", { method: "POST" });
  selectedItemId = null;
  await refresh();
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function pill(urgency) {
  const cls = URGENCY_PILL[urgency] || "pill-normal";
  return `<span class="pill ${cls}">${esc(urgency)}</span>`;
}

function renderInbox() {
  const list = $("#inbox-list");
  $("#inbox-count").textContent = `${state.items.length} item${state.items.length === 1 ? "" : "s"}`;
  if (!state.items.length) {
    list.innerHTML = `<li class="py-6 text-sm text-center" style="color:#6b7268">No items yet — trigger a scenario above.</li>`;
    return;
  }
  list.innerHTML = [...state.items].reverse().map(it => `
    <li>
      <button data-item="${esc(it.id)}" class="w-full text-left py-3 hover:bg-black/5 rounded px-2 ${it.id === selectedItemId ? 'bg-black/5' : ''}">
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

function renderDetail() {
  const panel = $("#detail-panel");
  const it = state.items.find(x => x.id === selectedItemId);
  if (!it) {
    panel.innerHTML = `<div style="color:#6b7268">Select an item from the inbox to see how it was classified.</div>`;
    return;
  }
  panel.innerHTML = `
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
        <div><div class="col-head mb-1">Category</div><div class="font-medium">${esc(it.category.replace('_',' '))}</div></div>
        <div><div class="col-head mb-1">Urgency</div><div>${pill(it.urgency)}</div></div>
        <div><div class="col-head mb-1">Owner</div><div class="font-medium">${esc(it.owner || '—')}</div></div>
        <div><div class="col-head mb-1">Next action</div><div class="font-medium">${esc(it.next_action || '—')}</div></div>
      </div>
    </div>
  `;
}

function renderAction() {
  const panel = $("#action-panel");
  const it = state.items.find(x => x.id === selectedItemId);
  if (!it) {
    panel.innerHTML = `<div style="color:#6b7268">The created task and a draft response will appear here.</div>`;
    return;
  }
  const task = state.tasks.find(t => t.item_id === it.id);
  const transitions = NEXT_STATUSES[it.status] || [];
  const buttons = transitions.map(([s, label]) =>
    `<button data-transition="${esc(s)}" class="text-xs font-medium px-3 py-1.5 rounded border hover:bg-black/5" style="border-color:var(--rule)">${esc(label)}</button>`
  ).join("");

  panel.innerHTML = `
    <div class="space-y-4">
      <div class="rounded border p-3" style="border-color:var(--rule); background:#f8f3e8">
        <div class="col-head mb-1">Task created</div>
        <div class="text-sm font-medium">${esc(task ? task.description : '—')}</div>
        <div class="text-xs mt-1" style="color:#6b7268">
          ${task ? `Assigned to <span class="font-medium" style="color:var(--ink)">${esc(task.assigned_to)}</span> · due ${esc(fmtTime(task.due_date))}` : ''}
        </div>
      </div>
      <div>
        <div class="col-head mb-1">Draft reply</div>
        <pre class="text-sm whitespace-pre-wrap leading-relaxed font-sans" style="color:var(--ink)" id="draft-body"></pre>
      </div>
      ${buttons ? `<div class="flex flex-wrap gap-2 pt-2 border-t" style="border-color:var(--rule)"><span class="col-head self-center mr-1">Status</span>${buttons}</div>` : ''}
    </div>
  `;
  // Inject draft via textContent to keep multi-line untrusted content safe.
  $("#draft-body").textContent = it.draft || "";

  $$('[data-transition]').forEach(b => {
    b.addEventListener('click', () => transition(selectedItemId, b.dataset.transition));
  });
}

function renderBoard() {
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
    ul.innerHTML = items.map(it => `
      <li class="rounded border bg-white/60 p-2" style="border-color:var(--rule)">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium truncate">${esc(it.from_name)}</span>
          ${pill(it.urgency)}
        </div>
        <div class="text-[0.65rem] mt-1 uppercase tracking-widest" style="color:#6b7268">${esc(it.category.replace('_',' '))}</div>
      </li>
    `).join("");
  });
}

function render() {
  renderInbox();
  renderDetail();
  renderAction();
  renderBoard();
}

document.addEventListener("DOMContentLoaded", () => {
  $$("[data-scenario]").forEach(b => b.addEventListener("click", () => trigger(b.dataset.scenario)));
  $("#reset-btn").addEventListener("click", reset);
  refresh();
  setInterval(refresh, 4000);
});

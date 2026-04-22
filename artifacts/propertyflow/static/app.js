// Tiny client helpers — no framework.

// URL prefix detection: when the app is hosted under a path proxy (e.g. /app),
// hardcoded "/api/items" etc. in JS would escape the prefix. Derive the
// current prefix from this script's own src (HTML attrs are rewritten by the
// server-side prefix middleware, so the script tag will be /app/static/app.js
// when the prefix is active, or /static/app.js otherwise).
const BASE = (() => {
  const marker = '/static/app.js';
  for (const s of document.getElementsByTagName('script')) {
    const src = s.getAttribute('src') || '';
    const i = src.indexOf(marker);
    if (i >= 0) {
      // Strip protocol/host if present, return only the path prefix.
      const path = src.startsWith('http') ? new URL(src).pathname : src;
      return path.slice(0, path.indexOf(marker));
    }
  }
  return '';
})();

// Quick-login buttons on /login: clicking fills the email and submits.
// Selector matches any login form regardless of URL prefix (the app may be
// hosted at "/" or under a path-proxy prefix like "/app", so the form's
// action can be either "/login" or "/app/login").
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.quick-login');
  if (!btn) return;
  e.preventDefault();
  const form = document.querySelector('form[action$="/login"]');
  if (!form) return;
  const input = form.querySelector('input[name="email"]');
  if (input) {
    input.value = btn.dataset.email;
    form.submit();
  }
});

// Manual create form: posts JSON to /api/items, redirects on success.
document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (form.id !== 'manual-item') return;
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  const btn = form.querySelector('button[type="submit"], button:not([type])');
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Running\u2026';
  try {
    const res = await fetch(BASE + '/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    window.location.href = `${BASE}/items/${out.id}`;
  } catch (err) {
    btn.disabled = false;
    btn.textContent = original;
    alert('Failed: ' + err.message);
  }
});

// All other form submits: disable button to prevent double-submit, show loading state.
document.addEventListener('submit', (e) => {
  const form = e.target;
  if (form.id === 'manual-item') return;
  const btn = form.querySelector('button[type="submit"], button:not([type])');
  if (!btn) return;
  const original = btn.textContent;
  btn.disabled = true;
  if (!btn.classList.contains('btn-ghost')) {
    btn.textContent = original.replace(/\u2026$/, '') + '\u2026';
  }
  // Re-enable after 8s as a safety net (network error / redirect not firing)
  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = original;
  }, 8000);
});

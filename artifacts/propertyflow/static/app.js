// Tiny client helpers — no framework.

// Quick-login buttons on /login: clicking one fills the email and submits.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.quick-login');
  if (!btn) return;
  e.preventDefault();
  const form = document.querySelector('form[action="/login"]');
  if (!form) return;
  const input = form.querySelector('input[name="email"]');
  if (input) {
    input.value = btn.dataset.email;
    form.submit();
  }
});

// Manual create form on dashboard posts JSON, not form-encoded.
document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (form.id !== 'manual-item') return;
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  const btn = form.querySelector('button');
  btn.disabled = true; btn.textContent = 'Working…';
  try {
    const res = await fetch('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    window.location.href = `/items/${out.id}`;
  } catch (err) {
    btn.disabled = false; btn.textContent = 'Run through workflow';
    alert('Failed: ' + err.message);
  }
});

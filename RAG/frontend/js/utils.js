// ─── Escape HTML ──────────────────────────────────────────────────────────
function escapeHtml(text) {
  return String(text)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Markdown renderer ────────────────────────────────────────────────────
function renderMarkdown(raw) {
  let t = escapeHtml(raw);
  t = t.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/\*(.*?)\*/g, '<em>$1</em>');
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/^[•\-\*] (.+)$/gm, '<li style="margin-left:1rem;list-style-type:disc">$1</li>');
  t = t.replace(/(<li[^>]*>.*?<\/li>\n?)+/gs, m => `<ul style="margin:.3rem 0">${m}</ul>`);
  t = t.replace(/\n/g, '<br>');
  return t;
}

// ─── Toast ────────────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = 'info') {
  const toast = document.getElementById('toast');
  const inner = document.getElementById('toast-inner');
  inner.textContent = msg;
  inner.className = 'px-4 py-2 rounded-full text-sm font-semibold shadow-lg text-white whitespace-nowrap ' +
    (type === 'success' ? 'bg-green-600' : type === 'error' ? 'bg-red-600' : 'bg-slate-700');
  toast.classList.remove('hidden');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.add('hidden'), 3500);
}

// ─── Scroll ───────────────────────────────────────────────────────────────
function scrollToBottom() {
  const c = document.getElementById('messages-container');
  requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
}

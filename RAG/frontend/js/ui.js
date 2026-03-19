// ─── Tab switching ────────────────────────────────────────────────────────
function switchTab(tab) {
  state.currentTab = tab;
  ['chat','base','profil'].forEach(t => {
    const content = document.getElementById('tab-' + t);
    const nav     = document.getElementById('nav-' + t);
    if (t === tab) {
      content.classList.add('active');
      nav.classList.remove('text-slate-400', 'dark:text-slate-500');
      nav.classList.add('text-primary');
    } else {
      content.classList.remove('active');
      nav.classList.remove('text-primary');
      nav.classList.add('text-slate-400', 'dark:text-slate-500');
    }
  });
  if (tab === 'base') loadDocuments();
}

// ─── Dark mode ────────────────────────────────────────────────────────────
function toggleDark() {
  const html = document.documentElement;
  html.classList.toggle('dark');
  const isDark = html.classList.contains('dark');
  document.getElementById('dark-icon').textContent = isDark ? 'light_mode' : 'dark_mode';
  localStorage.setItem('dark', isDark ? '1' : '0');
}

// ─── Status polling ────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await fetch('/api/health');
    const d = await r.json();
    const dot  = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (d.status === 'ready') {
      dot.className  = 'w-2 h-2 rounded-full bg-green-500 transition-colors';
      text.textContent = 'En ligne';
      const el = document.getElementById('doc-count-profil');
      if (el) el.textContent = d.documents + ' doc' + (d.documents > 1 ? 's' : '');
      const mn = document.getElementById('model-name');
      if (mn && d.model) mn.textContent = d.model.replace('ollama/', '');
    } else {
      dot.className  = 'w-2 h-2 rounded-full bg-amber-400 transition-colors animate-pulse';
      text.textContent = 'Initialisation…';
    }
  } catch {
    const dot = document.getElementById('status-dot');
    dot.className = 'w-2 h-2 rounded-full bg-red-500 transition-colors';
    document.getElementById('status-text').textContent = 'Hors ligne';
  }
}

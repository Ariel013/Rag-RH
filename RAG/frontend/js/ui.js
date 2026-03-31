// ─── Tab switching ────────────────────────────────────────────────────────
function switchTab(tab) {
  state.currentTab = tab;
  closeSidebar();

  const tabs = ['chat', 'base', 'profil', 'analytics'];
  tabs.forEach(t => {
    const content = document.getElementById('tab-' + t);
    if (content) content.classList.toggle('active', t === tab);
  });

  // Desktop sidebar nav
  document.querySelectorAll('.sidebar-nav-item').forEach(btn => {
    btn.classList.remove('active');
  });
  const desktopNav = document.getElementById('nav-' + tab);
  if (desktopNav) desktopNav.classList.add('active');

  // Mobile bottom nav
  ['chat', 'base', 'profil', 'analytics'].forEach(t => {
    const mob = document.getElementById('mob-nav-' + t);
    if (!mob) return;
    if (t === tab) {
      mob.classList.add('text-primary');
      mob.classList.remove('text-slate-400', 'dark:text-slate-500');
    } else {
      mob.classList.remove('text-primary');
      mob.classList.add('text-slate-400', 'dark:text-slate-500');
    }
  });

  if (tab === 'base')      loadDocuments();
  if (tab === 'analytics') loadAnalytics();
}

// ─── Sidebar (mobile drawer) ───────────────────────────────────────────────
function toggleSidebar() {
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('sidebar-overlay');
  const isOpen   = sidebar.classList.contains('open');
  if (isOpen) {
    closeSidebar();
  } else {
    sidebar.classList.add('open');
    overlay.classList.add('visible');
    overlay.classList.remove('hidden');
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  sidebar.classList.remove('open');
  overlay.classList.remove('visible');
  // Délai pour laisser l'animation se terminer
  setTimeout(() => overlay.classList.add('hidden'), 220);
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

// ─── Bootstrap ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.msg-time').forEach(el => {
    el.textContent = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  });
  document.getElementById('today-label').textContent =
    new Date().toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long' });

  document.getElementById('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });

  pollStatus();
  setInterval(pollStatus, 5000);

  // Badge "questions sans réponse" — rafraîchi toutes les 30s
  refreshUnansweredBadge();
  setInterval(refreshUnansweredBadge, 30000);

  if (localStorage.getItem('dark') === '1') {
    document.documentElement.classList.add('dark');
    document.getElementById('dark-icon').textContent = 'light_mode';
  }

  checkAdminSession();
  initSession();
});

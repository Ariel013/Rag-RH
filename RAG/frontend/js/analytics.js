// ─── Analytics Dashboard ──────────────────────────────────────────────────

let _analyticsView = 'overview';
let _convPage      = 1;
let _unansPage     = 1;
let _unansStatus   = 'pending';

function loadAnalytics() {
  switchAnalyticsView('overview');
  refreshUnansweredBadge();
}

function switchAnalyticsView(view) {
  _analyticsView = view;
  ['overview', 'conversations', 'unanswered'].forEach(v => {
    document.getElementById('av-' + v).classList.toggle('hidden', v !== view);
    const btn = document.getElementById('atab-' + v);
    if (v === view) {
      btn.classList.add('bg-white', 'dark:bg-slate-700', 'text-primary', 'shadow-sm');
      btn.classList.remove('text-slate-500');
    } else {
      btn.classList.remove('bg-white', 'dark:bg-slate-700', 'text-primary', 'shadow-sm');
      btn.classList.add('text-slate-500');
    }
  });
  if (view === 'overview')       renderOverview();
  else if (view === 'conversations') renderConversations(1);
  else if (view === 'unanswered')    renderUnanswered('pending', 1);
}

// ─── Vue d'ensemble ───────────────────────────────────────────────────────

async function renderOverview() {
  const el = document.getElementById('analytics-overview-content');
  el.innerHTML = _loadingHtml();
  try {
    const data = await _apiFetch('/api/admin/stats');
    el.innerHTML = `
      <div class="grid grid-cols-3 gap-2 mb-4">
        ${_statCard(data.total_questions, 'Questions', 'forum')}
        ${_statCard(data.unanswered_pending, 'Sans réponse', 'help', data.unanswered_pending > 0 ? 'amber' : 'primary')}
        ${_statCard(data.total_conversations, 'Conversations', 'chat_bubble')}
      </div>
      ${data.unanswered_pending > 0 ? _alertBanner(data.unanswered_pending) : ''}
      <div class="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm border border-primary/10">
        <h3 class="font-bold text-sm text-highlight mb-3 flex items-center gap-2">
          <span class="material-symbols-outlined text-[18px]">trending_up</span>
          Questions les plus posées
        </h3>
        ${data.top_questions.length === 0
          ? '<p class="text-xs text-slate-400 text-center py-4">Aucune donnée pour le moment</p>'
          : `<div class="space-y-1.5">${data.top_questions.map((q, i) => _topQuestionRow(q, i)).join('')}</div>`
        }
      </div>`;
  } catch {
    el.innerHTML = _errorHtml();
  }
}

function _statCard(value, label, icon, color = 'primary') {
  const colors = {
    primary: 'text-primary border-primary/10',
    amber:   'text-amber-500 border-amber-300 dark:border-amber-700',
  };
  return `
    <div class="bg-white dark:bg-slate-800 rounded-xl p-3 text-center shadow-sm border ${colors[color]}">
      <span class="material-symbols-outlined text-[18px] ${color === 'amber' ? 'text-amber-400' : 'text-primary/50'}">${icon}</span>
      <p class="text-2xl font-bold mt-0.5 ${color === 'amber' ? 'text-amber-500' : 'text-primary'}">${value}</p>
      <p class="text-[10px] text-slate-400 mt-0.5 leading-tight">${label}</p>
    </div>`;
}

function _alertBanner(count) {
  return `
    <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl p-3 mb-4 flex items-center gap-3">
      <span class="material-symbols-outlined text-amber-500 text-[22px] shrink-0">notification_important</span>
      <div class="min-w-0">
        <p class="text-sm font-semibold text-amber-700 dark:text-amber-400">${count} question(s) sans réponse</p>
        <p class="text-xs text-amber-600 dark:text-amber-500">L'assistant n'a pas pu répondre — ajoutez des réponses.</p>
      </div>
      <button onclick="switchAnalyticsView('unanswered')"
        class="ml-auto shrink-0 text-xs bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors">
        Voir →
      </button>
    </div>`;
}

function _topQuestionRow(q, i) {
  const isFirst = i === 0;
  return `
    <div class="flex items-center gap-3 py-1.5 border-b border-slate-50 dark:border-slate-700 last:border-0">
      <span class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0
        ${isFirst ? 'bg-primary text-white' : 'bg-slate-100 dark:bg-slate-700 text-slate-500'}">
        ${i + 1}
      </span>
      <span class="flex-1 text-xs text-slate-700 dark:text-slate-300 line-clamp-2">${escapeHtml(q.question)}</span>
      <span class="shrink-0 text-xs font-bold text-primary">${q.count}×</span>
    </div>`;
}

// ─── Conversations ────────────────────────────────────────────────────────

async function renderConversations(page) {
  _convPage = page;
  const el = document.getElementById('analytics-conversations-content');
  el.innerHTML = _loadingHtml();
  try {
    const data = await _apiFetch(`/api/admin/conversations?page=${page}`);
    const totalPages = Math.ceil(data.total / data.page_size);
    el.innerHTML = `
      <p class="text-xs text-slate-400 mb-3">${data.total} conversation(s) au total</p>
      <div class="space-y-2">
        ${data.items.length === 0
          ? '<p class="text-center text-slate-400 text-sm py-6">Aucune conversation enregistrée</p>'
          : data.items.map(c => _convCard(c)).join('')}
      </div>
      ${totalPages > 1 ? _pagination(page, totalPages, `renderConversations`) : ''}`;
  } catch {
    el.innerHTML = _errorHtml();
  }
}

function _convCard(c) {
  return `
    <div class="bg-white dark:bg-slate-800 rounded-xl p-3 shadow-sm border border-primary/10
                hover:border-primary/30 transition-colors cursor-pointer"
         onclick="toggleConvDetail('${c.id}', this)">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">
            ${escapeHtml(c.first_question || 'Conversation')}
          </p>
          <p class="text-[10px] text-slate-400 mt-0.5">
            ${_fmtDate(c.started_at)} · ${c.message_count} message(s)
          </p>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          ${c.unanswered_count > 0
            ? `<span class="text-[10px] bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 font-bold px-1.5 py-0.5 rounded-full">
                ${c.unanswered_count} ⚠
               </span>`
            : ''}
          <span class="material-symbols-outlined text-slate-300 text-[18px] conv-arrow">expand_more</span>
        </div>
      </div>
      <div class="conv-detail hidden mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
        <div class="conv-detail-body text-xs text-slate-400 text-center py-2">Chargement…</div>
      </div>
    </div>`;
}

async function toggleConvDetail(convId, cardEl) {
  const detail = cardEl.querySelector('.conv-detail');
  const arrow  = cardEl.querySelector('.conv-arrow');
  if (!detail.classList.contains('hidden')) {
    detail.classList.add('hidden');
    if (arrow) arrow.textContent = 'expand_more';
    return;
  }
  detail.classList.remove('hidden');
  if (arrow) arrow.textContent = 'expand_less';

  const body = detail.querySelector('.conv-detail-body');
  try {
    const messages = await _apiFetch(`/api/admin/conversations/${convId}/messages`);
    if (messages.length === 0) {
      body.innerHTML = '<p class="text-center py-2">Aucun message</p>';
      return;
    }
    body.innerHTML = `<div class="space-y-2">${messages.map(m => `
      <div class="rounded-lg p-2.5 ${m.had_answer
        ? 'bg-slate-50 dark:bg-slate-700/50'
        : 'bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800'}">
        <p class="text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">
          <span class="text-primary">Q :</span> ${escapeHtml(m.question)}
        </p>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          <span class="text-primary">R :</span>
          ${m.answer ? escapeHtml(m.answer.substring(0, 250)) + (m.answer.length > 250 ? '…' : '') : '—'}
        </p>
        ${!m.had_answer ? '<p class="text-[10px] text-amber-600 font-semibold mt-1">⚠ Sans réponse</p>' : ''}
      </div>`).join('')}
    </div>`;
  } catch {
    body.innerHTML = '<p class="text-center text-red-400 py-2">Erreur de chargement</p>';
  }
}

// ─── Questions sans réponse ───────────────────────────────────────────────

async function renderUnanswered(status, page) {
  _unansStatus = status;
  _unansPage   = page;
  const el = document.getElementById('analytics-unanswered-content');
  el.innerHTML = _loadingHtml();
  try {
    const data = await _apiFetch(`/api/admin/unanswered?status=${status}&page=${page}`);
    const totalPages = Math.ceil(data.total / 20);
    el.innerHTML = `
      <div class="flex gap-1.5 mb-3">
        ${_filterPill('pending', status, 'En attente')}
        ${_filterPill('resolved', status, 'Résolues')}
      </div>
      <p class="text-xs text-slate-400 mb-3">${data.total} question(s)</p>
      <div class="space-y-3">
        ${data.items.length === 0
          ? `<p class="text-center text-slate-400 text-sm py-6">
               ${status === 'pending' ? 'Aucune question en attente ✓' : 'Aucune question résolue'}
             </p>`
          : data.items.map(u => _unansweredCard(u)).join('')}
      </div>
      ${totalPages > 1 ? _pagination(page, totalPages, `renderUnanswered.bind(null,'${status}')`) : ''}`;
  } catch {
    el.innerHTML = _errorHtml();
  }
}

function _filterPill(value, current, label) {
  const active = value === current;
  return `<button onclick="renderUnanswered('${value}', 1)"
    class="text-xs px-3 py-1.5 rounded-full font-semibold transition-colors
           ${active
             ? (value === 'pending' ? 'bg-amber-500 text-white' : 'bg-green-500 text-white')
             : 'bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700'}">
    ${label}
  </button>`;
}

function _unansweredCard(u) {
  const isPending = u.status === 'pending';
  return `
    <div class="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm border
      ${isPending ? 'border-amber-200 dark:border-amber-800' : 'border-green-200 dark:border-green-900'}">
      <p class="text-xs font-bold text-slate-700 dark:text-slate-200 mb-1 flex items-start gap-2">
        <span class="material-symbols-outlined text-[16px] shrink-0 mt-0.5
          ${isPending ? 'text-amber-500' : 'text-green-500'}">
          ${isPending ? 'help' : 'check_circle'}
        </span>
        ${escapeHtml(u.question)}
      </p>
      <p class="text-[10px] text-slate-400 ml-6 mb-3">${_fmtDate(u.asked_at)}</p>
      ${isPending ? _resolveForm(u.id) : _resolvedResponse(u.admin_response)}
    </div>`;
}

function _resolvedResponse(response) {
  return `
    <div class="ml-6 bg-green-50 dark:bg-green-900/20 rounded-lg p-2.5">
      <p class="text-xs font-semibold text-green-700 dark:text-green-400 mb-1">Réponse ajoutée :</p>
      <p class="text-xs text-slate-600 dark:text-slate-300">${escapeHtml(response || '')}</p>
    </div>`;
}

function _resolveForm(id) {
  return `
    <div class="ml-6">
      <button onclick="toggleResolveForm('${id}')"
        class="text-xs bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg
               font-semibold transition-colors flex items-center gap-1.5">
        <span class="material-symbols-outlined text-[14px]">edit_note</span>
        Ajouter une réponse
      </button>
      <div id="rfc-${id}" class="hidden mt-2 space-y-2">
        <textarea id="rft-${id}" rows="4"
          class="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700
                 bg-slate-50 dark:bg-slate-700 focus:outline-none focus:border-primary/50 resize-none"
          placeholder="Rédigez la réponse à ajouter à la base de connaissances…"></textarea>
        <div class="flex gap-2">
          <button onclick="submitResolve('${id}')"
            class="flex-1 bg-primary hover:bg-primary/90 text-white py-2 rounded-lg text-xs
                   font-semibold transition-colors flex items-center justify-center gap-1.5">
            <span class="material-symbols-outlined text-[14px]">add_circle</span>
            Ajouter à la base RAG
          </button>
          <button onclick="toggleResolveForm('${id}')"
            class="px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-slate-600
                   border border-slate-200 dark:border-slate-700 transition-colors">
            Annuler
          </button>
        </div>
      </div>
    </div>`;
}

function toggleResolveForm(id) {
  document.getElementById('rfc-' + id).classList.toggle('hidden');
}

async function submitResolve(unansweredId) {
  const textarea = document.getElementById('rft-' + unansweredId);
  const response = textarea.value.trim();
  if (!response) { showToast('Veuillez saisir une réponse.', 'error'); return; }
  try {
    await _apiFetch(`/api/admin/unanswered/${unansweredId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ admin_response: response }),
    });
    showToast('Réponse ajoutée à la base RAG ✓', 'success');
    await renderUnanswered(_unansStatus, _unansPage);
    await refreshUnansweredBadge();
  } catch {
    showToast('Erreur lors de l\'enregistrement', 'error');
  }
}

// ─── Badge notification ───────────────────────────────────────────────────

async function refreshUnansweredBadge() {
  if (!state.isAdmin) return; // pas de token, inutile d'appeler
  try {
    const data  = await _apiFetch('/api/admin/stats');
    const badge = document.getElementById('analytics-badge');
    if (!badge) return;
    if (data.unanswered_pending > 0) {
      badge.textContent = data.unanswered_pending > 9 ? '9+' : data.unanswered_pending;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  } catch { /* réseau indisponible, on ignore */ }
}

// ─── Utilitaires internes ─────────────────────────────────────────────────

async function _apiFetch(url, options = {}) {
  const token = getAdminToken();
  if (token) {
    options.headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
  }
  const r = await fetch(url, options);
  if (r.status === 401) {
    logoutAdmin();
    throw new Error('Session expirée, veuillez vous reconnecter.');
  }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function _loadingHtml() {
  return '<div class="text-center py-8 text-slate-400 text-sm">Chargement…</div>';
}

function _errorHtml() {
  return '<p class="text-center text-red-400 text-sm py-6">Erreur de chargement</p>';
}

function _pagination(page, totalPages, callbackExpr) {
  return `
    <div class="flex items-center justify-center gap-3 mt-4">
      <button onclick="${callbackExpr}(${page - 1})" ${page === 1 ? 'disabled' : ''}
        class="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700
               disabled:opacity-40 hover:border-primary/40 transition-colors">
        ← Précédent
      </button>
      <span class="text-xs text-slate-400">${page} / ${totalPages}</span>
      <button onclick="${callbackExpr}(${page + 1})" ${page >= totalPages ? 'disabled' : ''}
        class="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700
               disabled:opacity-40 hover:border-primary/40 transition-colors">
        Suivant →
      </button>
    </div>`;
}

function _fmtDate(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr + 'Z').toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

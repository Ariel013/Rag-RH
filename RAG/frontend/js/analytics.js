// ─── Analytics Dashboard ──────────────────────────────────────────────────

let _analyticsView = 'overview';
let _convPage      = 1;
let _unansPage     = 1;
let _unansStatus   = 'pending';
let _allTopics     = [];  // cache pour les dropdowns de reassign

function loadAnalytics() {
  _allTopics = [];
  switchAnalyticsView('overview');
  refreshUnansweredBadge();
}

function switchAnalyticsView(view) {
  _analyticsView = view;
  ['overview', 'conversations', 'unanswered', 'topics'].forEach(v => {
    document.getElementById('av-' + v).classList.toggle('hidden', v !== view);
    const btn = document.getElementById('atab-' + v);
    if (!btn) return;
    if (v === view) {
      btn.classList.add('bg-white', 'dark:bg-slate-700', 'text-primary', 'shadow-sm');
      btn.classList.remove('text-slate-500');
    } else {
      btn.classList.remove('bg-white', 'dark:bg-slate-700', 'text-primary', 'shadow-sm');
      btn.classList.add('text-slate-500');
    }
  });
  if (view === 'overview')           renderOverview();
  else if (view === 'conversations') renderConversations(1);
  else if (view === 'unanswered')    renderUnanswered('pending', 1);
  else if (view === 'topics')        renderTopics();
}

// ─── Vue d'ensemble ───────────────────────────────────────────────────────

async function renderOverview() {
  const el = document.getElementById('analytics-overview-content');
  el.innerHTML = _loadingHtml();
  try {
    const data = await _apiFetch('/api/admin/stats');
    const total = data.total_questions || 0;
    el.innerHTML = `
      <div class="grid grid-cols-3 gap-2 mb-4">
        ${_statCard(total, 'Questions', 'forum')}
        ${_statCard(data.unanswered_pending, 'Sans réponse', 'help', data.unanswered_pending > 0 ? 'amber' : 'primary')}
        ${_statCard(data.total_conversations, 'Conversations', 'chat_bubble')}
      </div>
      ${data.unanswered_pending > 0 ? _alertBanner(data.unanswered_pending) : ''}
      <div class="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm border border-primary/10">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-bold text-sm text-highlight flex items-center gap-2">
            <span class="material-symbols-outlined text-[18px]">folder_special</span>
            Distribution par topic
          </h3>
          <button onclick="switchAnalyticsView('topics')"
            class="text-xs text-primary hover:underline font-semibold">
            Gérer les topics →
          </button>
        </div>
        ${(!data.top_topics || data.top_topics.length === 0)
          ? '<p class="text-xs text-slate-400 text-center py-4">Aucune donnée pour le moment</p>'
          : `<div class="space-y-2">${data.top_topics.map(t => _topicBarRow(t, total)).join('')}</div>
             ${data.unclassified > 0
               ? `<p class="text-[10px] text-slate-400 mt-2 text-right">${data.unclassified} question(s) non classées</p>`
               : ''}`
        }
      </div>`;
  } catch {
    el.innerHTML = _errorHtml();
  }
}

function _topicBarRow(topic, total) {
  const pct = total > 0 ? Math.round((topic.count / total) * 100) : 0;
  return `
    <div class="space-y-1">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-700 dark:text-slate-300 font-medium truncate">${escapeHtml(topic.name)}</span>
        <span class="shrink-0 text-primary font-bold ml-2">${topic.count}</span>
      </div>
      <div class="w-full bg-slate-100 dark:bg-slate-700 rounded-full h-1.5">
        <div class="bg-primary h-1.5 rounded-full transition-all" style="width:${pct}%"></div>
      </div>
    </div>`;
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

// ─── Topics ───────────────────────────────────────────────────────────────

async function renderTopics() {
  const el = document.getElementById('analytics-topics-content');
  el.innerHTML = _loadingHtml();
  _allTopics = [];
  try {
    const topics = await _apiFetch('/api/admin/topics');
    _allTopics = topics;
    el.innerHTML = `
      <div class="mb-4 bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm border border-primary/10">
        <h3 class="font-bold text-sm text-highlight mb-3 flex items-center gap-2">
          <span class="material-symbols-outlined text-[18px]">add_circle</span>
          Créer un topic personnalisé
        </h3>
        <div class="flex gap-2">
          <input id="new-topic-name" type="text" placeholder="Nom du topic…"
            class="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700
                   bg-slate-50 dark:bg-slate-700 focus:outline-none focus:border-primary/50"
            onkeydown="if(event.key==='Enter') submitCreateTopic()"/>
          <button onclick="submitCreateTopic()"
            class="px-4 py-2 bg-primary hover:bg-primary/90 text-white text-xs font-semibold
                   rounded-lg transition-colors flex items-center gap-1.5 shrink-0">
            <span class="material-symbols-outlined text-[14px]">add</span>
            Créer
          </button>
        </div>
      </div>
      <div class="space-y-2" id="topics-list">
        ${topics.length === 0
          ? '<p class="text-center text-slate-400 text-sm py-6">Aucun topic disponible</p>'
          : topics.map(t => _topicCard(t)).join('')}
      </div>`;
  } catch {
    el.innerHTML = _errorHtml();
  }
}

function _topicCard(t) {
  const badge = t.is_custom
    ? '<span class="text-[9px] bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 rounded-full font-bold ml-1.5">Perso</span>'
    : '';
  return `
    <div class="topic-card bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-primary/10" data-topic-id="${t.id}">
      <button onclick="toggleTopicDetail('${t.id}', this)"
        class="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-primary/5 rounded-xl transition-colors">
        <div class="flex items-center gap-2 min-w-0">
          <span class="material-symbols-outlined text-primary text-[18px] shrink-0">folder</span>
          <span class="font-semibold text-sm truncate">${escapeHtml(t.name)}</span>
          ${badge}
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <span class="text-xs font-bold text-primary">${t.count} question${t.count > 1 ? 's' : ''}</span>
          <span class="material-symbols-outlined text-slate-300 text-[18px] topic-arrow">expand_more</span>
        </div>
      </button>
      <div class="topic-detail hidden px-4 pb-3">
        <div class="topic-detail-body text-xs text-slate-400 text-center py-2">Chargement…</div>
      </div>
    </div>`;
}

async function toggleTopicDetail(topicId, btnEl) {
  const card   = btnEl.closest('.topic-card');
  const detail = card.querySelector('.topic-detail');
  const arrow  = card.querySelector('.topic-arrow');

  if (!detail.classList.contains('hidden')) {
    detail.classList.add('hidden');
    if (arrow) arrow.textContent = 'expand_more';
    return;
  }

  detail.classList.remove('hidden');
  if (arrow) arrow.textContent = 'expand_less';

  const body = detail.querySelector('.topic-detail-body');
  try {
    const data = await _apiFetch(`/api/admin/topics/${topicId}/messages`);
    if (_allTopics.length === 0) {
      _allTopics = await _apiFetch('/api/admin/topics');
    }

    if (data.items.length === 0) {
      body.innerHTML = '<p class="text-center py-3 text-slate-400">Aucune question dans ce topic</p>';
      return;
    }

    const more = data.total > data.items.length
      ? `<p class="text-[10px] text-slate-400 text-center mt-2">${data.total - data.items.length} question(s) supplémentaire(s) non affichées</p>`
      : '';

    body.innerHTML = `
      <div class="space-y-1 max-h-72 overflow-y-auto pr-1">
        ${data.items.map(m => _topicMessageRow(m, topicId)).join('')}
      </div>
      ${more}`;
  } catch {
    body.innerHTML = '<p class="text-center text-red-400 py-2">Erreur de chargement</p>';
  }
}

function _topicMessageRow(m, currentTopicId) {
  const otherTopics = _allTopics.filter(t => t.id !== currentTopicId);
  const options = otherTopics.map(t =>
    `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`
  ).join('');

  return `
    <div class="flex items-center gap-2 py-2 border-b border-slate-50 dark:border-slate-700 last:border-0" id="tmsg-${m.id}">
      <span class="flex-1 text-xs text-slate-700 dark:text-slate-300 leading-tight">${escapeHtml(m.question)}</span>
      <select onchange="reassignMessageTopic('${m.id}', this.value, this)"
        class="shrink-0 text-[10px] py-1 px-1.5 rounded border border-slate-200 dark:border-slate-700
               bg-white dark:bg-slate-700 text-slate-500 focus:outline-none focus:border-primary/50 cursor-pointer">
        <option value="">Déplacer →</option>
        ${options}
      </select>
    </div>`;
}

async function reassignMessageTopic(messageId, newTopicId, selectEl) {
  if (!newTopicId) return;
  selectEl.disabled = true;
  try {
    await _apiFetch(`/api/admin/messages/${messageId}/topic`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ topic_id: newTopicId }),
    });
    const row = document.getElementById('tmsg-' + messageId);
    if (row) row.remove();
    showToast('Question déplacée ✓', 'success');
    // Rafraîchir les compteurs
    _allTopics = [];
    renderTopics();
  } catch {
    selectEl.disabled = false;
    selectEl.value = '';
    showToast('Erreur lors du déplacement', 'error');
  }
}

async function submitCreateTopic() {
  const input = document.getElementById('new-topic-name');
  const name  = input.value.trim();
  if (!name) { showToast('Entrez un nom de topic', 'error'); return; }

  try {
    await _apiFetch('/api/admin/topics', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name }),
    });
    input.value = '';
    _allTopics  = [];
    showToast(`Topic "${name}" créé ✓`, 'success');
    renderTopics();
  } catch (err) {
    showToast(`Erreur : ${err.message}`, 'error');
  }
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
      <div class="flex items-start justify-between gap-2 mb-1">
        <p class="text-xs font-bold text-slate-700 dark:text-slate-200 flex items-start gap-2">
          <span class="material-symbols-outlined text-[16px] shrink-0 mt-0.5
            ${isPending ? 'text-amber-500' : 'text-green-500'}">
            ${isPending ? 'help' : 'check_circle'}
          </span>
          ${escapeHtml(u.question)}
        </p>
        <button onclick="deleteUnanswered('${u.id}', this)"
          class="shrink-0 p-1 rounded-lg hover:bg-red-50 hover:text-red-500 text-slate-300 transition-colors" title="Supprimer cette question">
          <span class="material-symbols-outlined text-[16px]">delete</span>
        </button>
      </div>
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

async function deleteUnanswered(unansweredId, btnEl) {
  if (!confirm('Supprimer cette question ?')) return;
  try {
    await _apiFetch(`/api/admin/unanswered/${unansweredId}`, { method: 'DELETE' });
    btnEl.closest('.bg-white, .dark\\:bg-slate-800').remove();
    showToast('Question supprimée', 'success');
  } catch (err) {
    showToast(`Erreur : ${err.message}`, 'error');
  }
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

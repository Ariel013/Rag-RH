// ─── Welcome HTML builder ─────────────────────────────────────────────────
function buildWelcomeHTML(time, date) {
  return `
    <div class="flex justify-center">
      <span class="text-xs font-semibold text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-3 py-1 rounded-full uppercase tracking-wider">${date}</span>
    </div>
    <div class="flex items-start gap-3">
      <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shrink-0">
        <span class="material-symbols-outlined text-white text-sm">smart_toy</span>
      </div>
      <div class="flex flex-col gap-1 max-w-[85%]">
        <div class="bg-primary text-white p-4 rounded-xl rounded-tl-none text-[15px] leading-relaxed">
          Bonjour ! Je suis votre assistant RH. Comment puis-je vous aider aujourd'hui ?
        </div>
        <span class="text-[10px] text-slate-400 ml-1">Assistant • ${time}</span>
      </div>
    </div>
    <div id="quick-actions" class="grid grid-cols-2 gap-2">
      <button onclick="sendQuickAction('Quelles sont les politiques de congés de l\\'entreprise ?')"
        class="flex items-center gap-2 px-3 py-3 bg-white dark:bg-slate-800 border border-primary/20 rounded-xl text-highlight dark:text-slate-100 hover:bg-primary/5 transition-colors text-sm font-semibold shadow-sm">
        <span class="material-symbols-outlined text-primary text-[20px]">policy</span><span>Politiques</span>
      </button>
      <button onclick="sendQuickAction('Quels sont mes avantages sociaux et ma mutuelle ?')"
        class="flex items-center gap-2 px-3 py-3 bg-white dark:bg-slate-800 border border-primary/20 rounded-xl text-highlight dark:text-slate-100 hover:bg-primary/5 transition-colors text-sm font-semibold shadow-sm">
        <span class="material-symbols-outlined text-primary text-[20px]">featured_seasonal_and_gifts</span><span>Avantages</span>
      </button>
      <button onclick="sendQuickAction('Comment poser des congés et combien de jours ai-je ?')"
        class="flex items-center gap-2 px-3 py-3 bg-white dark:bg-slate-800 border border-primary/20 rounded-xl text-highlight dark:text-slate-100 hover:bg-primary/5 transition-colors text-sm font-semibold shadow-sm">
        <span class="material-symbols-outlined text-primary text-[20px]">event_busy</span><span>Congés</span>
      </button>
      <button onclick="sendQuickAction('Quelle est la procédure de remboursement des frais professionnels ?')"
        class="flex items-center gap-2 px-3 py-3 bg-white dark:bg-slate-800 border border-primary/20 rounded-xl text-highlight dark:text-slate-100 hover:bg-primary/5 transition-colors text-sm font-semibold shadow-sm">
        <span class="material-symbols-outlined text-primary text-[20px]">receipt_long</span><span>Frais</span>
      </button>
    </div>
    <div id="quick-chips" class="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
      <button onclick="sendQuickAction('Quel est mon solde de congés payés ?')"
        class="whitespace-nowrap px-3 py-1.5 bg-highlight/10 text-highlight dark:bg-highlight/20 rounded-full text-xs font-bold border border-highlight/20 hover:bg-highlight/20 transition-colors">Solde de congés ?</button>
      <button onclick="sendQuickAction('Comment fonctionne ma mutuelle santé ?')"
        class="whitespace-nowrap px-3 py-1.5 bg-highlight/10 text-highlight dark:bg-highlight/20 rounded-full text-xs font-bold border border-highlight/20 hover:bg-highlight/20 transition-colors">Mutuelle santé</button>
      <button onclick="sendQuickAction('Comment obtenir ma fiche de paie ?')"
        class="whitespace-nowrap px-3 py-1.5 bg-highlight/10 text-highlight dark:bg-highlight/20 rounded-full text-xs font-bold border border-highlight/20 hover:bg-highlight/20 transition-colors">Fiche de paie</button>
      <button onclick="sendQuickAction('Comment fonctionne le télétravail ?')"
        class="whitespace-nowrap px-3 py-1.5 bg-highlight/10 text-highlight dark:bg-highlight/20 rounded-full text-xs font-bold border border-highlight/20 hover:bg-highlight/20 transition-colors">Télétravail</button>
    </div>`;
}

// ─── Init session ─────────────────────────────────────────────────────────
function initSession() {
  const convs = getConversations();
  if (convs.length > 0) {
    state.currentId = convs[0].id;
    _msgLog = convs[0].messages || [];
    if (_msgLog.length > 0) {
      loadConversationIntoDOM(convs[0]);
    }
  } else {
    const conv = createConversation();
    state.currentId = conv.id;
    _msgLog = [];
  }
}

// ─── DOM rebuild from stored conversation ─────────────────────────────────
function loadConversationIntoDOM(conv) {
  const container = document.getElementById('messages-container');
  const date  = new Date(conv.createdAt).toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long' });
  const wTime = new Date(conv.createdAt).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});

  container.innerHTML = `
    <div class="flex justify-center">
      <span class="text-xs font-semibold text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-3 py-1 rounded-full uppercase tracking-wider">${date}</span>
    </div>
    <div class="flex items-start gap-3">
      <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shrink-0">
        <span class="material-symbols-outlined text-white text-sm">smart_toy</span>
      </div>
      <div class="flex flex-col gap-1 max-w-[85%]">
        <div class="bg-primary text-white p-4 rounded-xl rounded-tl-none text-[15px] leading-relaxed">
          Bonjour ! Je suis votre assistant RH. Comment puis-je vous aider aujourd'hui ?
        </div>
        <span class="text-[10px] text-slate-400 ml-1">Assistant • ${wTime}</span>
      </div>
    </div>`;

  conv.messages.forEach(msg => {
    if (msg.type === 'user') {
      container.insertAdjacentHTML('beforeend', `
        <div class="flex justify-end">
          <div class="flex flex-col items-end gap-1 max-w-[80%]">
            <div class="bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 p-3.5 rounded-xl rounded-tr-none text-[15px] leading-relaxed shadow-sm border border-slate-100 dark:border-slate-600">
              ${escapeHtml(msg.text)}
            </div>
            <span class="text-[10px] text-slate-400">Vous • ${msg.time}</span>
          </div>
        </div>`);
    } else if (msg.type === 'bot') {
      container.insertAdjacentHTML('beforeend', `
        <div class="flex items-start gap-3 bot-message">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shrink-0">
            <span class="material-symbols-outlined text-white text-sm">smart_toy</span>
          </div>
          <div class="flex flex-col gap-1.5 max-w-[85%]">
            <div class="bg-primary text-white p-4 rounded-xl rounded-tl-none text-[15px] leading-relaxed">${msg.html}</div>
            <span class="text-[10px] text-slate-400 ml-1">Assistant • ${msg.time}</span>
          </div>
        </div>`);
    }
  });

  scrollToBottom();
}

// ─── Sidebar — défini dans ui.js, renderConversationList appelé à l'init ──

function renderConversationList() {
  const list  = document.getElementById('conversations-list');
  const convs = getConversations();

  if (convs.length === 0) {
    list.innerHTML = '<p class="text-xs text-slate-400 text-center py-6">Aucune conversation</p>';
    return;
  }

  list.innerHTML = convs.map(conv => {
    const isActive = conv.id === state.currentId;
    const title    = conv.title || 'Nouvelle conversation';
    const timeStr  = formatConvTime(conv.updatedAt);
    return `
      <div class="group relative flex items-center gap-1">
        <button onclick="switchConversation('${conv.id}')"
          class="flex-1 text-left px-3 py-2.5 rounded-xl transition-colors text-sm min-w-0 ${isActive
            ? 'bg-primary/10 text-primary'
            : 'hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200'}">
          <p class="truncate font-medium text-sm">${escapeHtml(title)}</p>
          <p class="text-[10px] mt-0.5 ${isActive ? 'text-primary/70' : 'text-slate-400'}">${timeStr}</p>
        </button>
        <button onclick="removeConversation('${conv.id}')"
          class="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-400 hover:text-red-500 transition-all shrink-0 mr-1" title="Supprimer">
          <span class="material-symbols-outlined text-[15px]">delete</span>
        </button>
      </div>`;
  }).join('');
}

function formatConvTime(ts) {
  const diff = Date.now() - ts;
  if (diff < 60000)    return 'À l\'instant';
  if (diff < 3600000)  return Math.floor(diff / 60000) + ' min';
  if (diff < 86400000) return new Date(ts).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  return new Date(ts).toLocaleDateString('fr-FR', {day:'2-digit', month:'2-digit'});
}

function removeConversation(id) {
  let convs = getConversations().filter(c => c.id !== id);
  saveConversations(convs);
  if (state.currentId === id) {
    convs = getConversations();
    if (convs.length > 0) {
      switchConversation(convs[0].id);
    } else {
      startFreshConversation();
    }
  }
  renderConversationList();
}

function switchConversation(id) {
  if (id === state.currentId) { closeSidebar(); return; }
  const convs = getConversations();
  const conv  = convs.find(c => c.id === id);
  if (!conv) return;

  state.currentId  = id;
  _msgLog          = conv.messages || [];
  state.isStreaming = false;
  document.getElementById('chat-input').disabled = false;
  document.getElementById('send-btn').disabled   = false;

  if (_msgLog.length > 0) {
    loadConversationIntoDOM(conv);
  } else {
    const time = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
    const date = new Date().toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long' });
    document.getElementById('messages-container').innerHTML = buildWelcomeHTML(time, date);
  }

  switchTab('chat');
  closeSidebar();
}

// ─── Nouvelle conversation ────────────────────────────────────────────────
function newConversation() {
  if (state.isStreaming) return;
  startFreshConversation();
  closeSidebar();
}

function startFreshConversation() {
  const conv = createConversation();
  state.currentId = conv.id;
  _msgLog = [];

  const time = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  const date = new Date().toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long' });
  document.getElementById('messages-container').innerHTML = buildWelcomeHTML(time, date);

  switchTab('chat');
  const input = document.getElementById('chat-input');
  input.value = '';
  input.disabled = false;
  document.getElementById('send-btn').disabled = false;
  input.focus();
}

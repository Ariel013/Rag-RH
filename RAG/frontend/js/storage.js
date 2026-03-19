// ─── Conversation storage ─────────────────────────────────────────────────

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

function getConversations() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const now = Date.now();
    return JSON.parse(raw).filter(c => now - c.updatedAt < EXPIRY_MS);
  } catch { return []; }
}

function saveConversations(convs) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(convs));
}

function createConversation() {
  const conv = {
    id: genId(),
    title: '',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    chatHistory: [],
    messages: [],
  };
  const convs = getConversations();
  convs.unshift(conv);
  saveConversations(convs);
  return conv;
}

function persistCurrent(chatHistory) {
  if (!state.currentId) return;
  const convs = getConversations();
  const idx = convs.findIndex(c => c.id === state.currentId);
  if (idx === -1) return;
  convs[idx].chatHistory = chatHistory.slice(-20);
  convs[idx].messages    = [..._msgLog];
  convs[idx].updatedAt   = Date.now();
  if (!convs[idx].title) {
    const first = _msgLog.find(m => m.type === 'user');
    if (first) convs[idx].title = first.text.slice(0, 50);
  }
  saveConversations(convs);
}

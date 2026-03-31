// ─── Constants ────────────────────────────────────────────────────────────
const STORAGE_KEY    = 'rh_conversations';
const EXPIRY_MS      = 24 * 60 * 60 * 1000; // 24h — cache UI local
const ADMIN_SK       = 'aeig_admin_session';
const ADMIN_TOKEN_SK = 'aeig_admin_token';

// ─── State ────────────────────────────────────────────────────────────────
const state = {
  currentId:    null,
  isStreaming:  false,
  selectedFile: null,
  currentTab:   'chat',
  isAdmin:      false,
};

// Snapshot des messages de la conversation courante (pour la persistance)
let _msgLog = [];

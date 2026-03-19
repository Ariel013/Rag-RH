// ─── Constants ────────────────────────────────────────────────────────────
const STORAGE_KEY = 'rh_conversations';
const EXPIRY_MS   = 24 * 60 * 60 * 1000; // 24h
const ADMIN_EMAIL = 'admin@rag.com';
const ADMIN_PWD   = '12345678';
const ADMIN_SK    = 'aeig_admin_session';

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

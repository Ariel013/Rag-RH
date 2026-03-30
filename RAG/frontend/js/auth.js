// ─── Auth ─────────────────────────────────────────────────────────────────

function checkAdminSession() {
  state.isAdmin = sessionStorage.getItem(ADMIN_SK) === '1';
  updateLockIcon();
}

function updateLockIcon() {
  const lock  = document.getElementById('base-lock');
  const alock = document.getElementById('analytics-lock');
  if (lock)  lock.style.display  = state.isAdmin ? 'none' : '';
  if (alock) alock.style.display = state.isAdmin ? 'none' : '';
}

function openBaseTab() {
  if (state.isAdmin) { switchTab('base'); return; }
  _pendingAdminTab = 'base';
  document.getElementById('login-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('login-email').focus(), 50);
}

function openAnalyticsTab() {
  if (state.isAdmin) { switchTab('analytics'); return; }
  _pendingAdminTab = 'analytics';
  document.getElementById('login-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('login-email').focus(), 50);
}

let _pendingAdminTab = 'base';

function closeLoginModal() {
  document.getElementById('login-modal').classList.add('hidden');
  document.getElementById('login-error').classList.add('hidden');
  document.getElementById('login-email').value = '';
  document.getElementById('login-password').value = '';
}

function submitLogin() {
  const email = document.getElementById('login-email').value.trim().toLowerCase();
  const pwd   = document.getElementById('login-password').value;
  const err   = document.getElementById('login-error');
  if (email === ADMIN_EMAIL && pwd === ADMIN_PWD) {
    state.isAdmin = true;
    sessionStorage.setItem(ADMIN_SK, '1');
    updateLockIcon();
    closeLoginModal();
    switchTab(_pendingAdminTab || 'base');
  } else {
    err.classList.remove('hidden');
    document.getElementById('login-password').value = '';
    document.getElementById('login-password').focus();
  }
}

function logoutAdmin() {
  state.isAdmin = false;
  sessionStorage.removeItem(ADMIN_SK);
  updateLockIcon();
  switchTab('chat');
  showToast('Déconnecté', 'info');
}

function togglePasswordVisibility() {
  const input = document.getElementById('login-password');
  const eye   = document.getElementById('pwd-eye');
  if (input.type === 'password') {
    input.type = 'text';
    eye.textContent = 'visibility_off';
  } else {
    input.type = 'password';
    eye.textContent = 'visibility';
  }
}

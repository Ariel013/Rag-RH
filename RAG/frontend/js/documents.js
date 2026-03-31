// ─── File upload ──────────────────────────────────────────────────────────
function triggerFileUpload() {
  if (!state.isAdmin) { openBaseTab(); return; }
  document.getElementById('file-input').click();
}

function handleFileSelected(event) {
  const file = event.target.files[0];
  if (!file) return;
  state.selectedFile = file;
  switchTab('base');
  showUploadForm(file.name);
}

function handleDrop(event) {
  event.preventDefault();
  document.getElementById('upload-zone').classList.remove('dragover');
  const file = event.dataTransfer.files[0];
  if (!file) return;
  state.selectedFile = file;
  showUploadForm(file.name);
}

function showUploadForm(filename) {
  document.getElementById('selected-filename').textContent = filename;
  document.getElementById('upload-form').classList.remove('hidden');
  document.getElementById('upload-zone').style.display = 'none';
}

function cancelUpload() {
  state.selectedFile = null;
  document.getElementById('upload-form').classList.add('hidden');
  document.getElementById('upload-zone').style.display = '';
  document.getElementById('file-input').value = '';
  document.getElementById('upload-title').value = '';
}

async function submitUpload() {
  if (!state.selectedFile) return;
  const title    = document.getElementById('upload-title').value.trim();
  const category = document.getElementById('upload-category').value;

  document.getElementById('upload-form').classList.add('hidden');
  document.getElementById('upload-progress').classList.remove('hidden');
  document.getElementById('upload-status').textContent = 'Analyse et indexation…';

  try {
    const fd = new FormData();
    fd.append('file',     state.selectedFile);
    fd.append('title',    title);
    fd.append('category', category);

    const token = getAdminToken();
    const resp = await fetch('/api/documents/upload', {
      method:  'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body:    fd,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Erreur upload');

    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('upload-zone').style.display = '';
    document.getElementById('file-input').value = '';
    state.selectedFile = null;
    document.getElementById('upload-title').value = '';
    showToast(`✓ "${data.title}" indexé (${data.chunks} sections)`, 'success');
    loadDocuments();
  } catch (err) {
    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('upload-form').classList.remove('hidden');
    showToast(`Erreur : ${err.message}`, 'error');
  }
}

// ─── Document list ────────────────────────────────────────────────────────
async function loadDocuments() {
  const list = document.getElementById('docs-list');
  list.innerHTML = '<div class="text-center py-4 text-slate-400 text-sm">Chargement…</div>';
  try {
    const resp = await fetch('/api/documents');
    const data = await resp.json();
    const docs = data.documents || [];

    const el = document.getElementById('doc-count-profil');
    if (el) el.textContent = docs.length + ' doc' + (docs.length > 1 ? 's' : '');

    if (docs.length === 0) {
      list.innerHTML = `
        <div class="text-center py-6 text-slate-400">
          <span class="material-symbols-outlined text-[36px] mb-2 block">folder_open</span>
          <p class="text-sm">Aucun document indexé</p>
        </div>`;
      return;
    }

    list.innerHTML = '';
    const catColors = {
      'Congés':           'bg-blue-50 text-blue-600 border-blue-100',
      'Avantages sociaux':'bg-green-50 text-green-600 border-green-100',
      'Procédures':       'bg-orange-50 text-orange-600 border-orange-100',
      'Télétravail':      'bg-purple-50 text-purple-600 border-purple-100',
      'Formation':        'bg-yellow-50 text-yellow-600 border-yellow-100',
      'Paie':             'bg-red-50 text-red-600 border-red-100',
    };

    docs.forEach(doc => {
      const color = catColors[doc.category] || 'bg-slate-50 text-slate-600 border-slate-100';
      const item  = document.createElement('div');
      item.className = 'flex items-center gap-3 p-3 rounded-xl border border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors group';
      item.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <span class="material-symbols-outlined text-primary text-[18px]">description</span>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold truncate">${escapeHtml(doc.title)}</p>
          <span class="inline-block text-[10px] font-bold px-2 py-0.5 rounded-full border ${color}">${escapeHtml(doc.category)}</span>
        </div>
        <button onclick="deleteDocument('${doc.id}', this)"
          class="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg hover:bg-red-50 hover:text-red-500 text-slate-400 transition-all" title="Supprimer">
          <span class="material-symbols-outlined text-[16px]">delete</span>
        </button>`;
      list.appendChild(item);
    });
  } catch {
    list.innerHTML = '<div class="text-center py-4 text-red-400 text-sm">Impossible de charger les documents</div>';
  }
}

async function deleteDocument(docId, btnEl) {
  if (!confirm('Supprimer ce document de la base de connaissances ?')) return;
  try {
    const token = getAdminToken();
    const resp = await fetch(`/api/documents/${docId}`, {
      method:  'DELETE',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new Error('Erreur suppression');
    btnEl.closest('.flex.items-center').remove();
    showToast('Document supprimé', 'success');
    loadDocuments();
  } catch (err) {
    showToast(`Erreur : ${err.message}`, 'error');
  }
}

// ─── Chat ─────────────────────────────────────────────────────────────────
function handleSend() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text || state.isStreaming) return;
  input.value = '';
  sendMessage(text);
}

function sendQuickAction(text) {
  if (state.isStreaming) return;
  switchTab('chat');
  setTimeout(() => sendMessage(text), 50);
}

async function sendMessage(question) {
  state.isStreaming = true;
  document.getElementById('send-btn').disabled = true;
  document.getElementById('chat-input').disabled = true;

  // Masquer quick actions au 1er message
  const qa = document.getElementById('quick-actions');
  const qc = document.getElementById('quick-chips');
  if (qa) qa.style.display = 'none';
  if (qc) qc.style.display = 'none';

  const time = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  appendMessage('user', question);
  _msgLog.push({ type: 'user', text: question, time });

  // Récupérer chatHistory stocké
  const convs = getConversations();
  const conv  = convs.find(c => c.id === state.currentId);
  const chatHistory = conv ? [...(conv.chatHistory || [])] : [];
  chatHistory.push({ role: 'user', content: question });

  const typingEl = appendTyping();
  scrollToBottom();

  const history = chatHistory.slice(0, -1);
  let botText = '';
  let sources = null;
  let hadAnswer = true;
  let streamDone = false;
  const botTime = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history, conversation_id: state.currentId || '' }),
    });

    if (!resp.ok) throw new Error(`Erreur serveur (${resp.status})`);

    typingEl.remove();
    const botBubble = appendBotBubble();
    const textNode  = botBubble.querySelector('.bot-text');
    scrollToBottom();

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (!streamDone) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.type === 'sources') {
            sources = data.sources;
          } else if (data.type === 'text_delta') {
            botText += data.content;
            textNode.innerHTML = renderMarkdown(botText);
            scrollToBottom();
          } else if (data.type === 'error') {
            textNode.innerHTML = `<span class="text-red-300">⚠ ${escapeHtml(data.message)}</span>`;
            streamDone = true; break;
          } else if (data.type === 'done') {
            hadAnswer = data.had_answer !== false;
            streamDone = true; break;
          }
        } catch { /* ignore malformed */ }
      }
    }

    // Sources, seulement si l'assistant a répondu
    const shownSources = hadAnswer && sources ? sources : [];
    textNode.insertAdjacentHTML('afterend', sourcesHTML(shownSources));

    // Persister
    if (botText) {
      _msgLog.push({ type: 'bot', html: renderMarkdown(botText), sources: shownSources, time: botTime });
      chatHistory.push({ role: 'assistant', content: botText });
      persistCurrent(chatHistory);
    }

  } catch (err) {
    typingEl.remove();
    appendMessage('bot-error', err.message);
  }

  state.isStreaming = false;
  document.getElementById('send-btn').disabled = false;
  document.getElementById('chat-input').disabled = false;
  document.getElementById('chat-input').focus();
  scrollToBottom();
}

// ─── Message builders ─────────────────────────────────────────────────────
function appendMessage(role, text) {
  const container = document.getElementById('messages-container');
  const time = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  if (role === 'user') {
    container.insertAdjacentHTML('beforeend', `
      <div class="flex justify-end">
        <div class="flex flex-col items-end gap-1 max-w-[80%]">
          <div class="bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 p-3.5 rounded-xl rounded-tr-none text-[15px] leading-relaxed shadow-sm border border-slate-100 dark:border-slate-600">
            ${escapeHtml(text)}
          </div>
          <span class="text-[10px] text-slate-400">Vous • ${time}</span>
        </div>
      </div>`);
  } else {
    container.insertAdjacentHTML('beforeend', `
      <div class="flex items-start gap-3 bot-message">
        <div class="w-8 h-8 rounded-full bg-red-500 flex items-center justify-center shrink-0">
          <span class="material-symbols-outlined text-white text-sm">error</span>
        </div>
        <div class="bg-red-50 text-red-700 p-3 rounded-xl text-sm">${escapeHtml(text)}</div>
      </div>`);
  }
}

function appendTyping() {
  const container = document.getElementById('messages-container');
  const div = document.createElement('div');
  div.className = 'flex items-start gap-3';
  div.innerHTML = `
    <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shrink-0">
      <span class="material-symbols-outlined text-white text-sm">smart_toy</span>
    </div>
    <div class="bg-primary/10 dark:bg-primary/20 px-4 py-3 rounded-xl rounded-tl-none flex items-center gap-1.5 h-10">
      <span class="typing-dot w-2 h-2 rounded-full bg-primary/60"></span>
      <span class="typing-dot w-2 h-2 rounded-full bg-primary/60"></span>
      <span class="typing-dot w-2 h-2 rounded-full bg-primary/60"></span>
    </div>`;
  container.appendChild(div);
  return div;
}

function appendBotBubble() {
  const container = document.getElementById('messages-container');
  const time = new Date().toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  const div  = document.createElement('div');
  div.className = 'flex items-start gap-3 bot-message';
  div.innerHTML = `
    <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shrink-0">
      <span class="material-symbols-outlined text-white text-sm">smart_toy</span>
    </div>
    <div class="flex flex-col gap-1.5 max-w-[85%]">
      <div class="bg-primary text-white p-4 rounded-xl rounded-tl-none text-[15px] leading-relaxed bot-text"></div>
      <span class="text-[10px] text-slate-400 ml-1">Assistant • ${time}</span>
    </div>`;
  container.appendChild(div);
  return div;
}

// ─── Sources : pages consultées, et passages exacts envoyés au LLM ───────
let _sourcesSeq = 0;

function sourcesHTML(sources) {
  if (!sources || !sources.length) return '';
  const uid = `src-${++_sourcesSeq}`;
  const chips = sources.map((s, i) => {
    const hasText = Array.isArray(s.extraits) && s.extraits.length;
    const label = `<span class="material-symbols-outlined text-[14px]" aria-hidden="true">description</span>${escapeHtml(s.title)}`;
    return hasText
      ? `<button type="button" onclick="toggleSource(this)" aria-expanded="false" aria-controls="${uid}-${i}"
           class="source-chip inline-flex items-center gap-1 px-2.5 py-1 bg-primary/10 text-primary dark:text-slate-200 dark:bg-primary/30 rounded-full text-[11px] font-semibold border border-primary/20 hover:bg-primary/20 transition-colors">${label}</button>`
      : `<span class="inline-flex items-center gap-1 px-2.5 py-1 bg-primary/10 text-primary dark:text-slate-200 dark:bg-primary/30 rounded-full text-[11px] font-semibold border border-primary/20">${label}</span>`;
  }).join('');
  const panels = sources.map((s, i) => {
    if (!Array.isArray(s.extraits) || !s.extraits.length) return '';
    const texte = s.extraits.map(escapeHtml).join('\n\n[…]\n\n');
    return `<div id="${uid}-${i}" class="source-extrait hidden mt-2 p-3 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-[13px] leading-relaxed text-slate-700 dark:text-slate-200 whitespace-pre-line max-h-64 overflow-y-auto"><p class="font-semibold text-slate-900 dark:text-slate-100 mb-1">${escapeHtml(s.title)}</p>${texte}</div>`;
  }).join('');
  return `<div class="sources px-1">
      <p class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Passages consultés</p>
      <div class="flex flex-wrap gap-1.5">${chips}</div>${panels}
    </div>`;
}

function toggleSource(btn) {
  const box   = btn.closest('.sources');
  const panel = document.getElementById(btn.getAttribute('aria-controls'));
  const open  = btn.getAttribute('aria-expanded') !== 'true';
  box.querySelectorAll('.source-chip').forEach(b => b.setAttribute('aria-expanded', 'false'));
  box.querySelectorAll('.source-extrait').forEach(p => p.classList.add('hidden'));
  if (open) {
    btn.setAttribute('aria-expanded', 'true');
    panel.classList.remove('hidden');
  }
}

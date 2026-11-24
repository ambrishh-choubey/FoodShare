/* FoodShare Smart Assistant window. Messages and replies are inserted with textContent
   (never as HTML), so nothing a user types or a reply contains can run as code. */
(function () {
  'use strict';
  const FS = window.FoodShare;
  const root = document.getElementById('fs-chatbot');
  if (!FS || !root) { return; }

  const toggle = document.getElementById('fs-chat-toggle');
  const panel = document.getElementById('fs-chat-panel');
  const log = document.getElementById('fs-chat-log');
  const suggest = document.getElementById('fs-chat-suggest');
  const form = document.getElementById('fs-chat-form');
  const input = document.getElementById('fs-chat-input');
  const KEY = 'fs-chat';           // sessionStorage: this tab only, never sent anywhere
  const MAX_SAVED = 40;

  let meta = null;                 // { user_id, role, suggestions } from /chatbot/start
  let messages = [];               // { who: 'user'|'bot'|'error', text, links }
  let busy = false;

  // ---- per-tab history (cleared by "Clear", by logout, and when the tab closes)
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify({ uid: meta.user_id, role: meta.role, messages: messages.slice(-MAX_SAVED) })); } catch (e) { /* storage unavailable */ }
  }
  function forget() { try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ } }
  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(KEY) || 'null');
      if (saved && saved.uid === meta.user_id && saved.role === meta.role && Array.isArray(saved.messages)) { return saved.messages; }
    } catch (e) { /* ignore */ }
    return [];
  }
  document.addEventListener('submit', function (e) {   // logging out must not leave answers behind
    if (e.target && /\/logout$/.test(e.target.getAttribute('action') || '')) { forget(); }
  });

  // ---- rendering
  function bubble(m) {
    const div = document.createElement('div');
    div.className = 'fs-msg ' + (m.who === 'user' ? 'user' : 'bot') + (m.who === 'error' ? ' error' : '');
    div.textContent = m.text;
    if (m.links && m.links.length) {
      const box = document.createElement('div');
      box.className = 'fs-msg-links';
      m.links.forEach(function (l) {
        if (typeof l.url !== 'string' || l.url.charAt(0) !== '/' || l.url.charAt(1) === '/') { return; }  // same-site paths only
        const a = document.createElement('a');
        a.href = l.url;
        a.textContent = l.label;
        box.appendChild(a);
      });
      if (box.children.length) { div.appendChild(box); }
    }
    return div;
  }
  function scrollDown() { log.scrollTop = log.scrollHeight; }
  function render() {
    log.textContent = '';
    messages.forEach(function (m) { log.appendChild(bubble(m)); });
    scrollDown();
  }
  function showSuggestions(list) {
    suggest.textContent = '';
    (list || []).forEach(function (q) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = q;
      b.addEventListener('click', function () { send(q); });
      suggest.appendChild(b);
    });
  }
  function typing(on) {
    const old = document.getElementById('fs-typing');
    if (old) { old.remove(); }
    if (!on) { return; }
    const div = document.createElement('div');
    div.id = 'fs-typing';
    div.className = 'fs-msg bot fs-typing';
    div.setAttribute('aria-label', 'The assistant is typing');
    div.innerHTML = '<span></span><span></span><span></span>';   // fixed markup, no user data
    log.appendChild(div);
    scrollDown();
  }

  // ---- talking to the server
  async function start() {
    if (meta) { return; }
    try {
      const res = await FS.api('/chatbot/start');
      meta = res.data;
      messages = restore();
      if (!messages.length) { messages = [{ who: 'bot', text: meta.reply }]; }
      render();
      showSuggestions(meta.suggestions);
    } catch (err) {
      meta = { user_id: null, role: null };
      messages = [{ who: 'error', text: 'The assistant is unavailable right now. Please try again later.' }];
      render();
    }
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text || busy) { return; }
    busy = true;
    input.value = '';
    messages.push({ who: 'user', text: text });
    render();
    typing(true);
    try {
      const res = await FS.api('/chatbot/message', { method: 'POST', body: { message: text } });
      typing(false);
      messages.push({ who: 'bot', text: res.data.reply, links: res.data.links });
      showSuggestions(res.data.suggestions);
    } catch (err) {
      typing(false);
      messages.push({ who: 'error', text: err.message || 'Something went wrong. Please try again.' });
    }
    busy = false;
    render();
    save();
    input.focus();
  }

  // ---- open / close / clear
  function open() {
    panel.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Close FoodShare Smart Assistant');
    start().then(function () { input.focus(); });
  }
  function close() {
    panel.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open FoodShare Smart Assistant');
    toggle.focus();
  }
  toggle.addEventListener('click', function () { if (panel.hidden) { open(); } else { close(); } });
  document.getElementById('fs-chat-close').addEventListener('click', close);
  document.getElementById('fs-chat-clear').addEventListener('click', function () {
    forget();
    messages = meta ? [{ who: 'bot', text: meta.reply }] : [];
    render();
    showSuggestions(meta && meta.suggestions);
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { close(); } });
  form.addEventListener('submit', function (e) { e.preventDefault(); send(input.value); });
})();

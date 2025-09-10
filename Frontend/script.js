/* ============================================================================
   HushhVoice — script.js (Sign-In + OAuth + Chat + Threads, Clean + Fixed)
   ---------------------------------------------------------------------------
   • Google Sign-In (ID token) → /api/signin (verify identity)
   • OAuth buttons: Connect Mail, Connect Calendar, Connect Google Data (both)
   • Stores access_token + scopes in localStorage
   • Sends headers: X-User-Email and X-Google-Access-Token to backend
   • Chat UI + Threads + Settings modal
============================================================================ */
"use strict";

/* ============ CONFIG ============ */
const CONFIG = {
  API_BASE: `${location.protocol}//${location.hostname}:8000`,
  TIMEOUT_MS: 20000,
  GOOGLE_CLIENT_ID: "106283179463-48aftf364n2th97mone9s8mocicujt6c.apps.googleusercontent.com",
  KEYS: {
    THREADS: "hv_threads_v1",
    THREAD_ACTIVE: "hv_threads_active_v1",
    USER_EMAIL: "user_email",
  },
};

const OAUTH = {
  CLIENT_ID: CONFIG.GOOGLE_CLIENT_ID,
  SCOPE_MAIL: "https://www.googleapis.com/auth/gmail.readonly",
  SCOPE_CAL: "https://www.googleapis.com/auth/calendar.readonly",
  SCOPE_BOTH: "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly",
  LS_TOKEN: "google_access_token",
  LS_SCOPE: "google_access_scope",
};

/* ============ DOM HOOKS ============ */
const els = {
  // Chat UI
  chatBox: document.getElementById("chat-box"),
  input: document.getElementById("user-input"),
  sendBtn: document.getElementById("send-btn"),
  tplTyping: document.getElementById("tpl-typing"),
  tplAssistant: document.getElementById("tpl-assistant"),
  tplUser: document.getElementById("tpl-user"),

  // Settings
  openSettings: document.getElementById("open-settings"),
  settingsModal: document.getElementById("settings-modal"),

  // Threads
  threadsList: document.getElementById("chat-threads"),
  threadsEmpty: document.getElementById("chats-empty"),
  newChatBtn: document.getElementById("chat-new"),
  threadSearch: document.getElementById("chat-search"),
  tplThreadItem: document.getElementById("tpl-chat-thread"),
  tplThreadMenu: document.getElementById("tpl-thread-menu"),
  renameModal: document.getElementById("thread-rename-modal"),
  renameForm: document.getElementById("thread-rename-form"),
  renameInput: document.getElementById("thread-rename-input"),

  // Auth state
  profileSubtitle: document.getElementById("profile-subtitle"),
  profileHandle: document.getElementById("profile-handle"),
  googleBtnMount: document.getElementById("google-btn"),

  // OAuth action buttons (you added these in HTML)
  btnConnectMail: document.getElementById("btn-connect-mail"),
  btnConnectCal: document.getElementById("btn-connect-calendar"),
  btnConnectBoth: document.getElementById("btn-connect-both"),
};

/* ============ UTILITIES ============ */
const sanitize = (s) => (s ?? "").toString().trim();

function escapeHTML(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}
function renderMarkdownToHTML(md) {
  const raw = window.marked ? marked.parse(md || "") : (md || "");
  return window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
}
function renderFromTemplate(tpl, html) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  if (html != null) {
    const content = node.querySelector(".content");
    if (content) content.innerHTML = html;
  }
  return node;
}
function autoScrollChat() {
  if (!els.chatBox) return;
  els.chatBox.scrollTop = els.chatBox.scrollHeight;
}
function autoResize() {
  if (!els.input) return;
  els.input.style.height = "auto";
  els.input.style.height = Math.min(220, els.input.scrollHeight) + "px";
}
function openDialogSafe(dlg) {
  if (!dlg) return;
  if (typeof dlg.showModal === "function") {
    try { dlg.showModal(); return; } catch {}
  }
  dlg.setAttribute("open", "");
}

/* LocalStorage helpers */
function lsGet(key, fallback = null) {
  try { const raw = localStorage.getItem(key); return raw == null ? fallback : JSON.parse(raw); }
  catch { return fallback; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}

/* ============ GOOGLE SIGN-IN (ID TOKEN) ============ */
window.handleCredentialResponse = async function (response) {
  try {
    const idToken = response.credential;
    const res = await fetch(`${CONFIG.API_BASE}/api/signin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: idToken }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Invalid ID token");

    const email = data.email || "";
    localStorage.setItem(CONFIG.KEYS.USER_EMAIL, email);
    showSignedIn(email);
  } catch (err) {
    console.error("Google sign-in failed:", err);
    alert("Google sign-in failed. Check console for details.");
  }
};

function showSignedIn(email) {
  if (els.profileSubtitle) els.profileSubtitle.textContent = "Signed-In";
  if (els.profileHandle) els.profileHandle.textContent = (email.split("@")[0] || "You");

  // Replace Google mount with an email pill
  if (els.googleBtnMount) {
    els.googleBtnMount.innerHTML = `
      <div class="signed-in-email">
        Signed in as ${escapeHTML(email)}
      </div>
    `;
  }
}
function showSignedOut() {
  if (els.profileSubtitle) els.profileSubtitle.textContent = "Signed-Out";
  if (els.googleBtnMount) els.googleBtnMount.innerHTML = "";
}

/** Render the Google Sign-In button, unless already signed in. */
function initGoogleButton() {
  if (!window.google?.accounts?.id) return setTimeout(initGoogleButton, 200);

  // If browsing on 127.0.0.1 you must authorize that origin in Google Console
  if (location.hostname === "127.0.0.1") {
    console.warn("⚠️ If sign-in fails, add http://127.0.0.1:5500 to OAuth origins or use http://localhost:5500.");
  }

  const email = localStorage.getItem(CONFIG.KEYS.USER_EMAIL);
  if (email) {
    showSignedIn(email);
    return;
  }

  google.accounts.id.initialize({
    client_id: CONFIG.GOOGLE_CLIENT_ID,
    callback: window.handleCredentialResponse,
    ux_mode: "popup",
    auto_select: false,
  });

  if (els.googleBtnMount) {
    google.accounts.id.renderButton(els.googleBtnMount, {
      theme: "outline",
      size: "large",
      text: "signin_with",
      shape: "rectangular",
      logo_alignment: "left",
    });
  }
  showSignedOut();
}

/* ============ GOOGLE OAUTH (ACCESS TOKEN for Gmail/Calendar) ============ */
let _tokenClient = null;
let _currentScopeRequested = "";

function initGoogleOAuth() {
  if (!window.google?.accounts?.oauth2) return setTimeout(initGoogleOAuth, 200);

  _tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: OAUTH.CLIENT_ID,
    scope: OAUTH.SCOPE_BOTH,
    callback: (tok) => {
      if (tok && tok.access_token) {
        localStorage.setItem(OAUTH.LS_TOKEN, tok.access_token);
        localStorage.setItem(OAUTH.LS_SCOPE, _currentScopeRequested || "");
        console.log("✅ OAuth token acquired for scope:", _currentScopeRequested);
        // Mark buttons as connected (optional, CSS .is-connected)
        reflectConnectedScopes();
      }
    },
  });
}

function requestAccessToken(scope, promptConsent = true) {
  if (!_tokenClient) {
    console.warn("OAuth token client not ready yet.");
    return;
  }
  _currentScopeRequested = scope;
  _tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: OAUTH.CLIENT_ID,
    scope,
    callback: _tokenClient.callback,
  });
  _tokenClient.requestAccessToken({ prompt: promptConsent ? "consent" : "" });
}

function getAccessToken() {
  return localStorage.getItem(OAUTH.LS_TOKEN) || "";
}
function tokenHasScope(requiredScope) {
  const granted = (localStorage.getItem(OAUTH.LS_SCOPE) || "").split(/\s+/).filter(Boolean);
  return granted.includes(requiredScope);
}
function reflectConnectedScopes() {
  // Adds .is-connected class and updates text when that scope was granted
  const ls = (localStorage.getItem(OAUTH.LS_SCOPE) || "").split(/\s+/);
  if (els.btnConnectMail) {
    const connected = ls.includes(OAUTH.SCOPE_MAIL);
    els.btnConnectMail.classList.toggle("is-connected", connected);
    els.btnConnectMail.textContent = connected ? "\u2713 Gmail Connected" : "Connect Gmail";
  }
  if (els.btnConnectCal) {
    const connected = ls.includes(OAUTH.SCOPE_CAL);
    els.btnConnectCal.classList.toggle("is-connected", connected);
    els.btnConnectCal.textContent = connected ? "\u2713 Calendar Connected" : "Connect Calendar";
  }
  if (els.btnConnectBoth) {
    const connected = ls.includes("https://www.googleapis.com/auth/gmail.readonly") &&
      ls.includes("https://www.googleapis.com/auth/calendar.readonly");
    els.btnConnectBoth.classList.toggle("is-connected", connected);
    els.btnConnectBoth.textContent = connected ? "\u2713 All Connected" : "Connect Google";
  }
}

/* ============ THREADS (sidebar) ============ */
(function initThreads() {
  const THREADS_KEY = CONFIG.KEYS.THREADS;
  const ACTIVE_KEY  = CONFIG.KEYS.THREAD_ACTIVE;
  const MSG_PREFIX  = "hv_thread_";

  const msgKey = (id) => `${MSG_PREFIX}${id}`;
  const nowISO = () => new Date().toISOString();

  function timeSince(iso) {
    if (!iso) return "";
    const s = Math.floor((Date.now() - new Date(iso).getTime())/1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s/60); if (m < 60) return `${m}m ago`;
    const h = Math.floor(m/60); if (h < 24) return `${h}h ago`;
    const d = Math.floor(h/24); return `${d}d ago`;
  }
  function loadThreads(){ return lsGet(THREADS_KEY, []); }
  function saveThreads(list){ lsSet(THREADS_KEY, list); }
  function loadActive(){ return lsGet(ACTIVE_KEY, null); }
  function saveActive(id){ lsSet(ACTIVE_KEY, id); }
  function sortThreads(list){
    const pinned = list.filter(t=>t.pinned).sort((a,b)=> b.updatedAt.localeCompare(a.updatedAt));
    const rest   = list.filter(t=>!t.pinned).sort((a,b)=> b.updatedAt.localeCompare(a.updatedAt));
    return [...pinned, ...rest];
  }
  const autoTitle = (s) => (s||"").replace(/\s+/g," ").trim().slice(0,48) || "Untitled";

  function render(){
    if (!els.threadsList) return;
    let list = sortThreads(loadThreads());
    const active = loadActive();
    const q = (els.threadSearch?.value || "").toLowerCase().trim();
    if (q){
      list = list.filter(t =>
        (t.title||"").toLowerCase().includes(q) ||
        (t.snippet||"").toLowerCase().includes(q)
      );
    }
    els.threadsList.innerHTML = "";
    if (!list.length){ if (els.threadsEmpty) els.threadsEmpty.style.display = "block"; return; }
    if (els.threadsEmpty) els.threadsEmpty.style.display = "none";

    for (const t of list){
      const node = els.tplThreadItem.content.firstElementChild.cloneNode(true);
      node.dataset.id = t.id;
      node.querySelector(".thread-title").textContent = t.title || "Untitled";
      node.querySelector(".thread-snippet").textContent = t.snippet || " ";
      const timeEl = node.querySelector(".thread-time");
      timeEl.textContent = timeSince(t.updatedAt);
      timeEl.setAttribute("datetime", t.updatedAt);
      if (t.id === active) node.setAttribute("data-selected", "true");

      node.querySelector(".thread-main")?.addEventListener("click", () => openThread(t.id));
      node.querySelector(".thread-pin")?.addEventListener("click", (e)=>{ e.stopPropagation(); togglePin(t.id); });
      node.querySelector(".thread-rename")?.addEventListener("click", (e)=>{ e.stopPropagation(); openRename(t.id, t.title); });
      node.querySelector(".thread-delete")?.addEventListener("click", (e)=>{ e.stopPropagation(); if (confirm("Delete this chat?")) deleteThread(t.id); });

      els.threadsList.appendChild(node);
    }
  }

  function createThread(){
    const id = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `t_${Date.now()}`;
    const t = { id, title:"New chat", snippet:"", updatedAt:nowISO(), pinned:false };
    const list = loadThreads(); list.push(t); saveThreads(list);
    saveActive(id); render(); openThread(id); return id;
  }
  function deleteThread(id){
    const list = loadThreads().filter(t=>t.id!==id);
    saveThreads(list);
    if (loadActive() === id) saveActive(list[0]?.id || null);
    try { localStorage.removeItem(msgKey(id)); } catch {}
    render();
    if (!loadActive() && els.chatBox){ els.chatBox.innerHTML = ""; }
  }
  function renameThread(id, title){
    const list = loadThreads();
    const t = list.find(x=>x.id===id); if (!t) return;
    t.title = (title||"Untitled").trim() || "Untitled";
    t.updatedAt = nowISO();
    saveThreads(list); render();
  }
  function togglePin(id){
    const list = loadThreads();
    const t = list.find(x=>x.id===id); if (!t) return;
    t.pinned = !t.pinned; t.updatedAt = nowISO();
    saveThreads(list); render();
  }
  function touchThread(id, latestText){
    const list = loadThreads();
    const t = list.find(x=>x.id===id); if (!t) return;
    if (latestText) t.snippet = latestText;
    if (t.title === "New chat" && latestText) t.title = autoTitle(latestText);
    t.updatedAt = nowISO();
    saveThreads(list); render();
  }
  function openThread(id){
    saveActive(id); render();
    if (!els.chatBox) return;
    const messages = lsGet(msgKey(id), []);
    els.chatBox.innerHTML = "";
    messages.forEach(m => {
      const li = document.createElement("li");
      li.className = `msg ${m.role==='assistant'?'bot':'user'}`;
      li.dataset.role = m.role;
      li.innerHTML = `<div class="avatar" aria-hidden="true">${m.role==='assistant'?'🤖':'🧑'}</div><div class="bubble"><div class="content"></div></div>`;
      li.querySelector(".content").innerHTML = m.role === "assistant" ? renderMarkdownToHTML(m.text || "") : escapeHTML(m.text || "").replace(/\n/g, "<br/>");
      els.chatBox.appendChild(li);
    });
    autoScrollChat();
  }
  function openRename(id, currentTitle){
    if (!els.renameModal || !els.renameForm || !els.renameInput) return;
    els.renameInput.value = currentTitle || "";
    openDialogSafe(els.renameModal);
    const onSubmit = (e)=>{
      e.preventDefault();
      if (e.submitter?.value === "cancel"){ els.renameModal.close(); els.renameForm.removeEventListener("submit", onSubmit); return; }
      renameThread(id, els.renameInput.value.trim());
      els.renameModal.close(); els.renameForm.removeEventListener("submit", onSubmit);
    };
    els.renameForm.addEventListener("submit", onSubmit, { once: true });
  }

  // Expose
  window.HVThreads = {
    create: createThread,
    open: openThread,
    active: () => lsGet(ACTIVE_KEY, null),
    list:  () => sortThreads(loadThreads()),
    rename: renameThread,
    delete: deleteThread,
    pin: togglePin,
    addMessage: (id, role, text) => {
      const key = msgKey(id);
      const list = lsGet(key, []);
      list.push({ role, text: (text||"").toString(), ts: nowISO() });
      lsSet(key, list);
      if (role === "user" || role === "assistant") touchThread(id, text);
    },
  };

  // Bind
  els.newChatBtn?.addEventListener("click", createThread);
  els.threadSearch?.addEventListener("input", render);

  render();
  const act = lsGet(ACTIVE_KEY, null);
  if (act) openThread(act);
})();

/* ============ MESSAGES ============ */
function addUserMessage(text) {
  const safe = escapeHTML(text).replace(/\n/g, "<br/>");
  const node = renderFromTemplate(els.tplUser, safe);
  els.chatBox.appendChild(node);
  autoScrollChat();
  const id = window.HVThreads?.active() || window.HVThreads?.create();
  if (id) window.HVThreads.addMessage(id, "user", text);
}
function addAssistantMessage(text) {
  const node = renderFromTemplate(els.tplAssistant, renderMarkdownToHTML(text));
  els.chatBox.appendChild(node);
  autoScrollChat();
  const id = window.HVThreads?.active() || window.HVThreads?.create();
  if (id) window.HVThreads.addMessage(id, "assistant", text);
}

/* ============ TYPING ============ */
let typingNode = null;
function showTyping() {
  if (typingNode) return; typingNode = renderFromTemplate(els.tplTyping);
  els.chatBox.appendChild(typingNode); autoScrollChat();
}
function hideTyping() {
  if (!typingNode) return; typingNode.remove(); typingNode = null;
}

/* ============ API ============ */
async function httpPostJSON(path, body) {
  const url = `${CONFIG.API_BASE}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CONFIG.TIMEOUT_MS);

  const userEmail = localStorage.getItem(CONFIG.KEYS.USER_EMAIL) || "";
  const accessToken = getAccessToken();

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(userEmail ? { "X-User-Email": userEmail } : {}),
        ...(accessToken ? { "X-Google-Access-Token": accessToken } : {}),
      },
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const j = await res.json(); if (j?.detail) msg = j.detail; } catch {}
      throw new Error(msg);
    }
    return await res.json();
  } catch (e) {
    clearTimeout(timeout); throw e;
  }
}

/* ============ CHAT FLOW ============ */
async function sendQuery(raw) {
  const query = sanitize(raw);
  if (!query) return;
  addUserMessage(query);
  els.input.value = ""; autoResize(); showTyping();

  try {
    const data = await httpPostJSON("/api/echo", { prompt: query });
    const text = data?.response ?? "❌ No response.";
    hideTyping(); addAssistantMessage(text);
  } catch (err) {
    hideTyping();
    const msg = err?.message || String(err);
    if (msg.includes("Missing Gmail access token")) {
      addAssistantMessage("🔐 To check your inbox, please click 'Connect Google' and grant Gmail access.");
    } else {
      addAssistantMessage(`⚠️ Couldn’t reach server: ${escapeHTML(msg)}`);
    }
  }
}

/* ============ WIRING ============ */
window.addEventListener("load", () => {
  // Google Sign-In button
  initGoogleButton();

  // OAuth client + connect buttons
  initGoogleOAuth();
  els.btnConnectMail?.addEventListener("click", () => requestAccessToken(OAUTH.SCOPE_MAIL, true));
  els.btnConnectCal?.addEventListener("click", () => requestAccessToken(OAUTH.SCOPE_CAL, true));
  els.btnConnectBoth?.addEventListener("click", () => requestAccessToken(OAUTH.SCOPE_BOTH, true));
  reflectConnectedScopes();

  // Settings
  els.openSettings?.addEventListener("click", (e) => { e.stopPropagation(); openDialogSafe(els.settingsModal); });

  // Input UX
  els.input?.addEventListener("input", autoResize);
  els.input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuery(els.input.value); }
  });
  els.sendBtn?.addEventListener("click", () => sendQuery(els.input.value));

  els.input?.focus?.();
  autoResize();
});

// Optional for console testing
window.HushhVoice = { sendQuery };

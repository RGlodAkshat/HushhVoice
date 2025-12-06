/*
============================================================
 HushhVoice — script.js (Clean, organized, with calendar+email intents)
 With short-term memory windows for all endpoints + Speak/Copy actions
============================================================
*/

/* =============================
   0) DOM HOOKS
   ============================= */
const els = {
  // Core
  app: document.getElementById("app"),
  chatBox: document.getElementById("chat-box"),
  input: document.getElementById("user-input"),
  sendBtn: document.getElementById("send-btn"),
  micBtn: document.getElementById("mic-btn"),
  stopBtn: document.getElementById("stop-btn"),

  // Auth
  googleLogin: document.getElementById("google-login"),
  userInfo: document.getElementById("user-info"),
  userEmail: document.getElementById("user-email"),
  logoutBtn: document.getElementById("logout-btn"),

  // Templates
  tplTyping: document.getElementById("tpl-typing"),
  tplAssistant: document.getElementById("tpl-assistant"),
  tplUser: document.getElementById("tpl-user"),

  // System
  toasts: document.getElementById("toasts"),
  micHelp: document.getElementById("mic-help"),
  voiceSelect: document.getElementById("voice-select"),

  // Sidebar / Nav
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  profileHandle: document.getElementById("profile-handle"),

  // Bio (modal + preview)
  bioModal: document.getElementById("bio-modal"),
  openBioBtn: document.getElementById("open-bio-btn"),
  bioForm: document.getElementById("bio-form"),
  bioText: document.getElementById("bio-text"),
  bioPreview: document.getElementById("bio-preview"),
  bioPreviewText: document.getElementById("bio-preview-text"),
  editBioInline: document.getElementById("edit-bio-inline"),

  // RAG Memory (placeholders in UI)
  memoryForm: document.getElementById("memory-form"),
  memoryInput: document.getElementById("memory-input"),
  memoryLog: document.getElementById("memory-log"),
  memoryWrap: document.querySelector(".memory-log-wrap"),
  memoryClearBtn: document.getElementById("memory-clear-btn"),
  tplMemoryItem: document.getElementById("tpl-memory-item"),

  // Facts
  addFactBtn: document.getElementById("add-fact-btn"),
  factList: document.getElementById("fact-list"),

  // Vision / Attachments
  attachmentBar: document.getElementById("attachment-bar"),
  cameraBtn: document.getElementById("camera-btn"),
  galleryBtn: document.getElementById("gallery-btn"),
  imageInput: document.getElementById("image-input"),
  imageInputGallery: document.getElementById("image-input-gallery"),
};

/* =============================
   1) CONFIG & STORAGE KEYS
   ============================= */
const CONFIG = {
  BASE_URL: "https://hushhvoice-1.onrender.com",
  // BASE_URL: "https://5334cbb4e81e.ngrok-free.app", // <-- your ngrok URL here
  CLIENT_ID: "106283179463-48aftf364n2th97mone9s8mocicujt6c.apps.googleusercontent.com",

  GMAIL_SCOPES: [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
  ].join(" "),

  CALENDAR_SCOPES: [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
  ].join(" "),

  USE_STREAMING: false,
  TIMEOUT_MS: 25_000,
  RETRIES: 2,
  SPEECH_RATE: 1.0,
  DEFAULT_EMAIL_FETCH: 20,

  // Vision
  MAX_IMAGE_MB: 6,
  VISION_DEFAULT_PROMPT:
    "What is this? Identify the product (brand/model) and give key facts, price ballpark, and concise nutrition if food.",

  // Short-term memory window
  MEMORY_WINDOW_MESSAGES: 20, // last N messages to include each call

  // TTS
  AUTO_TTS: false, // Disable automatic text-to-speech after responses
};

const KEYS = {
  GOOGLE_ID_TOKEN: "google_token",
  USER_EMAIL: "user_email",
  USER_NAME: "user_name",
  BIO: "hushh_bio",
  MEMORIES: "hushh_memories",
  FACTS: "hushh_facts",
  ONBOARDED: "hv_onboarded_v1",           // <— add this
};

/* =============================
   2) STATE & UTILITIES
   ============================= */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
const sanitize = (s) => (s ?? "").toString().trim();

const safeJSON = async (res) => {
  try { return await res.json(); } catch { return null; }
};

function toast(msg, type = "info", timeout = 3500) {
  if (!els.toasts) return;
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  els.toasts.appendChild(t);
  setTimeout(() => t.remove(), timeout);
}

function escapeHTML(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}

function renderMarkdownToHTML(md) {
  const raw = marked.parse(md || "");
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
}

async function typeMarkdown(el, fullText, speed = 18) {
  el.innerHTML = "";
  let i = 0;
  const delay = Math.max(8, Math.min(speed, 30));
  while (i <= fullText.length) {
    const slice = fullText.slice(0, i);
    el.innerHTML = renderMarkdownToHTML(slice);
    if (typeof autoScrollChat === "function") autoScrollChat();
    i += 2;
    await new Promise((r) => setTimeout(r, delay));
  }
}

function emailToHandle(email) {
  if (!email || !email.includes("@")) return "you";
  return email.split("@")[0] || "you";
}

/* =============================
   3) LOCAL STORAGE HELPERS
   ============================= */
function lsGet(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { }
}

/* =============================
   4) GOOGLE AUTH (ID TOKEN) + PROFILE
   ============================= */
function setAuthUI(email) {
  console.log("Setting auth UI with email:", email);
  const loggedIn = !!email;
  if (els.googleLogin) els.googleLogin.style.display = loggedIn ? "none" : "block";
  if (els.userInfo) els.userInfo.style.display = loggedIn ? "inline-flex" : "none";
  if (els.userEmail) els.userEmail.textContent = email || "";
  if (els.profileHandle) els.profileHandle.textContent = emailToHandle(email);
}

function decodeJwtPayload(jwt) {
  try {
    const payload = jwt.split(".")[1];
    const pad = "=".repeat((4 - (payload.length % 4)) % 4);
    const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/") + pad);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

function handleGoogleLogin(resp) {
  const jwt = resp?.credential;
  const payload = jwt ? decodeJwtPayload(jwt) : null;
  const email = payload?.email;
  const name = payload?.name || "";
  if (!jwt || !email) {
    toast("Google sign-in failed. Try again.", "error");
    return;
  }
  localStorage.setItem(KEYS.GOOGLE_ID_TOKEN, jwt);
  localStorage.setItem(KEYS.USER_EMAIL, email);
  if (name) localStorage.setItem(KEYS.USER_NAME, JSON.stringify(name));
  setAuthUI(email);
  toast(`Signed in as ${email}`);
}

function checkLoginStatus() {
  const token = localStorage.getItem(KEYS.GOOGLE_ID_TOKEN);
  const email = localStorage.getItem(KEYS.USER_EMAIL);

  if (token && email) {
    console.log("User was already signed in.");
    setAuthUI(email); // Update the UI
    return true;      // <-- Return true because the user is logged in
  } else {
    console.log("No active session found.");
    return false;     // <-- Return false
  }
}

function handleLogout() {
  // Clear the user's token and details from storage
  localStorage.removeItem(KEYS.GOOGLE_ID_TOKEN);
  localStorage.removeItem(KEYS.USER_EMAIL);
  localStorage.removeItem(KEYS.USER_NAME);

  // Disable Google's automatic sign-in for the next visit
  if (window.google?.accounts?.id) {
    google.accounts.id.disableAutoSelect();
  }
  
  // Reset the UI to the logged-out state
  setAuthUI(null);

  toast("Signed out successfully.");

  initGoogle(); // Reinitialize Google Sign-In
}

function initGoogle(retries = 5, delay = 300) {
  // Check if Google's library is ready
  if (window.google?.accounts?.id) {
    console.log("Google GSI script loaded, initializing...");
    google.accounts.id.initialize({
      client_id: CONFIG.CLIENT_ID,
      callback: handleGoogleLogin,
      auto_select: false
    });
    google.accounts.id.renderButton(
      els.googleLogin,
      { theme: "outline", size: "large", width: "280" }
    );
  } else if (retries > 0) {
    // If not ready, wait and try again
    console.warn(`Google GSI script not loaded yet, retrying... (${retries} attempts left)`);
    setTimeout(() => {
      initGoogle(retries - 1, delay);
    }, delay);
  } else {
    // If all retries fail, show an error to the user
    console.error("Could not initialize Google Sign-In after multiple attempts.");
    if (els.googleLogin) {
      els.googleLogin.innerHTML = "Sign-In button failed to load. Please refresh the page.";
    }
  }
}

/* =============================
   4a) GENERAL OAUTH TOKEN CACHE (Calendar, Gmail, etc.)
   ============================= */
const oauthCache = Object.create(null); // { scopes: { access_token, expires_at } }

async function ensureAccessToken(scopes, { forceInteractive = false } = {}) {
  const key = String(scopes || "").trim();
  if (!key) return null;

  const cached = oauthCache[key];
  const now = Date.now();
  if (cached?.access_token && now < cached.expires_at) return cached.access_token;

  if (!window.google?.accounts?.oauth2) {
    toast("Google OAuth unavailable.", "error");
    return null;
  }

  function requestToken({ interactive }) {
    return new Promise((resolve) => {
      const client = google.accounts.oauth2.initTokenClient({
        client_id: CONFIG.CLIENT_ID,
        scope: key,
        prompt: interactive ? "consent" : "",
        callback: (res) => {
          if (res && res.access_token) {
            const ms = (res.expires_in ? Number(res.expires_in) : 3600) * 1000;
            oauthCache[key] = { access_token: res.access_token, expires_at: Date.now() + ms - 60 * 1000 };
            resolve(res.access_token);
          } else {
            resolve(null);
          }
        },
      });
      try { client.requestAccessToken({ prompt: interactive ? "consent" : "" }); } catch { resolve(null); }
    });
  }

  if (!forceInteractive) {
    const silent = await requestToken({ interactive: false });
    if (silent) return silent;
    await new Promise((r) => setTimeout(r, 350));
    const retrySilent = await requestToken({ interactive: false });
    if (retrySilent) return retrySilent;
  }

  return await requestToken({ interactive: true });
}

/* =============================
   5) NETWORK HELPERS (fetch + retry)
   ============================= */
class AbortControllerComposite {
  constructor(a, b) {
    this.controller = new AbortController();
    const abort = () => this.controller.abort();
    a?.addEventListener?.("abort", abort, { once: true });
    b?.addEventListener?.("abort", abort, { once: true });
  }
  get signal() { return this.controller.signal; }
}

async function httpPostJSON(path, body, { signal, gmailAccessToken = null } = {}) {
  const url = `${CONFIG.BASE_URL}${path}`;
  const idToken = localStorage.getItem(KEYS.GOOGLE_ID_TOKEN);
  const email = lsGet(KEYS.USER_EMAIL);
  const name = lsGet(KEYS.USER_NAME);

  const headers = { "Content-Type": "application/json" };
  if (idToken) headers.Authorization = `Bearer ${idToken}`;
  if (email) headers["X-User-Email"] = email;
  if (name) headers["X-User-Name"] = name;
  if (gmailAccessToken) headers["X-Google-Access-Token"] = gmailAccessToken;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CONFIG.TIMEOUT_MS);
  const finalSignal = signal ? new AbortControllerComposite(signal, controller).signal : controller.signal;

  try {
    const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body || {}), signal: finalSignal });
    if (!res.ok) {
      const errData = await safeJSON(res);
      throw new Error(errData?.error?.message || `HTTP ${res.status}`);
    }
    return await safeJSON(res);
  } finally { clearTimeout(timeout); }
}

async function postWithRetry(path, body, opts = {}) {
  let attempt = 0; let delay = 600;
  while (true) {
    try { return await httpPostJSON(path, body, opts); }
    catch (e) { if (attempt >= CONFIG.RETRIES) throw e; await sleep(delay); delay = clamp(delay * 2, 600, 4000); attempt++; }
  }
}

/* =============================
   6) UI RENDERING HELPERS
   ============================= */
function renderFromTemplate(tpl, html) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  if (html != null) {
    const content = node.querySelector(".content");
    if (content) content.innerHTML = html;
  }
  return node;
}
function autoScrollChat() { els.chatBox.scrollTop = els.chatBox.scrollHeight; }
function addUserMessage(text) {
  const safe = escapeHTML(text).replace(/\n/g, "<br/>");
  const node = renderFromTemplate(els.tplUser, safe);
  els.chatBox.appendChild(node); autoScrollChat();
}
function addAssistantMessage(text, { animate = true } = {}) {
  const node = renderFromTemplate(els.tplAssistant, "");
  const content = node.querySelector(".content");
  els.chatBox.appendChild(node);
  autoScrollChat();

  if (animate) {
    typeMarkdown(content, text);
  } else {
    content.innerHTML = renderMarkdownToHTML(text);
  }

  const speakBtn = node.querySelector(".speak-btn");
  const getPlainText = () => (content?.innerText || "").trim();

  if (speakBtn) {
    speakBtn.addEventListener("click", async (e) => {
      e.preventDefault();

      // If already speaking…
      if (ttsState.playing) {
        // If this same message initiated speaking: treat click as STOP
        if (ttsState.sourceBtn === speakBtn) {
          stopSpeaking();
        } else {
          // Another message tried to speak during lock — ignore & hint
          toast("Already speaking. Tap Stop first.", "info");
        }
        return;
      }

      // Not speaking yet -> start speaking this message
      const textToSpeak = getPlainText();
      if (!textToSpeak) {
        toast("Nothing to speak.", "info");
        return;
      }

      // Lock + UI toggle to Stop
      ttsState.playing = true;
      ttsState.sourceBtn = speakBtn;
      ttsState.sourceNode = node;

      speakBtn.classList.add("is-speaking");
      speakBtn.textContent = "⏹ Stop";
      speakBtn.setAttribute("aria-label", "Stop speaking");
      speakBtn.title = "Stop speaking";

      try {
        await speak(textToSpeak);
      } catch (err) {
        console.error(err);
        toast("Could not play TTS.", "error");
        resetTTSStateUI();
      }
    });
  }
}

let typingNode = null;
function showTyping() { if (typingNode) return; typingNode = renderFromTemplate(els.tplTyping); els.chatBox.appendChild(typingNode); autoScrollChat(); }
function hideTyping() { if (!typingNode) return; typingNode.remove(); typingNode = null; }

/* =============================
   7) TTS (speech out)
   ============================= */

// --- TTS global state (single-instance lock) ---
let currentAudio = null;
let ttsState = {
  playing: false,
  sourceBtn: null,   // the button that triggered TTS
  sourceNode: null,  // the message node (li.msg.bot)
};


async function speak(text) {
  if (!text) return;

  // Don't create overlaps; this function just creates/plays audio. Locking is handled in the button handler.
  const voice = els.voiceSelect ? els.voiceSelect.value : "alloy";
  if (currentAudio && !currentAudio.paused) {
    // in case some stray instance exists, stop before starting fresh
    try { currentAudio.pause(); currentAudio.currentTime = 0; } catch {}
    currentAudio = null;
  }

  const res = await fetch(`${CONFIG.BASE_URL}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice })
  });

  if (!res.ok) throw new Error(`TTS request failed: ${res.status}`);
  const audioBlob = await res.blob();
  const audioUrl = URL.createObjectURL(audioBlob);
  currentAudio = new Audio(audioUrl);

  document.body.classList.add("is-speaking");
  currentAudio.onended = () => {
    document.body.classList.remove("is-speaking");
    resetTTSStateUI();
  };
  currentAudio.onpause = () => {
    // when paused programmatically, treat like stop
    document.body.classList.remove("is-speaking");
    resetTTSStateUI();
  };

  await currentAudio.play();
}

function stopSpeaking() {
  if (currentAudio) {
    try { currentAudio.pause(); currentAudio.currentTime = 0; } catch {}
    currentAudio = null;
  }
  document.body.classList.remove("is-speaking");
  resetTTSStateUI();
}

// Reset lock + return any Speak button back to normal
function resetTTSStateUI() {
  if (ttsState.sourceBtn) {
    ttsState.sourceBtn.classList.remove("is-speaking");
    ttsState.sourceBtn.textContent = "🔈 Speak";
    ttsState.sourceBtn.setAttribute("aria-label", "Speak this response");
    ttsState.sourceBtn.title = "Speak this response";
  }
  ttsState.playing = false;
  ttsState.sourceBtn = null;
  ttsState.sourceNode = null;
}


function maybeSpeak(text) { if (CONFIG.AUTO_TTS) speak(text); }


/* =============================
   8) MIC (press & hold)
   ============================= */
let recognition = null; let micSupported = false; let recording = false;
(function initMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    micSupported = false;
    els.micBtn?.addEventListener("click", () => toast("Mic not supported in this browser.", "error"));
    els.micBtn?.setAttribute("disabled", "true");
    return;
  }
  micSupported = true; recognition = new SR();
  recognition.lang = "en-US"; recognition.continuous = false; recognition.interimResults = false; recognition.maxAlternatives = 1;
  recognition.onresult = (e) => { const transcript = e.results?.[0]?.[0]?.transcript || ""; if (transcript.trim()) sendQuery(transcript.trim()); };
  recognition.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") { try { els.micHelp?.showModal?.(); } catch { } }
    else { toast(`Mic error: ${e.error || "unknown"}`, "error"); }
    stopMicUI();
  };
  recognition.onend = () => stopMicUI();
  els.micBtn?.addEventListener("mousedown", startMicFlow);
  document.addEventListener("mouseup", () => recording && stopMicFlow());
  els.micBtn?.addEventListener("touchstart", (e) => { e.preventDefault(); startMicFlow(); }, { passive: false });
  document.addEventListener("touchend", () => recording && stopMicFlow());
})();
async function startMicFlow() {
  if (!micSupported || !recognition || recording) return;
  try { if (navigator.mediaDevices?.getUserMedia) { await navigator.mediaDevices.getUserMedia({ audio: true }); } } catch {}
  startMicUI();
  try { recognition.start(); } catch { stopMicUI(); }
}
function stopMicFlow() { try { recognition?.stop(); } catch {} stopMicUI(); }
function startMicUI() { recording = true; els.micBtn?.classList.add("recording"); els.micBtn?.setAttribute("aria-pressed", "true"); }
function stopMicUI() { recording = false; els.micBtn?.classList.remove("recording"); els.micBtn?.setAttribute("aria-pressed", "false"); }

/* =============================
   9) SIDEBAR / NAV
   ============================= */
let lockedScrollY = 0;
function openSidebar() {
  if (!els.sidebar) return;
  lockedScrollY = window.scrollY || window.pageYOffset || 0;
  document.body.style.top = `-${lockedScrollY}px`;
  document.body.classList.add("nav-open");
  els.sidebar.classList.add("open");
  els.sidebarToggle?.setAttribute("aria-expanded", "true");
  els.sidebar?.setAttribute("aria-hidden", "false");
}
function closeSidebar() {
  if (!els.sidebar) return;
  els.sidebar.classList.remove("open");
  els.sidebarToggle?.setAttribute("aria-expanded", "false");
  els.sidebar?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("nav-open");
  const y = Math.abs(parseInt(document.body.style.top || "0", 10)) || 0;
  document.body.style.top = "";
  window.scrollTo(0, y);
}
function toggleSidebar() { if (!els.sidebar) return; const isOpen = els.sidebar.classList.contains("open"); isOpen ? closeSidebar() : openSidebar(); }
els.sidebarToggle?.addEventListener("click", (e) => { e.stopPropagation(); toggleSidebar(); });
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && els.sidebar?.classList.contains("open")) closeSidebar(); });
els.app?.addEventListener("click", () => { if (els.sidebar?.classList.contains("open")) closeSidebar(); });
els.sidebar?.addEventListener("click", (e) => e.stopPropagation());
window.addEventListener("resize", () => { if (window.innerWidth >= 1100 && document.body.classList.contains("nav-open")) { closeSidebar(); } });

/* =============================
   10) BIO (modal + preview)
   ============================= */
function loadBio() { return lsGet(KEYS.BIO, ""); }
function saveBio(text) { lsSet(KEYS.BIO, text || ""); }
function setBioPreview(text) {
  const t = sanitize(text);
  if (!els.bioPreviewText) return;        // 👈 add this guard
  els.bioPreviewText.textContent = t ? t : "Add a short bio to personalize your assistant.";
}

function openBioModal() { if (!els.bioModal) return; els.bioText.value = loadBio(); try { els.bioModal.showModal(); } catch {} }
function closeBioModal() { try { els.bioModal.close(); } catch {} }
els.openBioBtn?.addEventListener("click", openBioModal);
els.editBioInline?.addEventListener("click", openBioModal);
els.bioForm?.addEventListener("submit", (e) => {
  e.preventDefault();
  const submitter = e.submitter?.value || e.submitter?.textContent?.toLowerCase();
  if (submitter === "cancel") { closeBioModal(); return; }
  const text = sanitize(els.bioText.value);
  saveBio(text); setBioPreview(text); closeBioModal(); toast("Bio saved.");
});

/* =============================
   11) RAG Memory (placeholders)
   ============================= */
// Keeping hooks intact for your memory UI elsewhere.



function getIntroMessage() {
  return [
    "# 👋 Welcome to HushhVoice",
    "Your private, consent-first copilot. Here’s what I can do:",
    "",
    "### What you can ask",
    "• **General** — “What is attention in Neural Networks?”",
    "• **Email** — “Summarize my last 5 important emails.”",
    "• **Calendar** — “Summarize all important calender events for tomorrow.”",
    "• **Schedule** — “Book 30m with Sam next Tue at 2pm; add Zoom.”",
    "• **Reply** — “Send an email to Manish.sainani@gmail.com, reminding him of an upcoming meeting at 10AM today.”",
    "• **Memory** — Tell me preferences (e.g., _I prefer 30-min meetings after 2pm_).",
    "",
    "### Make it yours",
    "1. **Sign in with Google** (top right) to enable **Mail** and **Calendar**.",
    "2. Open **Settings → About me** to set a short bio.",
    "3. Use **RAG Memory** to save small facts/preferences.",
    "",
    "### Privacy",
    "HushhVoice is consent-first: it only uses the sources you enable and only for the current task.",
    "",
    "### Quick starters",
    "• _“What did I miss in my inbox today?”_",
    "• _“Create a calendar event: Hushh sync, Wed 3–3:30pm, add Zoom.”_",
    "• _“Scan this image and extract key details.”_",
    "",
    "_Tip: Press **Enter** to send, **Shift+Enter** for a new line._"
  ].join("\n");
}





/* =============================
   12) FACTS (placeholder)
   ============================= */
els.addFactBtn?.addEventListener("click", () => {
  const fact = prompt("Add a quick fact:");
  if (!fact) return;
  const li = document.createElement("li");
  li.textContent = fact.trim();
  els.factList?.appendChild(li);
});

/* =============================
   13) CALENDAR HELPERS (time utils)
   ============================= */
function toLocalISO(year, month, day, hour, minute) {
  const d = new Date(year, month - 1, day, hour, minute, 0, 0);
  const yyyy = d.getFullYear(); const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0"); const HH = String(d.getHours()).padStart(2, "0");
  const MM = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${HH}:${MM}`;
}
function addMinutesToLocalISO(isoLocal, mins) {
  const [date, time] = isoLocal.split("T");
  const [Y, M, D] = date.split("-").map(Number);
  const [h, m] = time.split(":").map(Number);
  const d = new Date(Y, M - 1, D, h, m); d.setMinutes(d.getMinutes() + mins);
  const yyyy = d.getFullYear(); const mm = String(d.getMonth() + 1).padStart(2, "0"); const dd = String(d.getDate()).padStart(2, "0");
  const HH = String(d.getHours()).padStart(2, "0"); const MM = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${HH}:${MM}`;
}
function getLocalTimeZone() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } }

/* =============================
   14) INTENT CLASSIFIER
   ============================= */
async function classifyIntent(query) {
  if (!query || !query.trim()) return { intent: "general" };
  try { const { data } = await httpPostJSON("/intent/classify", { query }); return data || { intent: "general" }; }
  catch (e) { console.error("Intent classification failed:", e); return { intent: "general" }; }
}

/* =============================
   18) THREADS + MESSAGES (persistence + memory window)
   ============================= */
const THREAD_KEYS = {
  THREADS: "hushh_threads_v2",            // [{id, title, snippet, updatedAt, pinned:false}]
  ACTIVE: "hushh_active_thread_id_v2",   // string
  MSG_NS: "hushh_msgs_v2:",              // prefix + threadId -> [{id, role, text, ts}]
};

function nowISO() { return new Date().toISOString(); }
function uuid() { return crypto?.randomUUID?.() || (Date.now() + "-" + Math.random().toString(16).slice(2)); }

function loadThreads() { return lsGet(THREAD_KEYS.THREADS, []); }
function saveThreads(list) { lsSet(THREAD_KEYS.THREADS, list || []); }
function getActiveThreadId() { return lsGet(THREAD_KEYS.ACTIVE, null); }
function setActiveThreadId(id) { lsSet(THREAD_KEYS.ACTIVE, id); }

function msgKey(tid) { return THREAD_KEYS.MSG_NS + tid; }
function loadMsgs(tid) { return lsGet(msgKey(tid), []); }
function saveMsgs(tid, msgs) { lsSet(msgKey(tid), msgs || []); }

/** Build a short-term memory window (last N messages) as OpenAI chat messages */
function buildMessageWindow(tid) {
  const msgs = (loadMsgs(tid) || []).slice(-CONFIG.MEMORY_WINDOW_MESSAGES);
  const recent = msgs.map(m => ({
    role: m.role === "assistant" ? "assistant" : "user",
    content: m.text,
  }));
  const system = {
    role: "system",
    content:
      "You are HushhVoice — a private, consent-first AI copilot. " +
      "Use the conversation history to resolve pronouns and context. " +
      "Be concise, helpful, and ask for clarification only when necessary."
  };
  return [system, ...recent];
}

function sortThreads(a, b) {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  return new Date(b.updatedAt) - new Date(a.updatedAt);
}

function generateTitleFromText(text) {
  const t = (text || "").replace(/\s+/g, " ").trim();
  if (!t) return "Untitled";
  const max = 60;
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const stop = Math.max(cut.lastIndexOf("."), cut.lastIndexOf("?"), cut.lastIndexOf("!"), cut.lastIndexOf(" "));
  const head = (stop > 30 ? cut.slice(0, stop) : cut).trim();
  return head + "…";
}

function createThread(initialTitle = "Untitled") {
  const id = uuid();
  const t = { id, title: initialTitle, snippet: "—", updatedAt: nowISO(), pinned: false };
  const list = loadThreads();
  list.unshift(t);
  saveThreads(list);
  setActiveThreadId(id);
  saveMsgs(id, []); // init empty
  return t;
}

function updateThread(id, patch) {
  const list = loadThreads();
  const i = list.findIndex(x => x.id === id);
  if (i === -1) return;
  list[i] = { ...list[i], ...patch, updatedAt: nowISO() };
  list.sort(sortThreads);
  saveThreads(list);
}

function deleteThread(id) {
  const list = loadThreads().filter(x => x.id !== id);
  saveThreads(list);
  localStorage.removeItem(msgKey(id));
  if (getActiveThreadId() === id) setActiveThreadId(list[0]?.id || null);
}

function renderThreads() {
  const listEl = document.getElementById("chat-threads");
  const empty = document.getElementById("chats-empty");
  if (!listEl) return;

  const threads = loadThreads();
  listEl.innerHTML = "";
  if (!threads.length) {
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  const active = getActiveThreadId();
  threads.forEach(t => {
    const tpl = document.getElementById("tpl-chat-thread");
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = t.id;
    node.querySelector(".thread-title").textContent = t.title || "Untitled";
    node.querySelector(".thread-snippet").textContent = t.snippet || "—";
    const timeEl = node.querySelector(".thread-time");
    if (timeEl) { timeEl.dateTime = t.updatedAt; timeEl.textContent = new Date(t.updatedAt).toLocaleString(); }
    if (t.pinned) node.classList.add("pinned");
    if (t.id === active) node.classList.add("active");

    // Open
    node.querySelector(".thread-main")?.addEventListener("click", () => openThread(t.id));

    // Pin
    node.querySelector(".thread-pin")?.addEventListener("click", (e) => {
      e.stopPropagation();
      updateThread(t.id, { pinned: !t.pinned });
      renderThreads();
    });

    // Rename
    node.querySelector(".thread-rename")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const newTitle = prompt("Rename chat:", t.title || "Untitled");
      if (newTitle != null) { updateThread(t.id, { title: sanitize(newTitle) || "Untitled" }); renderThreads(); }
    });

    // Delete
    node.querySelector(".thread-delete")?.addEventListener("click", (e) => {
      e.stopPropagation();
      if (confirm("Delete this chat?")) {
        const wasActive = getActiveThreadId() === t.id;
        deleteThread(t.id);
        renderThreads();
        if (wasActive) {
          const next = getActiveThreadId();
          if (next) openThread(next); else clearChatUI();
        }
      }
    });

    listEl.appendChild(node);
  });
}

function clearChatUI() { els.chatBox.innerHTML = ""; }

function renderMessageBubble(msg) {
  if (msg.role === "user") {
    addUserMessage(msg.text);
  } else {
    addAssistantMessage(msg.text, { animate: false });
  }
}

function openThread(id) {
  setActiveThreadId(id);
  renderThreads();
  clearChatUI();
  const msgs = loadMsgs(id);
  if (!msgs.length) return;
  msgs.forEach(renderMessageBubble);
  autoScrollChat();
}

/* Persist + render helpers */
function appendMessage(role, text) {
  const tid = getActiveThreadId() || createThread().id;
  const msgs = loadMsgs(tid);
  const m = { id: uuid(), role, text: String(text || ""), ts: Date.now() };
  msgs.push(m);
  saveMsgs(tid, msgs);

  // Update thread snippet & (if first message) title
  if (role === "user") {
    if (msgs.length === 1) {
      updateThread(tid, { title: generateTitleFromText(text), snippet: text.slice(0, 140) });
    } else {
      updateThread(tid, { snippet: text.slice(0, 140) });
    }
  } else {
    if (msgs.length === 1) updateThread(tid, { snippet: text.slice(0, 140) });
  }
  renderThreads();

  // Render to chat panel
  renderMessageBubble(m);
}

/* =============================
   15) ACTION HANDLERS (short-term memory integrated)
   ============================= */
// Emails: read inbox Q&A
async function handleReadEmail(question) {
  const accessToken = await ensureAccessToken(CONFIG.GMAIL_SCOPES);
  if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Gmail access to proceed.", { animate: false }); return; }

  const active = getActiveThreadId() || createThread().id;
  const messages = buildMessageWindow(active);

  const data = await httpPostJSON("/mailgpt/answer", {
    query: question,
    max_results: CONFIG.DEFAULT_EMAIL_FETCH,
    messages, // <-- short-term memory
  }, { gmailAccessToken: accessToken });

  const answer = data?.data?.answer || "❌ No answer.";
  hideTyping(); appendMessage("assistant", answer); maybeSpeak(answer);
}

// Emails: send (draft → confirm → send)
async function handleSendEmail(instruction) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.GMAIL_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Gmail access to draft/send email.", { animate: false }); return; }

    const active = getActiveThreadId() || createThread().id;
    const messages = buildMessageWindow(active);

    const draftResp = await httpPostJSON("/mailgpt/reply", {
      instruction,
      max_results: 10,
      send: false,
      messages, // <-- short-term memory
    }, { gmailAccessToken: accessToken });

    const drafted = draftResp?.data?.drafted;
    if (!drafted) { hideTyping(); appendMessage("assistant", "❌ Could not generate a draft from your inbox context."); return; }

    const to = drafted.to_email || "(unknown)"; const subject = drafted.subject || "(no subject)"; const body = drafted.body || "";
    hideTyping();
    const preview = `**Draft preview**\n\n- **To:** ${escapeHTML(to)}\n- **Subject:** ${escapeHTML(subject)}\n\n\`\`\`\n${body}\n\`\`\`\n\nSend this email?`;
    appendMessage("assistant", preview);
    const yes = confirm(`Send this email?\n\nTo: ${to}\nSubject: ${subject}\n\n---\n${body}`);
    if (!yes) { appendMessage("assistant", "👍 Draft not sent. You can edit your instruction and try again."); return; }

    showTyping();
    const sendResp = await httpPostJSON("/mailgpt/reply", {
      instruction,
      max_results: 10,
      send: true,
      messages, // <-- short-term memory
    }, { gmailAccessToken: accessToken });

    const sent = !!sendResp?.data?.sent; hideTyping();
    const out = sent ? "✅ Email sent." : "⚠️ Attempted to send, but the server did not confirm success.";
    appendMessage("assistant", out); maybeSpeak(out);
  } catch (e) {
    console.error("handleSendEmail error:", e);
    hideTyping();
    appendMessage("assistant", `❌ Couldn't send email: ${e?.message || e}`);
  }
}

// Calendar: answer (read-only)
async function handleCalendarAnswer(question) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.CALENDAR_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Calendar access to answer that.", { animate: false }); return; }

    const active = getActiveThreadId() || createThread().id;
    const messages = buildMessageWindow(active);

    const payload = { query: question, max_results: 100, messages }; // <-- short-term memory
    const res = await httpPostJSON("/calendar/answer", payload, { gmailAccessToken: accessToken });

    const answer = res?.data?.answer || "❌ No answer.";
    hideTyping(); appendMessage("assistant", answer); maybeSpeak(answer);
  } catch (e) {
    console.error("handleCalendarAnswer error:", e);
    hideTyping(); addAssistantMessage(`❌ Calendar answer failed: ${e?.message || e}`, { animate: false });
  }
}

// Calendar: schedule (draft → confirm → create)
async function handleScheduleEvent(instruction) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.CALENDAR_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Calendar access to schedule that.", { animate: false }); return; }

    const active = getActiveThreadId() || createThread().id;
    const messages = buildMessageWindow(active);

    const draftResp = await httpPostJSON("/calendar/plan", {
      instruction,
      confirm: false,
      default_duration_minutes: 30,
      messages, // <-- short-term memory
    }, { gmailAccessToken: accessToken });

    const plan = draftResp?.data;
    if (!plan || !plan.event) { hideTyping(); appendMessage("assistant", "❌ Couldn't draft the event."); return; }

    const ev = plan.event; const summary = plan.human_summary || "Draft event";
    hideTyping();
    const preview =
      `**Event Preview**\n\n` +
      `- **Title:** ${escapeHTML(ev.summary || "(no title)")}\n` +
      `- **Start:** ${escapeHTML(ev.start || "")} ${ev.timezone ? `(${escapeHTML(ev.timezone)})` : ""}\n` +
      `- **End:** ${escapeHTML(ev.end || "")}\n` +
      (ev.location ? `- **Location:** ${escapeHTML(ev.location)}\n` : "") +
      (Array.isArray(ev.attendees) && ev.attendees.length ? `- **Attendees:** ${ev.attendees.map(a => escapeHTML(a)).join(", ")}\n` : "") +
      (ev.conference ? `- **Meet/Zoom:** requested\n` : "") +
      (ev.description ? `\n**Notes:**\n${escapeHTML(ev.description)}\n` : "") +
      `\n\`\`\`\n${summary}\n\`\`\`\n\nCreate this event?`;

    appendMessage("assistant", preview);
    const yes = confirm(
      `Create this event?\n\n${ev.summary}\n${ev.start} → ${ev.end}${ev.timezone ? " " + ev.timezone : ""}\n` +
      (ev.location ? `\nLocation: ${ev.location}` : "") +
      (Array.isArray(ev.attendees) && ev.attendees.length ? `\nAttendees: ${ev.attendees.join(", ")}` : "") +
      (ev.description ? `\n\n${ev.description}` : "")
    );
    if (!yes) { appendMessage("assistant", "👍 Not created. Edit your instruction and try again."); return; }

    showTyping();
    const createResp = await httpPostJSON("/calendar/plan", {
      instruction,
      confirm: true,
      event: ev,
      send_updates: "all",
      messages, // <-- short-term memory
    }, { gmailAccessToken: accessToken });

    const link = createResp?.data?.htmlLink || createResp?.data?.selfLink || null; hideTyping();
    const out = link ? `✅ Event created.\n\n[Open in Calendar](${link})` : "✅ Event created (no link returned).";
    appendMessage("assistant", out); maybeSpeak("Event created.");
  } catch (e) {
    console.error("handleScheduleEvent error:", e);
    hideTyping(); appendMessage("assistant", `❌ Couldn't create the event: ${e?.message || e}`);
  }
}
// Health: realistic onboarding flow
async function handleHealth(question) {
  const msg =
    "🩺 **Health Integration Setup**\n\n" +
    "To enable health features with HushhVoice, you need to pair a compatible smartwatch:\n\n" +
    "1. On your phone or laptop, open **Bluetooth settings** and ensure Bluetooth is turned on.\n" +
    "2. Put your **NoiseFit Halo** (or another supported device) into pairing mode.\n" +
    "3. Select your watch from the Bluetooth devices list and confirm pairing.\n" +
    "4. Once paired, grant permission for **heart rate, steps, sleep, and activity data** to be shared with HushhVoice.\n" +
    "5. Return to HushhVoice and type `connect health` to verify the connection.\n\n" +
    "Currently, only NoiseFit Halo is officially supported. Support for other brands (Apple Watch, Garmin, Fitbit, etc.) will roll out soon. " +
    "If the watch disconnects, just re-enable Bluetooth and reopen HushhVoice — it will auto-sync health data securely.";

  hideTyping();
  appendMessage("assistant", msg);
}



/* =============================
   16) SEND QUERY FLOW (thread-aware + memory)
   ============================= */
async function sendQuery(rawQuery) {
  const query = rawQuery?.trim(); if (!query) return;

  // Ensure an active thread exists and **persist** the user message
  const active = getActiveThreadId() || createThread().id;
  setActiveThreadId(active);
  renderThreads();

  appendMessage("user", query); // persist + render
  els.input.value = ""; autoResize(); showTyping();

  try {
    const intentObj = await classifyIntent(query);
    const intent = intentObj?.intent || "general";
    console.log("Detected intent:", intent);

    if (intent === "read_email") { await handleReadEmail(query); return; }
    if (intent === "send_email") { await handleSendEmail(query); return; }
    if (intent === "calendar_answer") { await handleCalendarAnswer(query); return; }
    if (intent === "schedule_event") { await handleScheduleEvent(query); return; }
    if (intent === "health") { await handleHealth(query); return; }


    // General chat with short-term memory window
    const messages = buildMessageWindow(active);
    const data = await httpPostJSON("/echo", { messages }); // <-- memory sent
    const serverText = data?.response || data?.data?.response || "❌ No response.";
    hideTyping();
    appendMessage("assistant", serverText);
    maybeSpeak(serverText);
  } catch (e) {
    console.error(e);
    hideTyping();
    appendMessage("assistant", "⚠️ Couldn’t connect to server.");
  }
}

/* =============================
   17) INPUT UX
   ============================= */
function autoResize() {
  if (!els.input) return;
  els.input.style.height = "auto";
  els.input.style.height = Math.min(220, els.input.scrollHeight) + "px";
}
els.input?.addEventListener("input", autoResize);
els.input?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuery(els.input.value); }
});
els.sendBtn?.addEventListener("click", () => sendQuery(els.input.value));
els.stopBtn?.addEventListener("click", stopSpeaking);

/* Wire “New Chat” — prevent duplicate bindings */
(function initNewChatButton() {
  if (window.__HV_NEW_CHAT_BOUND__) return;   // guard
  window.__HV_NEW_CHAT_BOUND__ = true;

  const btn = document.getElementById("chat-new");
  if (!btn) return;

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const t = createThread("Untitled");
    renderThreads();
    openThread(t.id);
  });
})();

/* =============================
   19) INIT
   ============================= */

function initializeApp() {
  // First, handle authentication
  const userIsLoggedIn = checkLoginStatus();
  if (!userIsLoggedIn) {
    initGoogle(); // Only show the Google button if the user is logged out
  }

  // Now, run all other startup tasks
  // Bio & Memory
  setBioPreview(lsGet(KEYS.BIO, ""));

  // Vision
  els.cameraBtn?.addEventListener("click", () => els.imageInput?.click());
  els.galleryBtn?.addEventListener("click", () => els.imageInputGallery?.click());
  // ... (add back your onPick and event listeners for image inputs here) ...

  els.input?.focus?.();
  autoResize();

  // THREADS: boot, restore, or create first thread
  renderThreads();
  const activeId = getActiveThreadId();
  if (activeId) {
    openThread(activeId);
  } else if (loadThreads().length) {
    openThread(loadThreads()[0].id);
  } else {
    const t = createThread("Untitled");
    openThread(t.id);
  }

  // One-time intro message
  if (!lsGet(KEYS.ONBOARDED, false)) {
    const active = getActiveThreadId() || createThread().id;
    setActiveThreadId(active);
    const intro = getIntroMessage();
    const msgs = loadMsgs(active) || [];
    const alreadyThere = msgs.some(m => m.role === "assistant" && m.text === intro);
    if (!alreadyThere) {
      appendMessage("assistant", intro);
    }
    lsSet(KEYS.ONBOARDED, true);
  }
  if (els.logoutBtn) {
    els.logoutBtn.addEventListener("click", handleLogout);
  }
}

// The ONLY event listener you need for initialization
document.addEventListener('DOMContentLoaded', initializeApp);
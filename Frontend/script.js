/*
============================================================
 HushhVoice — script.js (Clean, organized, with calendar+email intents)
 Layers (top → bottom):
  0) DOM Hooks
  1) Config & Keys
  2) State & Utilities
  3) LocalStorage helpers
  4) Google Auth (ID token) + Profile
  4a) Generic OAuth Token Cache (Calendar/Gmail/etc.)
  5) Network helpers (fetch + retry)
  6) UI rendering helpers
  7) TTS (speech out)
  8) Mic (press & hold)
  9) Sidebar / Nav
 10) Bio (modal + preview)
 11) RAG Memory
 12) Facts (placeholder)
 13) Calendar helpers (time utils)
 14) Intent classifier
 15) Action handlers
     - handleReadEmail
     - handleSendEmail (draft → confirm → send)
     - handleCalendarAnswer
     - handleScheduleEvent (draft → confirm → create)
 16) Send Query Flow (entry point)
 17) Input UX
 18) Init
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

  // RAG Memory
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
  BASE_URL: "https://40650b5a7c0f.ngrok-free.app",
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
};

const KEYS = {
  GOOGLE_ID_TOKEN: "google_token",
  USER_EMAIL: "user_email",
  USER_NAME: "user_name",
  BIO: "hushh_bio",
  MEMORIES: "hushh_memories",
  FACTS: "hushh_facts",
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
  t.className = "toast";
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

function initGoogle() {
  if (window.google?.accounts?.id) {
    google.accounts.id.initialize({ client_id: CONFIG.CLIENT_ID, callback: handleGoogleLogin });
    google.accounts.id.renderButton(els.googleLogin, { theme: "outline", size: "large", width: "100%" });
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
  if (html != null) { const content = node.querySelector(".content"); if (content) content.innerHTML = html; }
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
  els.chatBox.appendChild(node); autoScrollChat();
  if (animate) { typeMarkdown(content, text); } else { content.innerHTML = renderMarkdownToHTML(text); }
}
let typingNode = null;
function showTyping() { if (typingNode) return; typingNode = renderFromTemplate(els.tplTyping); els.chatBox.appendChild(typingNode); autoScrollChat(); }
function hideTyping() { if (!typingNode) return; typingNode.remove(); typingNode = null; }

/* =============================
   7) TTS (speech out)
   ============================= */
let currentAudio = null;
async function speak(text) {
  if (!text) return;
  const voice = els.voiceSelect ? els.voiceSelect.value : "alloy";
  if (currentAudio && !currentAudio.paused) { currentAudio.pause(); currentAudio.currentTime = 0; }
  try {
    const res = await fetch(`${CONFIG.BASE_URL}/tts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, voice }) });
    if (!res.ok) throw new Error(`TTS request failed: ${res.status}`);
    const audioBlob = await res.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    currentAudio = new Audio(audioUrl);
    currentAudio.play().catch(() => toast("🔈 Click anywhere to allow audio, then try again.", "error"));
  } catch (err) { console.error("TTS playback failed:", err); toast("🔈 Could not play TTS audio", "error"); }
}
function stopSpeaking() { if (currentAudio && !currentAudio.paused) { currentAudio.pause(); currentAudio.currentTime = 0; } }

/* =============================
   8) MIC (press & hold)
   ============================= */
let recognition = null; let micSupported = false; let recording = false;
(function initMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { micSupported = false; els.micBtn?.addEventListener("click", () => toast("Mic not supported in this browser.", "error")); els.micBtn?.setAttribute("disabled", "true"); return; }
  micSupported = true; recognition = new SR();
  recognition.lang = "en-US"; recognition.continuous = false; recognition.interimResults = false; recognition.maxAlternatives = 1;
  recognition.onresult = (e) => { const transcript = e.results?.[0]?.[0]?.transcript || ""; if (transcript.trim()) sendQuery(transcript.trim()); };
  recognition.onerror = (e) => { if (e.error === "not-allowed" || e.error === "service-not-allowed") { try { els.micHelp?.showModal?.(); } catch { } } else { toast(`Mic error: ${e.error || "unknown"}`, "error"); } stopMicUI(); };
  recognition.onend = () => stopMicUI();
  els.micBtn?.addEventListener("mousedown", startMicFlow);
  document.addEventListener("mouseup", () => recording && stopMicFlow());
  els.micBtn?.addEventListener("touchstart", (e) => { e.preventDefault(); startMicFlow(); }, { passive: false });
  document.addEventListener("touchend", () => recording && stopMicFlow());
})();
async function startMicFlow() { if (!micSupported || !recognition || recording) return; try { if (navigator.mediaDevices?.getUserMedia) { await navigator.mediaDevices.getUserMedia({ audio: true }); } } catch { } startMicUI(); try { recognition.start(); } catch { stopMicUI(); } }
function stopMicFlow() { try { recognition?.stop(); } catch { } stopMicUI(); }
function startMicUI() { recording = true; els.micBtn?.classList.add("recording"); els.micBtn?.setAttribute("aria-pressed", "true"); }
function stopMicUI() { recording = false; els.micBtn?.classList.remove("recording"); els.micBtn?.setAttribute("aria-pressed", "false"); }

/* =============================
   9) SIDEBAR / NAV
   ============================= */
let lockedScrollY = 0;
function openSidebar() { if (!els.sidebar) return; lockedScrollY = window.scrollY || window.pageYOffset || 0; document.body.style.top = `-${lockedScrollY}px`; document.body.classList.add("nav-open"); els.sidebar.classList.add("open"); els.sidebarToggle?.setAttribute("aria-expanded", "true"); els.sidebar?.setAttribute("aria-hidden", "false"); }
function closeSidebar() { if (!els.sidebar) return; els.sidebar.classList.remove("open"); els.sidebarToggle?.setAttribute("aria-expanded", "false"); els.sidebar?.setAttribute("aria-hidden", "true"); document.body.classList.remove("nav-open"); const y = Math.abs(parseInt(document.body.style.top || "0", 10)) || 0; document.body.style.top = ""; window.scrollTo(0, y); }
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
function setBioPreview(text) { const t = sanitize(text); els.bioPreviewText.textContent = t ? t : "Add a short bio to personalize your assistant."; }
function openBioModal() { if (!els.bioModal) return; els.bioText.value = loadBio(); try { els.bioModal.showModal(); } catch { } }
function closeBioModal() { try { els.bioModal.close(); } catch { } }
els.openBioBtn?.addEventListener("click", openBioModal);
els.editBioInline?.addEventListener("click", openBioModal);
els.bioForm?.addEventListener("submit", (e) => { e.preventDefault(); const submitter = e.submitter?.value || e.submitter?.textContent?.toLowerCase(); if (submitter === "cancel") { closeBioModal(); return; } const text = sanitize(els.bioText.value); saveBio(text); setBioPreview(text); closeBioModal(); toast("Bio saved."); });



/* =============================
   12) FACTS (placeholder)
   ============================= */
els.addFactBtn?.addEventListener("click", () => { const fact = prompt("Add a quick fact:"); if (!fact) return; const li = document.createElement("li"); li.textContent = fact.trim(); els.factList?.appendChild(li); });

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
  const [date, time] = isoLocal.split("T"); const [Y, M, D] = date.split("-").map(Number); const [h, m] = time.split(":").map(Number);
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
   15) ACTION HANDLERS
   ============================= */
// Emails: read inbox Q&A
async function handleReadEmail(question) {
  const accessToken = await ensureAccessToken(CONFIG.GMAIL_SCOPES);
  if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Gmail access to proceed.", { animate: false }); return; }
  const data = await httpPostJSON("/mailgpt/answer", { query: question, max_results: CONFIG.DEFAULT_EMAIL_FETCH }, { gmailAccessToken: accessToken });
  const answer = data?.data?.answer || "❌ No answer."; hideTyping(); addAssistantMessage(answer, { animate: false }); speak(answer);
}

// Emails: send (draft → confirm → send)
async function handleSendEmail(instruction) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.GMAIL_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Gmail access to draft/send email.", { animate: false }); return; }

    const draftResp = await httpPostJSON("/mailgpt/reply", { instruction, max_results: 10, send: false }, { gmailAccessToken: accessToken });
    const drafted = draftResp?.data?.drafted; if (!drafted) { hideTyping(); addAssistantMessage("❌ Could not generate a draft from your inbox context.", { animate: false }); return; }

    const to = drafted.to_email || "(unknown)"; const subject = drafted.subject || "(no subject)"; const body = drafted.body || "";
    hideTyping();
    addAssistantMessage(`**Draft preview**\n\n- **To:** ${escapeHTML(to)}\n- **Subject:** ${escapeHTML(subject)}\n\n\`\`\`\n${body}\n\`\`\`\n\nSend this email?`, { animate: false });
    const yes = confirm(`Send this email?\n\nTo: ${to}\nSubject: ${subject}\n\n---\n${body}`);
    if (!yes) { addAssistantMessage("👍 Draft not sent. You can edit your instruction and try again.", { animate: false }); return; }

    showTyping();
    const sendResp = await httpPostJSON("/mailgpt/reply", { instruction, max_results: 10, send: true }, { gmailAccessToken: accessToken });
    const sent = !!sendResp?.data?.sent; hideTyping();
    if (sent) { addAssistantMessage("✅ Email sent.", { animate: false }); speak("Email sent."); }
    else { addAssistantMessage("⚠️ Attempted to send, but the server did not confirm success.", { animate: false }); speak("There was an issue sending the email."); }
  } catch (e) { console.error("handleSendEmail error:", e); hideTyping(); addAssistantMessage(`❌ Couldn't send email: ${e?.message || e}`, { animate: false }); }
}

// Calendar: answer (read-only)
async function handleCalendarAnswer(question) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.CALENDAR_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Calendar access to answer that.", { animate: false }); return; }
    const payload = { query: question, max_results: 100 };
    const res = await httpPostJSON("/calendar/answer", payload, { gmailAccessToken: accessToken });
    const answer = res?.data?.answer || "❌ No answer."; hideTyping(); addAssistantMessage(answer, { animate: false }); speak(answer);
  } catch (e) { console.error("handleCalendarAnswer error:", e); hideTyping(); addAssistantMessage(`❌ Calendar answer failed: ${e?.message || e}`, { animate: false }); }
}

// Calendar: schedule (draft → confirm → create)
async function handleScheduleEvent(instruction) {
  try {
    const accessToken = await ensureAccessToken(CONFIG.CALENDAR_SCOPES);
    if (!accessToken) { hideTyping(); addAssistantMessage("🔐 I need Calendar access to schedule that.", { animate: false }); return; }

    const draftResp = await httpPostJSON("/calendar/plan", { instruction, confirm: false, default_duration_minutes: 30 }, { gmailAccessToken: accessToken });
    const plan = draftResp?.data; if (!plan || !plan.event) { hideTyping(); addAssistantMessage("❌ Couldn't draft the event.", { animate: false }); return; }

    const ev = plan.event; const summary = plan.human_summary || "Draft event";
    hideTyping();
    addAssistantMessage(
      `**Event Preview**\n\n` +
      `- **Title:** ${escapeHTML(ev.summary || "(no title)")}\n` +
      `- **Start:** ${escapeHTML(ev.start || "")} ${ev.timezone ? `(${escapeHTML(ev.timezone)})` : ""}\n` +
      `- **End:** ${escapeHTML(ev.end || "")}\n` +
      (ev.location ? `- **Location:** ${escapeHTML(ev.location)}\n` : "") +
      (Array.isArray(ev.attendees) && ev.attendees.length ? `- **Attendees:** ${ev.attendees.map(a => escapeHTML(a)).join(", ")}\n` : "") +
      (ev.conference ? `- **Meet/Zoom:** requested\n` : "") +
      (ev.description ? `\n**Notes:**\n${escapeHTML(ev.description)}\n` : "") +
      `\n\`\`\`\n${summary}\n\`\`\`\n\nCreate this event?`,
      { animate: false }
    );

    const yes = confirm(
      `Create this event?\n\n${ev.summary}\n${ev.start} → ${ev.end}${ev.timezone ? " " + ev.timezone : ""}\n` +
      (ev.location ? `\nLocation: ${ev.location}` : "") +
      (Array.isArray(ev.attendees) && ev.attendees.length ? `\nAttendees: ${ev.attendees.join(", ")}` : "") +
      (ev.description ? `\n\n${ev.description}` : "")
    );
    if (!yes) { addAssistantMessage("👍 Not created. Edit your instruction and try again.", { animate: false }); return; }

    showTyping();
    const createResp = await httpPostJSON("/calendar/plan", { instruction, confirm: true, event: ev, send_updates: "all" }, { gmailAccessToken: accessToken });
    const link = createResp?.data?.htmlLink || createResp?.data?.selfLink || null; hideTyping();
    if (link) { addAssistantMessage(`✅ Event created.\n\n[Open in Calendar](${link})`, { animate: false }); speak("Event created."); }
    else { addAssistantMessage("✅ Event created (no link returned).", { animate: false }); speak("Event created."); }
  } catch (e) { console.error("handleScheduleEvent error:", e); hideTyping(); addAssistantMessage(`❌ Couldn't create the event: ${e?.message || e}`, { animate: false }); }
}

/* =============================
   16) SEND QUERY FLOW (entry point)
   ============================= */
async function sendQuery(rawQuery) {
  const query = rawQuery?.trim(); if (!query) return;
  addUserMessage(query); els.input.value = ""; autoResize(); showTyping();
  try {
    const intentObj = await classifyIntent(query); const intent = intentObj?.intent || "general";
    console.log("Detected intent:", intent);

    if (intent === "read_email") { await handleReadEmail(query); return; }
    if (intent === "send_email") { await handleSendEmail(query); return; }
    if (intent === "calendar_answer") { await handleCalendarAnswer(query); return; }
    if (intent === "schedule_event") { await handleScheduleEvent(query); return; }

    const data = await httpPostJSON("/echo", { query });
    const serverText = data?.response || data?.data?.response || "❌ No response.";
    hideTyping(); addAssistantMessage(serverText); speak(serverText);
  } catch (e) { console.error(e); hideTyping(); addAssistantMessage("⚠️ Couldn’t connect to server.", { animate: false }); }
}

/* =============================
   17) INPUT UX
   ============================= */
function autoResize() { if (!els.input) return; els.input.style.height = "auto"; els.input.style.height = Math.min(220, els.input.scrollHeight) + "px"; }
els.input?.addEventListener("input", autoResize);
els.input?.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuery(els.input.value); } });
els.sendBtn?.addEventListener("click", () => sendQuery(els.input.value));
els.stopBtn?.addEventListener("click", stopSpeaking);

/* =============================
   18) INIT
   ============================= */
window.addEventListener("load", () => {
  // Auth UI
  initGoogle();
  const email = lsGet(KEYS.USER_EMAIL);
  setAuthUI(email);

  // Bio & Memory
  setBioPreview(lsGet(KEYS.BIO, ""));
  renderMemories(loadMemories());

  // Vision (placeholders)
  els.cameraBtn?.addEventListener("click", () => els.imageInput?.click());
  els.galleryBtn?.addEventListener("click", () => els.imageInputGallery?.click());

  async function onPick(file) {
    if (!file) return;
    try { const processed = await downscaleImage(file); showAttachmentPreview(processed); }
    catch { toast("Could not process image", "error"); }
  }
  els.imageInput?.addEventListener("change", (e) => onPick(e.target.files?.[0]));
  els.imageInputGallery?.addEventListener("change", (e) => onPick(e.target.files?.[0]));

  els.input?.focus?.();
  autoResize();
});

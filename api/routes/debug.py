from __future__ import annotations

from flask import Blueprint, Response, request

from utils.debug_events import clear_events, debug_enabled, list_events
from utils.json_helpers import jerror, jok


debug_bp = Blueprint("debug", __name__)


@debug_bp.get("/debug/events")
def debug_events():
    if not debug_enabled():
        return jerror("Debug console disabled", 404, "not_found")
    since = int(request.args.get("since") or 0)
    events = list_events(since)
    return jok({"events": events})


@debug_bp.post("/debug/clear")
def debug_clear():
    if not debug_enabled():
        return jerror("Debug console disabled", 404, "not_found")
    clear_events()
    return jok({"ok": True})


@debug_bp.get("/debug")
@debug_bp.get("/debug/ui")
def debug_ui():
    if not debug_enabled():
        return jerror("Debug console disabled", 404, "not_found")

    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>HushhVoice Debug Console</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #0e0f12;
      --panel: #171a21;
      --text: #e7e9ee;
      --muted: #8a93a3;
      --accent: #53c1ff;
      --warn: #ffb454;
      --error: #ff6b6b;
      --border: #262a35;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      background: var(--bg);
      color: var(--text);
    }
    header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }
    .title {
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.4px;
    }
    .controls {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    input, button {
      background: var(--panel);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 12px;
    }
    button { cursor: pointer; }
    .layout {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
      padding: 16px 20px 24px;
    }
    .status {
      color: var(--muted);
      font-size: 12px;
    }
    .event {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      display: grid;
      gap: 8px;
    }
    .event-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 12px;
      color: var(--muted);
    }
    .event-title {
      font-size: 13px;
      color: var(--text);
    }
    .event-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
    }
    .badge {
      padding: 2px 6px;
      border-radius: 999px;
      background: #222734;
      color: var(--accent);
    }
    .badge.error { color: var(--error); }
    .badge.warn { color: var(--warn); }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #c7d0e1;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <header>
    <div class="title">HushhVoice Debug Console</div>
    <div class="controls">
      <input id="filter" placeholder="filter text or request id">
      <button id="pause">Pause</button>
      <button id="clear">Clear</button>
    </div>
  </header>
  <div class="layout">
    <div class="status" id="status">Connecting...</div>
    <div id="events"></div>
  </div>

  <script>
    let lastId = 0;
    let paused = false;
    let events = [];

    const els = {
      events: document.getElementById("events"),
      status: document.getElementById("status"),
      filter: document.getElementById("filter"),
      pause: document.getElementById("pause"),
      clear: document.getElementById("clear"),
    };

    function fmtTime(ts) {
      const d = new Date(ts * 1000);
      return d.toLocaleTimeString();
    }

    function badgeClass(level) {
      if (level === "error") return "badge error";
      if (level === "warn") return "badge warn";
      return "badge";
    }

    function matchesFilter(ev) {
      const q = (els.filter.value || "").toLowerCase().trim();
      if (!q) return true;
      const hay = JSON.stringify(ev).toLowerCase();
      return hay.includes(q);
    }

    function render() {
      const filtered = events.filter(matchesFilter).slice(-200).reverse();
      els.events.innerHTML = "";
      for (const ev of filtered) {
        const div = document.createElement("div");
        div.className = "event";
        const dataText = JSON.stringify(ev.data || {}, null, 2);
        div.innerHTML = `
          <div class="event-header">
            <div>${fmtTime(ev.ts)} · ${ev.category}</div>
            <div class="${badgeClass(ev.level)}">${ev.level}</div>
          </div>
          <div class="event-title">${ev.message}</div>
          <div class="event-meta">
            <span>id: ${ev.id}</span>
            <span>request: ${ev.request_id || "-"}</span>
          </div>
          <pre>${dataText}</pre>
        `;
        els.events.appendChild(div);
      }
    }

    async function poll() {
      if (paused) return;
      try {
        const res = await fetch(`/debug/events?since=${lastId}`);
        const payload = await res.json();
        const list = (payload.data && payload.data.events) || [];
        if (list.length) {
          events = events.concat(list);
          lastId = list[list.length - 1].id;
          render();
        }
        els.status.textContent = `Live · ${events.length} events`;
      } catch (e) {
        els.status.textContent = "Disconnected";
      }
    }

    els.pause.addEventListener("click", () => {
      paused = !paused;
      els.pause.textContent = paused ? "Resume" : "Pause";
    });

    els.clear.addEventListener("click", async () => {
      await fetch("/debug/clear", { method: "POST" });
      events = [];
      lastId = 0;
      render();
    });

    els.filter.addEventListener("input", render);
    setInterval(poll, 1000);
    poll();
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html")

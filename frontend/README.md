# HushhVoice Frontend

This folder contains a static HTML/CSS/JS web client that talks to the Flask backend in `api/`.
Note: the new chat streaming WebSocket (`/chat/stream`) is currently used by the iOS app, not this web UI.

## Files

- `index.html` — Main UI markup (chat layout, sidebar, auth widgets, templates).
- `style.css` — All styling, layout, and animation rules.
- `script.js` — App logic: chat state, API calls, Google auth, TTS, memory, and UI behaviors.
- `Images/` — Logos and visual assets used by the UI.

## How The Frontend Works

- Uses plain HTML, CSS, and vanilla JS.
- Uses `/intent/classify` to route requests to chat, Gmail, or Calendar flows.
- Talks to the backend via `fetch` calls to `/echo` (or `/echo/stream`), `/mailgpt/answer`, `/mailgpt/reply`, `/calendar/answer`, `/calendar/plan`, `/tts`.
- Builds a short-term memory window from localStorage threads and sends it as `messages` on each request.
- Google sign-in is handled by the GIS client script loaded in `index.html`; Gmail/Calendar calls send `X-Google-Access-Token`.
- The backend base URL is configured in `script.js` under `CONFIG.BASE_URL`.

## Config Knobs (script.js)

- `CONFIG.BASE_URL` — Backend base URL.
- `CONFIG.CLIENT_ID` — Google OAuth client ID.
- `CONFIG.USE_STREAMING` — Use `/echo/stream` instead of `/echo`.
- `CONFIG.MEMORY_WINDOW_MESSAGES` — Number of recent messages included in each call.
- `CONFIG.AUTO_TTS` — Auto-play TTS after responses.

## Run Locally

From the project root:

```bash
cd frontend
python -m http.server 5500
```

Then open:

```
http://127.0.0.1:5500
```

## Pointing To Your Backend

Edit `script.js` and set:

```
CONFIG.BASE_URL = "http://127.0.0.1:5050";
```

If you are using ngrok:

```
CONFIG.BASE_URL = "https://xxxx.ngrok-free.app";
```

If you deploy the frontend + backend together (e.g., Vercel with `/api/*` routing),
set:

```
CONFIG.BASE_URL = "/api";
```

Make sure the backend is running first:

```bash
python api/index.py
```

## Google OAuth Client ID

The Google client ID is also configured in `script.js`:

```
CONFIG.CLIENT_ID = "...apps.googleusercontent.com";
```

If you change this, make sure the ID is also authorized in your Google Cloud Console and the OAuth consent screen is configured.

## Common Issues

- If the UI says the server hostname could not be found, verify `CONFIG.BASE_URL` matches your backend or ngrok URL exactly.
- If Google sign-in fails, confirm the client ID and JavaScript origin are correct.

If you want a build step or a Vite-based setup later, I can add that.

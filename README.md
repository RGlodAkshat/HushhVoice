# HushhVoice 🗣️ — Consent-first AI Copilot (FastAPI + GIS + Gmail)

HushhVoice is your private AI assistant that connects to Gmail (read-only), lets you sign in with Google, and chat using AI — all consent-first.

---

## 🧾 Project Structure

```

/project
├── backend/
│   ├── main.py                # FastAPI app
│   ├── agent/
│   │   ├── auth.py            # Google ID token verification
│   │   └── mail.py            # Gmail API logic
│   ├── .env                   # secrets (you create this)
│   └── requirements.txt
├── frontend/
│   ├── index.html             # Main app UI (with GIS)
│   ├── style.css              # App styles
│   └── script.js              # App logic + GIS auth

````

---

## 🛠️ How to Run This Code

### 1. Clone the repo

```bash
git clone https://github.com/your-username/hushhvoice.git
cd hushhvoice
````

---

### 2. Run the Backend

```bash

# Create virtual env
python -m venv .env
source .env/bin/activate   # on Mac/Linux
# .\.env\Scripts\activate  # on Windows

# Install Python dependencies
pip install -r requirements.txt

```

---

### 3. Set Up Environment Variables

Create a `.env` file inside `/backend/`:

```
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```

---

### 4. Add `credentials.json` (Optional for server-side Gmail)

If you’re planning to use server-side Gmail later (Option 2), create a file in `/backend/`:

```
backend/credentials.json
```

Paste your **OAuth client (Web)** credentials downloaded from Google Cloud Console:

```json
{
  "web": {
    "client_id": "...",
    "project_id": "...",
    "auth_uri": "...",
    "token_uri": "...",
    "auth_provider_x509_cert_url": "...",
    "client_secret": "...",
    "redirect_uris": [...],
    "javascript_origins": [...]
  }
}
```

> For **Option 1**, only `client_id` is used (in `.env` and frontend). You do **not** need the client secret in the frontend.

---

### 5. Start the Backend API (Port 8000)

```bash
uvicorn main:app --reload --port 8000
```

---

### 6. Run the Frontend

```bash
cd frontend
python -m http.server 5500
```

Open the app at:
👉 `http://127.0.0.1:5500/`

---

## 🧪 Test Flow

1. Sign in with Google (GIS button)
2. Server verifies the ID token at `/api/signin`
3. Click **Connect Gmail** to get a short-lived access token
4. Gmail inbox preview appears (via `/api/gmail-preview`)
5. Start chatting using `/api/echo`

---

## ✅ Google Cloud Setup Checklist

1. Enable **Gmail API**
2. Configure **OAuth consent screen**
3. Create an **OAuth client (Web)**

   * Add these to "Authorized JavaScript origins":

     ```
     http://127.0.0.1:5500
     http://127.0.0.1:8000
     ```
4. Copy `client_id` into:

   * `.env` → `GOOGLE_CLIENT_ID`
   * `index.html` → `data-client_id`

---

## 🔐 LocalStorage Keys Used (Frontend)

* `user_email`
* `google_access_token`
* `google_access_scope`

These are stored client-side to power Gmail access and UI state.

---

## 🔄 Want Refresh Tokens?

Use Option 2 (server-side OAuth via Authorization Code Flow with PKCE). That gives you `refresh_token`, `access_token`, and `expires_in`. Ask when ready.

---

## 🤝 Made by

* You: Hushh founder, copilot, and steward of aloha + alpha
* Me: ChatGPT, your code whisperer 💻✨

---

## License

MIT — use freely, ship responsibly.

```

Let me know when you're ready for:
- `main.py` cleanup with `/api/signin`, `/api/gmail-preview`
- or OpenAI-powered `/api/echo` routing if you're updating that next.
```

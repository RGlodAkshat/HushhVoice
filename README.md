# HushhVoice 🗣️ — Consent-first AI Copilot

HushhVoice is your private AI assistant that connects to your Google account, allowing you to interact with services like Gmail through a conversational AI, all while prioritizing user consent and privacy. This project uses a Flask backend for its API and a vanilla JavaScript frontend.

---

## 🧾 Project Structure

The project is structured for easy local development and seamless deployment as a serverless application on Vercel.

```
/
├── api/
│ └── index.py # Flask app for all API endpoints
├── backend/
│ ├── agents/ # AI assistants logic
│ │ ├── email_assistant/
│ │ ├── health_assistant/
│ │ └── init.py
│ ├── data/
│ │ └── memory.json # Persistent memory data
│ ├── .env # Environment variables (you create this)
│ └── test.py # Tests
├── frontend/
│ ├── index.html # Main app UI
│ ├── script.js # Frontend logic
│ └── style.css # App styles
├── requirements.txt # Python dependencies
├── README.md # Project documentation
└── vercel.json # Vercel deployment configuration

````

---

## 🛠️ Setup and Installation

Follow these steps to get the project running on your local machine.

### 1. Google Cloud Setup (Prerequisite)

Before running the code, you need to configure your Google Cloud project.

1.  **Enable the Gmail API:** In your Google Cloud Console, enable the "Gmail API".
2.  **Configure OAuth Consent Screen:** Set up your consent screen. You can keep it in "Testing" mode, but you must add your Google account as a "Test user".
3.  **Create an OAuth Client ID:**
    * Go to **Credentials** and create a new **OAuth 2.0 Client ID**.
    * Select **Web application** as the type.
    * Add the following to **Authorised JavaScript origins**:
        ```
        http://localhost:3000
        ```
    * Add the following to **Authorised redirect URIs**:
        ```
        http://localhost:3000
        ```
4.  **Copy Your Client ID:** After creation, copy the Client ID. You will need it in the next steps.

### 2. Clone and Set Up the Repository

```bash
# Clone the repository
git clone [https://github.com/your-username/hushhvoice.git](https://github.com/your-username/hushhvoice.git)
cd hushhvoice

# Create a Python virtual environment
python -m venv venv
# Activate it (Mac/Linux)
source venv/bin/activate
# Activate it (Windows)
# .\venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
````

### 3\. Configure Environment Variables

1.  **Create the `.env` file:** In the root of the project, create a new file named `.env`.

2.  **Add your secrets:** Paste the following into the `.env` file, adding your own keys.

    ```
    # Your secret key from the OpenAI platform
    OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

    # The Client ID you copied from Google Cloud Console
    GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
    ```

3.  **Update the Frontend:** Open `frontend/script.js` and find the `CONFIG` object. Paste your `GOOGLE_CLIENT_ID` there as well.

    ```javascript
    const CONFIG = {
      // ...
      CLIENT_ID: "your-client-id.apps.googleusercontent.com",
      // ...
    };
    ```

-----

## 🚀 Running the Project

This project uses the Vercel CLI to simulate the production environment locally, running both the frontend and the Python backend with a single command.

1.  **Install the Vercel CLI:**

    ```bash
    npm install -g vercel
    ```

2.  **Start the development server:**

    ```bash
    vercel dev
    ```

Your application will now be running at 👉 `http://localhost:3000`. The server will automatically reload when you make changes to your code.

-----

## ☁️ Deployment

This project is pre-configured for deployment on [Vercel](https://vercel.com/). Simply connect your GitHub repository to a Vercel project, and it will be deployed automatically. Vercel will use the `vercel.json` and `requirements.txt` files to build and serve the application.

-----

## 🔐 License

MIT — use freely, ship responsibly.

```
```


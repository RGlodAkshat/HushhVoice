from __future__ import annotations

import os
import sys

# Ensure api/ is on sys.path when running via gunicorn (e.g., Render).
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from config import DEBUG, PORT


# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", PORT)), debug=DEBUG)

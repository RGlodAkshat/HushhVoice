from __future__ import annotations

import os

from app_context import DEBUG, PORT, app

# Register routes and handlers
import error_handlers  # noqa: F401
import routes_meta  # noqa: F401
import routes_intent  # noqa: F401
import routes_echo  # noqa: F401
import routes_siri  # noqa: F401
import routes_mail  # noqa: F401
import routes_calendar  # noqa: F401
import routes_tts  # noqa: F401
import routes_onboarding_agent  # noqa: F401
import routes_identity_enrich  # noqa: F401


# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", PORT)), debug=DEBUG)

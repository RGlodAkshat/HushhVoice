from __future__ import annotations

import os
import sys

from services.cache_sync_service import refresh_calendar_cache, refresh_gmail_cache


def main() -> None:
    user_id = os.environ.get("HUSHH_CACHE_USER_ID")
    google_token = os.environ.get("HUSHH_GOOGLE_TOKEN")
    if not user_id or not google_token:
        print("Set HUSHH_CACHE_USER_ID and HUSHH_GOOGLE_TOKEN to run.")
        sys.exit(1)

    print("Refreshing Gmail cache...")
    refresh_gmail_cache(user_id, google_token)
    print("Refreshing Calendar cache...")
    refresh_calendar_cache(user_id, google_token)
    print("Done.")


if __name__ == "__main__":
    main()

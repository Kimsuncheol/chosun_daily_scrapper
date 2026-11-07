"""Wake Render, then create one scrape run. Uses only the standard library."""

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    opener = build_opener(NoRedirect)
    base = os.environ["API_BASE_URL"].rstrip("/")
    token = os.environ["SCRAPE_TOKEN"]
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("API_BASE_URL must be an HTTPS origin without a path")
    # Never send the bearer token until the origin has completed its cold start.
    for attempt in range(12):
        try:
            with opener.open(f"{base}/health", timeout=15) as response:
                if json.load(response).get("status") == "ok":
                    break
        except (HTTPError, URLError, TimeoutError, ValueError):
            pass
        if attempt == 11:
            raise SystemExit("Service did not become ready")
        time.sleep(10)
    request = Request(
        f"{base}/api/v1/scrape-runs",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        data=b"",
    )
    try:
        with opener.open(request, timeout=120) as response:
            run = json.load(response)
            print(json.dumps(run, indent=2))
    except HTTPError as exc:
        if exc.code == 409:
            print("Another scrape is running; no additional run created")
            return
        raise SystemExit(f"Scrape endpoint returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, ValueError):
        raise SystemExit(
            "Could not confirm scrape completion; inspect run history before retrying"
        ) from None
    if run.get("status") == "failed" or run.get("failed", 0):
        raise SystemExit("Collection reported failures; inspect run history")


if __name__ == "__main__":
    main()

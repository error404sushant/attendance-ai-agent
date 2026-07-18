import re
import json
from urllib.parse import urlparse, parse_qs


def parse_curl(curl_command: str) -> dict:
    # Normalize: remove line continuations, collapse whitespace
    curl = re.sub(r'\\\n', ' ', curl_command)
    curl = re.sub(r'\s+', ' ', curl).strip()

    # If plain URL is given (no curl keyword), wrap it
    if curl.startswith("http://") or curl.startswith("https://"):
        curl = f"curl '{curl}'"

    # Method
    method_match = re.search(r'-X\s+([A-Z]+)', curl, re.IGNORECASE)
    if method_match:
        method = method_match.group(1).upper()
    elif re.search(r'(?:--data|-d)\s', curl):
        method = "POST"
    else:
        method = "GET"

    # URL — handle single quotes, double quotes, or bare
    url_match = re.search(r"'(https?://[^']+)'|\"(https?://[^\"]+)\"|(https?://\S+)", curl)
    if not url_match:
        raise ValueError("No URL found in curl command")
    url = (url_match.group(1) or url_match.group(2) or url_match.group(3)).rstrip("'\"")

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    endpoint = parsed.path or "/"

    # Query parameters (GET)
    query_params = list(parse_qs(parsed.query).keys())

    # Body parameters (POST)
    body_params = []
    data_match = re.search(r"(?:--data|-d)\s+'([^']*)'|(?:--data|-d)\s+\"([^\"]*)\"", curl)
    if data_match:
        body_str = data_match.group(1) or data_match.group(2) or ""
        try:
            body = json.loads(body_str)
            if isinstance(body, dict):
                body_params = list(body.keys())
        except Exception:
            pass

    parameters = query_params + [p for p in body_params if p not in query_params]

    # Auto-generate internal name from endpoint path
    name_raw = endpoint.strip("/").replace("/", "_").replace("-", "_")
    name = re.sub(r'[^a-z0-9_]', '', name_raw.lower()) or "api_call"

    return {
        "name": name,
        "method": method,
        "base_url": base_url,
        "endpoint": endpoint,
        "parameters": parameters,
    }

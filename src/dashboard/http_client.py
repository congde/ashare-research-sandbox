from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any


def http_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Any:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    return json.loads(raw) if raw else {}


def http_post(
    url: str,
    body: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> Any:
    payload = body.encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=payload, headers=request_headers, method="POST")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body_text[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    return json.loads(raw) if raw else {}

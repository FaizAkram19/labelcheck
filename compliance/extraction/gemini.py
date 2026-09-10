"""Gemini vision extraction.

One network call per scan. Every image goes in the same request so the model can
merge declarations that are split across panels.

If the call fails for any reason the caller gets an exception with a readable
message. Nothing here decides compliance.
"""
import base64
import json
import os
import random
import re
import time

import requests

from .prompt import SYSTEM, build_user_prompt, FIELDS

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "60"))
RETRIES = int(os.environ.get("GEMINI_RETRIES", "3"))

# Transient on Google's side, not ours: 503 is an overloaded model, 500 and 504
# are internal or gateway timeouts. All are worth retrying. 429 is rate limiting
# and is also worth one backed-off retry on the free tier.
RETRYABLE = {429, 500, 502, 503, 504}


class ExtractionError(RuntimeError):
    pass


def _backoff(attempt):
    """Exponential backoff with jitter.

    The jitter matters when several people demo at once: without it every client
    retries in lockstep and hits the same overloaded model at the same instant.
    """
    return (2 ** attempt) + random.uniform(0, 0.5)


def _headers(api_key):
    """Authentication for the Gemini API.

    The key goes in the x-goog-api-key header, not in the URL. Authorization
    keys - the ones starting with AQ. that AI Studio issues now - reject the
    older ?key= query-parameter form. Keeping the secret out of the URL is
    better practice anyway: URLs end up in server logs and proxy logs.
    """
    return {"x-goog-api-key": api_key, "Content-Type": "application/json"}


def list_models(api_key=None):
    """Ask the API which models this key can use.

    Better than guessing a model name from documentation that goes stale.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is not set.")
    try:
        resp = requests.get(API_ROOT, headers=_headers(api_key),
                            params={"pageSize": 200}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ExtractionError(f"Could not reach the API: {exc}") from exc
    if resp.status_code in (401, 403):
        raise ExtractionError(
            f"The API rejected the key (HTTP {resp.status_code}). {resp.text[:200]}")
    if resp.status_code != 200:
        raise ExtractionError(f"Listing models returned {resp.status_code}: {resp.text[:200]}")

    out = []
    for m in resp.json().get("models", []):
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if not methods or "generateContent" in methods:
            out.append(name)
    return out


def _mime_for(name):
    name = (name or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".heic") or name.endswith(".heif"):
        return "image/heic"
    return "image/jpeg"


def _strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract(image_blobs, model=None, api_key=None):
    """image_blobs: list of (filename, bytes). Returns the parsed JSON dict."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ExtractionError(
            "GEMINI_API_KEY is not set. Put it in the .env file at the project root."
        )
    if not image_blobs:
        raise ExtractionError("No images supplied.")

    parts = [{"text": build_user_prompt()}]
    for name, blob in image_blobs:
        parts.append({
            "inline_data": {
                "mime_type": _mime_for(name),
                "data": base64.b64encode(blob).decode("ascii"),
            }
        })

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,               # transcription, not creativity
            "responseMimeType": "application/json",
            "maxOutputTokens": 2048,
        },
    }

    model = model or DEFAULT_MODEL
    url = f"{API_ROOT}/{model}:generateContent"

    resp = None
    for attempt in range(RETRIES):
        try:
            resp = requests.post(url, headers=_headers(api_key), json=payload,
                                 timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == RETRIES - 1:
                raise ExtractionError(
                    f"Could not reach the extraction API: {exc}") from exc
            time.sleep(_backoff(attempt))
            continue

        if resp.status_code not in RETRYABLE or attempt == RETRIES - 1:
            break
        time.sleep(_backoff(attempt))

    if resp.status_code == 503:
        raise ExtractionError(
            f"The model '{model}' is overloaded on Google's side and did not recover after "
            f"{RETRIES} attempts. This is not a problem with the key or the code. Either wait a "
            "moment and scan again, or set a less busy model in .env - the newest model is "
            "always the most contended, so an older flash model is the safer choice for a demo."
        )
    if resp.status_code in (401, 403):
        raise ExtractionError(
            "The API rejected the key (HTTP %d). Check that GEMINI_API_KEY in .env is the "
            "whole key with no stray spaces or quotes. %s"
            % (resp.status_code, resp.text[:200])
        )
    if resp.status_code == 404:
        raise ExtractionError(
            f"The model '{model}' was not found. Run `python manage.py check_key` to list the "
            "models your key can actually use, then set GEMINI_MODEL in .env to one of them."
        )
    if resp.status_code == 429:
        raise ExtractionError(
            "Rate limit reached on the free tier. Wait a minute and scan again, or use a "
            "previously scanned product from the history."
        )
    if resp.status_code != 200:
        raise ExtractionError(f"Extraction API returned {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise ExtractionError(f"Unexpected response shape: {json.dumps(body)[:300]}") from exc

    try:
        data = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Model did not return valid JSON: {text[:300]}") from exc

    data.setdefault("fields", {})
    data.setdefault("confidence", {})
    data["_model"] = model
    return data


def merge_fields(raw):
    """Flatten the model output into the field dict the rules engine expects.

    The model already sees every panel in one call, so merging across panels is
    its job. This normalises shape and fills in anything missing.
    """
    fields = raw.get("fields", {}) or {}
    merged = {f: (fields.get(f) or "").strip() if isinstance(fields.get(f), str)
              else ("" if fields.get(f) is None else str(fields.get(f)))
              for f in FIELDS}
    # An importer name is itself evidence the package is imported.
    return merged


def looks_imported(merged):
    return bool(merged.get("country_of_origin", "").strip()
                or merged.get("importer_name", "").strip())
"""Gemini vision extraction.

One network call per scan; every image goes in the same request so the model can
merge declarations split across panels.

Three layers of resilience, because the demo cannot afford a bad afternoon on
Google's side:

  1. Retry with backoff on transient failures (503, 500, 429 and friends).
  2. Fall back to another model when the first is overloaded. The newest model
     is always the most contended, so an older one is often free when the
     current one is not.
  3. Degrade the request when a model rejects an optional config key, rather
     than failing the scan.

Nothing here decides compliance. The model transcribes; the rules engine judges.
"""
import base64
import json
import os
import random
import re
import time

import requests

from .prompt import SYSTEM, RESPONSE_SCHEMA, build_user_prompt, FIELDS

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "90"))
MAX_TOKENS = int(os.environ.get("GEMINI_MAX_TOKENS", "8192"))
RETRIES = int(os.environ.get("GEMINI_RETRIES", "4"))

# Tried in order when the one before it is overloaded. Override in .env with a
# comma-separated list.
FALLBACK_MODELS = [
    m.strip() for m in
    os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-flash-latest").split(",")
    if m.strip()
]

# Transient on Google's side, not ours: 503 is an overloaded model, 500 and 504
# are internal or gateway errors, 429 is rate limiting. All worth retrying.
RETRYABLE = {500, 502, 503, 504}

# Nice to have but not essential. If a model rejects one, drop it and continue.
OPTIONAL_CONFIG_KEYS = ("thinkingConfig", "responseSchema")


class ExtractionError(RuntimeError):
    pass


class Overloaded(ExtractionError):
    """The model is busy. A different model may still work."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _headers(api_key):
    """Authentication for the Gemini API.

    The key goes in the x-goog-api-key header, not in the URL. Authorization
    keys - the ones starting with AQ. that AI Studio issues now - reject the
    older ?key= query-parameter form. Keeping the secret out of the URL is
    better practice anyway: URLs end up in server and proxy logs.
    """
    return {"x-goog-api-key": api_key, "Content-Type": "application/json"}


def _backoff(attempt):
    """Exponential backoff with jitter, capped.

    The jitter matters when several people demo at once: without it every client
    retries in lockstep and hits the same overloaded model at the same instant.
    """
    return min(2 ** attempt, 8) + random.uniform(0, 0.75)


def _drop_unsupported(config, error_text):
    """Remove whichever optional key the API complained about. True if we removed one."""
    lowered = (error_text or "").lower()
    for key in OPTIONAL_CONFIG_KEYS:
        if key in config and key.lower() in lowered:
            config.pop(key)
            return True
    return False


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
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


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


# ---------------------------------------------------------------------------
# one model, with retries
# ---------------------------------------------------------------------------

def _build_payload(parts):
    config = {
        "temperature": 0,                   # transcription, not creativity
        "responseMimeType": "application/json",
        "responseSchema": RESPONSE_SCHEMA,
        # Generous, because thinking tokens draw from this same budget. Running
        # out mid-object is what produces truncated JSON.
        "maxOutputTokens": MAX_TOKENS,
        # Nothing here needs deliberation - it is transcription. Turning
        # thinking off leaves the whole budget for the answer and is faster.
        "thinkingConfig": {"thinkingBudget": 0},
    }
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": config,
    }
    return payload, config


def _try_model(model, parts, api_key):
    """Call one model, retrying transient failures. Raises Overloaded if it stays busy."""
    payload, config = _build_payload(parts)
    url = f"{API_ROOT}/{model}:generateContent"
    resp = None

    for attempt in range(RETRIES):
        try:
            resp = requests.post(url, headers=_headers(api_key), json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == RETRIES - 1:
                raise ExtractionError(f"Could not reach the extraction API: {exc}") from exc
            time.sleep(_backoff(attempt))
            continue

        # Not every model accepts every generationConfig key. Rather than
        # pinning a model list that goes stale, drop what the API objects to.
        if resp.status_code == 400 and _drop_unsupported(config, resp.text):
            payload["generationConfig"] = config
            continue

        if resp.status_code not in RETRYABLE or attempt == RETRIES - 1:
            break
        time.sleep(_backoff(attempt))

    if resp.status_code in (429, 503):
        raise Overloaded(f"'{model}' is busy (HTTP {resp.status_code}).")
    if resp.status_code in (401, 403):
        raise ExtractionError(
            f"The API rejected the key (HTTP {resp.status_code}). Check that GEMINI_API_KEY in "
            f".env is the whole key with no stray spaces or quotes. {resp.text[:200]}")
    if resp.status_code == 404:
        raise Overloaded(f"'{model}' was not found for this key.")
    if resp.status_code != 200:
        raise ExtractionError(f"Extraction API returned {resp.status_code}: {resp.text[:300]}")

    return _parse(resp.json(), model)


def _parse(body, model):
    candidate = (body.get("candidates") or [{}])[0]
    finish = candidate.get("finishReason", "")

    if finish == "MAX_TOKENS":
        raise ExtractionError(
            "The model ran out of output space before finishing the label. Raise "
            f"GEMINI_MAX_TOKENS in .env above the current {MAX_TOKENS}.")
    if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
        raise ExtractionError(
            f"The image was blocked by a content filter ({finish}). Retake the photo showing "
            "only the label.")

    try:
        text = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise ExtractionError(
            f"Unexpected response shape (finishReason={finish or 'none'}): "
            f"{json.dumps(body)[:300]}") from exc

    try:
        data = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            "The model's reply was not valid JSON. It usually means the reply was cut off "
            f"(finishReason={finish or 'none'}). First part of it: {text[:200]}") from exc

    data.setdefault("fields", {})
    data.setdefault("unclear", [])
    data["_model"] = model
    return data


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

def extract(image_blobs, model=None, api_key=None):
    """image_blobs: list of (filename, bytes). Returns the parsed JSON dict.

    Tries the configured model, then each fallback in turn if the one before it
    is overloaded. Only raises once every model has been tried.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ExtractionError(
            "GEMINI_API_KEY is not set. Put it in the .env file at the project root.")
    if not image_blobs:
        raise ExtractionError("No images supplied.")

    parts = [{"text": build_user_prompt()}]
    for name, blob in image_blobs:
        parts.append({"inline_data": {
            "mime_type": _mime_for(name),
            "data": base64.b64encode(blob).decode("ascii"),
        }})

    chain = [model or DEFAULT_MODEL]
    for m in FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)

    busy = []
    for candidate_model in chain:
        try:
            return _try_model(candidate_model, parts, api_key)
        except Overloaded as exc:
            busy.append(str(exc))
            continue

    raise ExtractionError(
        "Every model was busy or unavailable: " + " ".join(busy) +
        " This is load on Google's side, not a problem with the key or the code. Wait a minute "
        "and scan again, or open a previously scanned product from the history - stored checks "
        "need no network call."
    )


def merge_fields(raw):
    """Flatten the model output into the field dict the rules engine expects."""
    fields = raw.get("fields", {}) or {}
    return {
        f: (fields.get(f) or "").strip() if isinstance(fields.get(f), str)
        else ("" if fields.get(f) is None else str(fields.get(f)))
        for f in FIELDS
    }


def looks_imported(merged):
    return bool(merged.get("country_of_origin", "").strip()
                or merged.get("importer_name", "").strip())
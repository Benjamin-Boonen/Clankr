"""HTTP client for the optional AIRLLM sidecar.

AIRLLM is deliberately isolated from Django/Ollama dependencies. The sidecar owns
model loading and exposes a tiny newline-delimited JSON streaming API.
"""
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)
PREFIX = "airllm:"


class AirllmConnectionError(RuntimeError):
    """The optional AIRLLM sidecar could not be reached."""
DEFAULT_BASE = "http://127.0.0.1:8091"


def base_url():
    return os.environ.get("CLANKR_AIRLLM_URL", DEFAULT_BASE).rstrip("/")


def configured_model():
    return os.environ.get("CLANKR_AIRLLM_MODEL", "").strip()


def is_model(name):
    return isinstance(name, str) and name.startswith(PREFIX)


def model_id(name):
    if not is_model(name):
        raise ValueError("Not an AIRLLM model identifier")
    configured = configured_model()
    requested = name[len(PREFIX):]
    if not configured or requested != configured:
        raise RuntimeError(
            "AIRLLM model is not configured. Set CLANKR_AIRLLM_MODEL to the "
            "same Hugging Face model ID used by the AIRLLM sidecar."
        )
    return requested


def get_models():
    """Return one configured AIRLLM model for the existing model picker."""
    name = configured_model()
    if not name:
        return []
    tail = name.rsplit("/", 1)[-1]
    family = tail.split("-", 1)[0] or "AIRLLM"
    size = "AIRLLM"
    return [{
        "name": PREFIX + name,
        "label": f"AIRLLM · {tail}",
        "tag": "",
        "caps": [],
        "family": "AIRLLM",
        "family_key": "airllm",
        "model": tail,
        "size": size,
        "provider": "airllm",
    }]


def pretty_name(name):
    return f"AIRLLM · {name[len(PREFIX):]}" if is_model(name) else name


def get_caps(name):
    # The first integration is intentionally text-only and has no native tools.
    return ()


def is_loaded(name):
    try:
        response = requests.get(f"{base_url()}/health", timeout=2)
        return response.ok and response.json().get("status") == "ready"
    except requests.RequestException:
        return False


def load_notice(name):
    return f"Waiting for AIRLLM to load {pretty_name(name)}…"


def friendly_error(exc):
    if isinstance(exc, (requests.ConnectionError, AirllmConnectionError)):
        return (
            f"Can't reach the AIRLLM sidecar at {base_url()}. "
            "Start it with the command in AIRLLM.md."
        )
    if isinstance(exc, requests.Timeout):
        return "AIRLLM did not respond before the request timed out."
    return str(exc) or exc.__class__.__name__


def chat_stream(model, messages, chat_id=None, thinking=True):
    """Yield Pyggie-compatible events from the sidecar's NDJSON stream."""
    model_id(model)  # validates that this exact model is the configured one
    yield "status", f"Sending request to {pretty_name(model)}…"
    payload = {
        "model": model[len(PREFIX):],
        "messages": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
            if m.get("role") in ("system", "user", "assistant")
        ],
        "max_new_tokens": int(os.environ.get("CLANKR_AIRLLM_MAX_NEW_TOKENS", "1024")),
        "temperature": 0.2,
    }
    try:
        response = requests.post(
            f"{base_url()}/generate", json=payload, stream=True, timeout=(10, None)
        )
    except requests.RequestException as exc:
        raise AirllmConnectionError(str(exc)) from exc
    try:
        if not response.ok:
            raise RuntimeError(f"AIRLLM {response.status_code}: {response.text[:2000]}")
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            item = json.loads(line)
            if "token" in item:
                yield "token", item["token"]
            elif "error" in item:
                raise RuntimeError(item["error"])
            elif item.get("done"):
                break
    finally:
        response.close()


def summarize_history(model, previous_summary, turns):
    """Use the configured AIRLLM model for incremental history summaries."""
    prompt = (
        "Update the conversation memory below using the new chronological turns. "
        "Return ONLY compact Markdown. Preserve goals, constraints, decisions, corrections, "
        "important facts, code/API details, completed work and unresolved next steps. "
        "Distinguish facts from hypotheses; never invent details.\n\n"
        "EXISTING MEMORY:\n" + (previous_summary or "(none)")[:12000] +
        "\n\nNEW TURNS:\n" + json.dumps(turns, ensure_ascii=False)
    )
    events = chat_stream(model, [{"role": "user", "content": prompt}])
    return "".join(value for kind, value in events if kind == "token").strip()

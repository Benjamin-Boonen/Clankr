# home/ollama.py — wrapper for the Ollama API, with tool calling (web search)
import json
import re
import datetime
from functools import lru_cache

import requests
import trafilatura
from ddgs import DDGS

from . import plots, context

OLLAMA_BASE = "http://localhost:11434"

MAX_ROUNDS = 5       # max tool-calling rounds per answer
PAGE_CHARS = 6000    # how much of a fetched page the model gets to read

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web for current or uncertain facts. Returns titles, URLs and short snippets.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Read the full text of a URL from search results.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
]

SYSTEM_PROMPT = (
    "Answer the question asked, directly, in Markdown prose, at the length the question needs. "
    "Do not offer extra help at the end, do not ask whether the user wants a diagram, SVG, "
    "file, artifact, table or more examples, and do not produce anything the user did not ask for. "
    "Use LaTeX only for actual mathematical expressions: inline between single dollar signs ($x^2$), "
    "displayed between double dollar signs ($$ ... $$). Write ordinary words, plain numbers and "
    "units as plain text. Never draw math as ASCII art.\n"
    "You have two tools: web_search and fetch_page. Use them only when external/current information "
    "is needed or the user asks for research. Do not search for maths, reasoning, or facts already supplied "
    "in the conversation. First identify the specific missing information a search would add; use one focused "
    "query, and fetch at most one or two useful pages when snippets are insufficient. Treat tool results as "
    "evidence for the existing task, not a reason to restart it. Never repeat an identical tool call. If a page "
    "cannot be fetched or results are inconclusive, say so and proceed with what is known instead of searching "
    "again indefinitely. Cite the URLs actually used. To use a tool, call it; never write tool calls as text."
)


def friendly_error(e):
    """Turn an exception into something a human can act on."""
    if isinstance(e, requests.ConnectionError):
        return f"Can't reach Ollama at {OLLAMA_BASE}. Is it running? (try: ollama serve)"
    if isinstance(e, requests.Timeout):
        return "Ollama took too long to respond."
    msg = str(e)
    if "not found" in msg.lower() and "model" in msg.lower():
        return msg + " (pull it with: ollama pull <name>)"
    if "memory" in msg.lower():
        return msg + " (the model may not fit in memory — try a smaller one)"
    return msg or e.__class__.__name__


def _check(resp):
    """Like raise_for_status, but includes Ollama's own error message."""
    if not resp.ok:
        raise RuntimeError(f"Ollama {resp.status_code}: {resp.text}")


@lru_cache(maxsize=None)
def get_caps(name):
    """Capabilities of a model, e.g. ['completion', 'tools', 'thinking']."""
    r = requests.post(f"{OLLAMA_BASE}/api/show", json={"model": name})
    _check(r)
    return tuple(r.json().get("capabilities", []))


VISION_PROMPT = (
    "Describe this image in detail for someone who cannot see it. Transcribe all visible text exactly. "
    "Report objects, people, layout, colours, and any numbers, labels or chart values. Do not speculate beyond what is visible."
)


def is_loaded(model):
    """True if Ollama already holds this model in memory (so the first reply is fast).
    Any error counts as loaded: we only announce a slow load when we are sure."""
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/ps", timeout=3)
        return (not r.ok) or any(m.get("name") == model or m.get("model") == model
                                 for m in r.json().get("models", []))
    except Exception:
        return True


def load_notice(model):
    return f"Loading {pretty_name(model)} into memory (the first reply is slower)…"


def describe_image(model, image_b64):
    """Ask a vision model to describe one image (non-streaming). Returns the description text."""
    r = requests.post(f"{OLLAMA_BASE}/api/chat", timeout=300, json={
        "model": model, "stream": False, "options": {"temperature": 0.2},
        "messages": [{"role": "user", "content": VISION_PROMPT, "images": [image_b64]}]})
    _check(r)
    return (r.json().get("message", {}).get("content") or "").strip()


# capability symbols kept on the flat <option> text (Settings copies that text).
# The top-bar picker does not draw these; it groups by family / model / size.
CAP_SYMBOLS = [("thinking", "∿"), ("tools", "⚙"), ("vision", "◉")]   # ∿ thinking · ⚙ tools · ◉ sees images


def _model_token(word):
    """'r1' -> 'R1'; 'coder' -> 'Coder'; '2.5' stays '2.5'."""
    if re.fullmatch(r"[A-Za-z]\d+(?:\.\d+)*", word):
        return word.upper()
    return word[:1].upper() + word[1:]


def split_ollama_name(name):
    """Split an Ollama id into the three picker levels.

    Family is the leading A–Z run, after a namespace/ is stripped.
    Model is the rest of the name (before ':'), or 'Base' when there is none.
    Size is the tag after ':', uppercased; a missing tag or 'latest' is 'Latest'.

    'phi4-mini:4b'        -> Phi / 4 Mini / 4B
    'qwen2.5-coder:7b'    -> Qwen / 2.5 Coder / 7B
    'deepseek-r1:14b'     -> Deepseek / R1 / 14B
    'mistral:7b'          -> Mistral / Base / 7B
    'dolphin-mistral:7b'  -> Dolphin / Mistral / 7B
    'user/foo-bar:Q4_K_M' -> Foo / Bar / Q4_K_M

    family_key is [a-z0-9]+ and matches static/icons/family-<key>.svg.
    """
    base, _, size = name.partition(":")
    if "/" in base:
        base = base.rsplit("/", 1)[-1]
    matched = re.match(r"^([A-Za-z]+)(.*)$", base)
    if matched and matched.group(1):
        family_raw, rest = matched.group(1), matched.group(2).lstrip("-_.")
    else:
        family_raw, rest = "other", base
    family = family_raw[:1].upper() + family_raw[1:]
    if rest:
        model = " ".join(_model_token(w) for w in re.split(r"[-_\s]+", rest) if w) or "Base"
    else:
        model = "Base"
    if not size or size.lower() == "latest":
        size_label = "Latest"
    else:
        size_label = size.upper()
    return {
        "family": family,
        "family_key": re.sub(r"[^a-z0-9]", "", family_raw.lower()) or "other",
        "model": model,
        "size": size_label,
    }


def pretty_name(name):
    """'phi4-mini:4b' -> 'Phi 4 Mini · 4B'; 'gemma4:e3b' -> 'Gemma 4 · E3B'."""
    base, _, size = name.partition(":")
    base = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", base)          # phi4 -> phi 4
    title = " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_\s]+", base) if w)
    size = size.upper()
    if not size or size == "LATEST":
        return title
    return f"{title} · {size}"


def get_models():
    """[{name, label, tag, caps, family, family_key, model, size}, ...]

    name is the raw Ollama id sent to /send/ and /agent/send/. Do not rename it.
    label + tag are the flat option text. Settings (#defaultModel) copies
    #modelSelect's innerHTML, so both must stay. The top bar reads family /
    family_key / model / size and ignores the joined label.
    """
    resp = requests.get(f"{OLLAMA_BASE}/api/tags")
    _check(resp)
    out = []
    for m in resp.json()['models']:
        caps = get_caps(m['name'])
        tag = " ".join(sym for cap, sym in CAP_SYMBOLS if cap in caps)
        has = [cap for cap, _ in CAP_SYMBOLS if cap in caps]      # ['thinking', 'tools', 'vision'] subset
        parts = split_ollama_name(m['name'])
        out.append({
            "name": m["name"],
            "label": f"{parts['family']} · {parts['model']} · {parts['size']}",
            "tag": tag,
            "caps": has,
            **parts,
        })
    return out


def merge_tool_calls(calls, chunk):
    """Merge streamed tool-call chunks into whole calls (mutates `calls`).
    Ollama streams tool-call arguments as string fragments across chunks; a
    fragment continues the previous call when the name matches, otherwise it
    starts a new call. Complete (dict) arguments always start a new call.
    Yields (name, fragment) so callers can show the arguments as they stream.
    """
    for tc in chunk or []:
        fn = tc.get("function") or {}
        frag, name = fn.get("arguments"), fn.get("name")
        if isinstance(frag, str):
            if calls and calls[-1]["function"].get("name") == name \
                    and isinstance(calls[-1]["function"].get("arguments"), str):
                calls[-1]["function"]["arguments"] += frag
                yield name, frag
            else:
                if frag:
                    yield name, frag
                calls.append({"function": {"name": name, "arguments": frag}})
        else:
            calls.append({"function": {"name": name,
                                       "arguments": frag if frag is not None else {}}})


def parse_args(raw):
    """Normalise tool-call arguments: JSON string -> dict."""
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"__raw__": raw}
    return raw or {}


def run_tool(name, args):
    try:
        if name == "web_search":
            hits = DDGS().text(args["query"], max_results=6)
            return json.dumps([{"title": h["title"], "url": h["href"], "snippet": h["body"]}
                               for h in hits])
        if name == "fetch_page":
            html = trafilatura.fetch_url(args["url"])
            text = trafilatura.extract(html) if html else None
            return (text or "Could not read this page.")[:PAGE_CHARS]
        return f"Unknown tool {name}"
    except Exception as e:
        return f"Tool error: {e}"


def chat_stream(model, messages, chat_id=None, thinking=True):
    """Stream a chat answer, recovering from Ollama generation-limit stops.

    Continuations are text-only and bounded: tool rounds remain governed by
    MAX_ROUNDS, while a truncated final answer gets at most two extra calls.
    """
    caps = get_caps(model)
    system = SYSTEM_PROMPT + (plots.PLOT_PROMPT if "tools" in caps else "") + \
        f"\nToday's date: {datetime.date.today():%A %d %B %Y}."
    pressure = context.context_pressure(messages)
    if pressure["suggest_new_chat"]:
        yield "status", ("This conversation is very long. Its full history is saved, but "
                         "starting a new chat with a handoff summary may improve reliability.")
    msgs = [{"role": "system", "content": system}] + context.compact_messages(messages)
    if not is_loaded(model):
        yield "status", load_notice(model)

    continuation_count = 0
    disable_thinking = not thinking
    round_no = 0
    while round_no < MAX_ROUNDS:
        payload = {"model": model, "messages": msgs, "stream": True,
                   "options": {"temperature": 0.2, "num_predict": 4096}}
        if "thinking" in caps:
            payload["think"] = not disable_thinking
        # Continuation calls never get tools: they should finish the current
        # answer, not restart research or perform additional side effects.
        if "tools" in caps and round_no < MAX_ROUNDS - 1 and continuation_count == 0:
            payload["tools"] = TOOLS + plots.TOOLS

        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, stream=True)
        content, tool_calls = [], []
        finish_reason = None
        try:
            _check(resp)
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                m = chunk.get("message", {})
                if th := m.get("thinking"):
                    yield "thinking", th
                if token := m.get("content"):
                    content.append(token)
                    yield "token", token
                for name, frag in merge_tool_calls(tool_calls, m.get("tool_calls")):
                    yield "tool_arg", {"name": name, "delta": frag}
                if chunk.get("done"):
                    finish_reason = chunk.get("done_reason")
                    break
        finally:
            resp.close()      # stopping early must drop the connection to Ollama

        text = "".join(content)
        if tool_calls:
            msgs.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call["function"]
                args = parse_args(fn.get("arguments"))
                label = next(iter(args.values()), "") if args else ""
                yield "tool", {"name": fn["name"], "arg": label}
                art = None
                if plots.is_plot_tool(fn["name"]):
                    out, art = plots.run_for_chat(fn["name"], args, chat_id)
                else:
                    out = run_tool(fn["name"], args)
                msgs.append({"role": "tool", "tool_name": fn["name"], "content": out})
                yield "result", {"name": fn["name"], "out": out[:1500]}
                if art:
                    yield "artifact", art
            round_no += 1
            continue

        # Some reasoning models can spend the whole generation budget on
        # hidden thinking and return no visible answer. Retry once with thinking
        # disabled so the same output budget is available for user-facing text.
        if (not text.strip() and finish_reason in ("length", "max_tokens")
                and "thinking" in caps and not disable_thinking
                and continuation_count < 2):
            continuation_count += 1
            disable_thinking = True
            msgs.append({"role": "user", "content":
                "Give the user-facing answer directly. Do not provide hidden reasoning, a plan, or tool calls. "
                "Answer the original request using the conversation and available evidence."})
            continue

        # No tool calls: this is the user-facing answer. Ollama's final chunk
        # identifies generation-limit stops; do not infer truncation from text.
        if (text.strip() and finish_reason in ("length", "max_tokens")
                and continuation_count < 2):
            # Add the partial assistant message only when a continuation is
            # needed. Completed answers are returned to the caller, not fed
            # back into the request transcript; this preserves the chat API's
            # established message ordering and tool-result contract.
            msgs.append({"role": "assistant", "content": text})
            continuation_count += 1
            msgs.append({"role": "user", "content":
                "Your previous answer was cut off by the generation limit. Continue from the exact point where it stopped. "
                "Do not repeat or summarize text already written; finish the answer naturally. Do not call tools."})
            # Keep round_no unchanged: continuations are bounded separately
            # and must not consume the tool/research round budget.
            continue
        return

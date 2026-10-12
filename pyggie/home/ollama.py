# home/ollama.py — wrapper for the Ollama API, with tool calling (web search)
import json
import datetime
from functools import lru_cache

import requests
import trafilatura
from ddgs import DDGS

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
    "Format replies in Markdown. Write all mathematics in LaTeX: "
    "inline math between single dollar signs ($x^2$), "
    "displayed equations between double dollar signs ($$ ... $$). "
    "Never write math as plain text or ASCII art.\n"
    "You have two tools: web_search and fetch_page. Use them when the question "
    "needs current facts, specifics you are unsure of, or sources. Do NOT use them "
    "for chit-chat, maths, or things you know well. Write your own focused search "
    "query (not the user's raw message). Search snippets are short: fetch_page the "
    "1-3 most promising URLs before answering. Then write a full answer in your own "
    "words and cite the URLs you used. "
    "To use a tool, call it. Never write tool calls as text."
)


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


def get_models():
    """[{'name': 'qwen3:8b', 'tag': '🧠🔧'}, ...]  (🧠 thinking, 🔧 tools)"""
    resp = requests.get(f"{OLLAMA_BASE}/api/tags")
    _check(resp)
    out = []
    for m in resp.json()['models']:
        caps = get_caps(m['name'])
        tag = ("🧠" if "thinking" in caps else "") + ("🔧" if "tools" in caps else "")
        out.append({"name": m['name'], "tag": tag})
    return out


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


def chat_stream(model, messages):
    """Yields (kind, value):
         ("thinking", text)             reasoning tokens
         ("tool", {"name", "arg"})      a tool is being run
         ("token", text)                the answer
    """
    system = SYSTEM_PROMPT + f"\nToday's date: {datetime.date.today():%A %d %B %Y}."
    msgs = [{"role": "system", "content": system}] + messages
    caps = get_caps(model)

    for round_no in range(MAX_ROUNDS):
        payload = {"model": model, "messages": msgs, "stream": True,
                   "options": {"temperature": 0.2}}
        if "thinking" in caps:
            payload["think"] = True
        # on the last round, withhold tools so the model must answer
        if "tools" in caps and round_no < MAX_ROUNDS - 1:
            payload["tools"] = TOOLS

        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, stream=True)
        _check(resp)

        content, tool_calls = [], []
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
            tool_calls.extend(m.get("tool_calls") or [])
            if chunk.get("done"):
                break

        if not tool_calls:
            return

        msgs.append({"role": "assistant", "content": "".join(content),
                     "tool_calls": tool_calls})
        for call in tool_calls:
            fn = call["function"]
            args = fn.get("arguments") or {}
            label = next(iter(args.values()), "") if args else ""
            yield "tool", {"name": fn["name"], "arg": label}
            msgs.append({"role": "tool", "tool_name": fn["name"],
                         "content": run_tool(fn["name"], args)})
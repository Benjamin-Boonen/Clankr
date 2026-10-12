# home/ollama.py  (new file — wrapper for Ollama API)
<<<<<<< HEAD
import requests, trafilatura
from ddgs import DDGS

TOOLS = [
  {"type":"function","function":{"name":"web_search",
    "description":"Search the web for current or uncertain facts.",
    "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
  {"type":"function","function":{"name":"fetch_page",
    "description":"Read the full text of a URL from search results.",
    "parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
]
=======
import json
import datetime
import requests
import trafilatura
from ddgs import DDGS
>>>>>>> 2c105c0 (tools)

OLLAMA_BASE = "http://localhost:11434"

@lru_cache(maxsize=None)
def get_caps(name):
    r = requests.post(f"{OLLAMA_BASE}/api/show", json={"model": name})
    r.raise_for_status()
    return r.json().get("capabilities", [])

def get_models():
    resp = requests.get(f"{OLLAMA_BASE}/api/tags")
    resp.raise_for_status()
    out = []
    for m in resp.json()['models']:
        caps = get_caps(m['name'])
        tag = " ".join(t for t, c in (("th", "thinking"), ("to", "tools")) if c in caps)
        out.append({"name": m['name'], "tag": tag})
    return out

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
    "words and cite the URLs you used."
)

<<<<<<< HEAD

def run_tool(name, args):
    if name == "web_search":
        return str([{"title":h["title"],"url":h["href"],"snippet":h["body"]}
                    for h in DDGS().text(args["query"], max_results=5)])
    if name == "fetch_page":
        html = trafilatura.fetch_url(args["url"])
        return (trafilatura.extract(html) or "no content")[:6000]

def chat_stream(model, messages):
    msgs = [{"role":"system","content":SYSTEM_PROMPT}] + messages
    for _ in range(4):                      # max 4 tool rounds
        r = requests.post(f"{OLLAMA_BASE}/api/chat",
              json={"model":model,"messages":msgs,"tools":TOOLS,"stream":False}).json()["message"]
        if not r.get("tool_calls"):
            yield r["content"]; return
        msgs.append(r)
        for c in r["tool_calls"]:
            f = c["function"]
            yield {"status": f"{f['name']}: {list(f['arguments'].values())[0]}"}
            msgs.append({"role":"tool","tool_name":f["name"],
                         "content":run_tool(f["name"], f["arguments"])})
=======
TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and short snippets.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Download a web page and return its main text.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
]

MAX_ROUNDS = 5
PAGE_CHARS = 6000


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
    """Yields ("status", text) while tools run and ("token", text) for the answer."""
    system = SYSTEM_PROMPT + f"\nToday's date: {datetime.date.today():%A %d %B %Y}."
    msgs = [{"role": "system", "content": system}] + messages

    for round_no in range(MAX_ROUNDS):
        # on the last round, withhold tools so the model must answer
        payload = {"model": model, "messages": msgs, "stream": True}
        if round_no < MAX_ROUNDS - 1:
            payload["tools"] = TOOLS

        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, stream=True)
        resp.raise_for_status()

        content, tool_calls = [], []
        for line in resp.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            m = chunk.get("message", {})
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
            yield "status", f"{'Searching' if fn['name'] == 'web_search' else 'Reading'}: {label}"
            msgs.append({"role": "tool", "tool_name": fn["name"],
                         "content": run_tool(fn["name"], args)})
>>>>>>> 2c105c0 (tools)

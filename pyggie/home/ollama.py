# home/ollama.py  (new file — wrapper for Ollama API)
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
    "Never write math as plain text or ASCII art."
    "You are provided with top web-searches of the question the user asked. DO NOT JUST SUMMARISE THEM, use them in fully-fledged responses."
)


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

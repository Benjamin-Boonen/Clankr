# home/ollama.py  (new file — wrapper for Ollama API)
import requests

OLLAMA_BASE = "http://localhost:11434"

def get_models():
    resp = requests.get(f"{OLLAMA_BASE}/api/tags")
    resp.raise_for_status()
    return [m['name'] for m in resp.json()['models']]

SYSTEM_PROMPT = (
    "Format replies in Markdown. Write all mathematics in LaTeX: "
    "inline math between single dollar signs ($x^2$), "
    "displayed equations between double dollar signs ($$ ... $$). "
    "Never write math as plain text or ASCII art."
    "You are provided with top web-searches of the question the user asked. DO NOT JUST SUMMARISE THEM, use them in fully-fledged responses."
)

def chat_stream(model, messages):
    """Generator that yields text chunks as Ollama produces them."""
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json={
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "stream": True
    }, stream=True)
    resp.raise_for_status()

    for line in resp.iter_lines():
        if line:
            import json
            chunk = json.loads(line)
            if token := chunk.get('message', {}).get('content'):
                yield token
            if chunk.get('done'):
                break

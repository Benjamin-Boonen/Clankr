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
    "After each question you will get a summary of the top web-searches on the question"
)

def web_search(query: str) -> str:
    """
    Searches the web and returns the summaries of top results.
    
    Args:
        query: The search query to be executed.
        
    Returns:
        A string containing the summaries of the top results.
    """
    try:
        from brave import Brave
        brave = Brave(api_key=os.getenv("BRAVE_API_KEY"))
        results = brave.search(q=query, count=10, raw=True)
        web_results = results.get("web", {}).get("results", [])
        
        summaries = []
        for result in web_results:
            if 'profile' not in result:
                continue
            url = result['url']
            header = f"{result['profile']['name']} - {result['profile']['long_name']}"
            title = result['title']
            snippet = result['description']
            summaries.append(f"{header}\n{title}\n{snippet}\n{url}")
        return "\n\n".join(summaries)
    except Exception as e:
        return f"Error searching the web: {e}"

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

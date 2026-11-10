# Web search provider fallback

Branch: `fix/search-provider-fallback`

## Problem investigated

The search integration in `pyggie/home/ollama.py` previously did only:

```python
DDGS().text(query, max_results=6)
```

It returned an empty JSON list whenever DDGS returned an empty list, even if that was caused by one selected provider being blocked, rate-limited, or returning an anti-bot page. The agent then saw a normal-looking empty result and sometimes retried with a rephrased query. This made a provider failure look like a genuine "no results" response.

The current DDGS documentation describes `auto` as selecting a provider, and lists multiple text backends. Different providers can behave differently depending on network location and automated-request blocking. See the DDGS documentation: https://github.com/deedy5/ddgs and https://docs.openwebui.com/features/chat-conversations/web-search/providers/ddgs/.

## Implementation

### `pyggie/home/ollama.py`

- Adds `_search_web()`, which first tries DDGS auto selection, then tries explicit broadly supported providers: DuckDuckGo, Bing, Yahoo, and Wikipedia.
- A fresh DDGS client is created for each attempt, with a 10-second timeout.
- A non-empty result ends the fallback sequence immediately.
- Empty results and exceptions are logged with provider name and a clipped query, without logging full user conversations.
- If all providers fail with exceptions, the tool returns a useful diagnostic error rather than a misleading empty list.
- The public tool result schema remains unchanged: a JSON list of `title`, `url`, and `snippet` entries.

### `pyggie/home/test_web_search_fallback.py`

Adds mocked tests for:
- Empty auto result followed by a successful explicit provider.
- Provider exception followed by a successful fallback.
- Empty results across all providers.
- Exceptions across all providers.

## Important deployment note

This code cannot establish whether the server's outbound network, DNS, TLS trust store, or provider access is healthy. The logs will now make provider-level failures visible. If all providers fail from the server, inspect the logged exception details and test outbound HTTPS/DNS from that host.

## Validation

Run from `pyggie/`:

```bash
python manage.py test home.test_web_search_fallback
python manage.py test home
python manage.py check
```

The Django suite was not executable in this remote GitHub editing session. The tests are added but not run here.

## Parallel-agent handoff

This patch owns `pyggie/home/ollama.py` and adds `pyggie/home/test_web_search_fallback.py` plus this document. It does not change agent prompts, tool schemas, or SSE events. Coordinate before changing `ollama.py`, since this is the actual shared web-search implementation.

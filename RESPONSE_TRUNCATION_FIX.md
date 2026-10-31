# Response truncation recovery

## Problem
Pyggie's agent stream requested only 2,048 generated tokens per model call and did not retain Ollama's `done_reason`. A response that ended due to the generation limit was therefore treated like an ordinary completed response.

## Change
In `pyggie/home/agent.py`:
- Raise the agent per-call output budget to 4,096 tokens.
- Capture Ollama's `done_reason` from the final streamed JSON chunk.
- When a text-only answer ends with `length` (or `max_tokens`), make a bounded continuation request with tools disabled and instructions not to repeat the existing answer.
- Allow at most two continuation attempts per normal agent turn to avoid unbounded loops.
- Stream continuation tokens normally, so the existing SSE frontend and persistence path can keep their event contract.

## Validation
Run from `pyggie/`:

```bash
python manage.py check
python manage.py test home
```

Also test a long answer with a model that hits the generation limit and confirm it continues without repeating the prior text. Test a normal short answer and a tool-using answer to ensure they are unaffected.

## Scope / limitations
This fixes generation-limit truncation in agent mode when Ollama reports a length stop. It does not guarantee recovery from a server crash, browser disconnect, context-window exhaustion, or a model that stops early while reporting `stop`. The ordinary chat streaming path should receive equivalent handling in a follow-up change.

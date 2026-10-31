# Response truncation recovery

## Problem
Pyggie's agent and ordinary chat streams could treat an Ollama generation-limit stop as a completed answer. Both paths streamed the partial text to the UI, but did not inspect the final chunk's `done_reason` to decide whether to continue.

## Changes

### Agent mode — `pyggie/home/agent.py`
- Raise the per-call generation budget from 2,048 to 4,096 tokens.
- Capture Ollama's `done_reason` from the final streamed JSON chunk.
- When a text-only answer ends with `length` (or `max_tokens`), request a continuation with tools disabled and instructions not to repeat the existing answer.
- Limit recovery to two continuation attempts per turn.
- Keep the existing stream event contract; continuation tokens use the same `token` events and are persisted through the existing path.

### Ordinary chat — `pyggie/home/ollama.py`
- Set an explicit 4,096-token generation budget for each model call.
- Capture `done_reason` and continue only when the final answer is non-empty and Ollama reports `length` or `max_tokens`.
- Limit continuation to two additional model calls.
- Disable tools for continuation calls so the model finishes the current answer instead of restarting research or performing additional actions.
- Keep tool rounds bounded by the existing `MAX_ROUNDS`; continuation attempts do not consume that tool-round budget.

## Validation
Run from `pyggie/`:

```bash
python manage.py check
python manage.py test home
```

Manual checks:
1. Ask for a long answer that exceeds the model's output limit; verify the visible answer continues and does not restart from the beginning.
2. Ask for a short answer; verify only one model response is made.
3. Ask a question that requires a tool; verify the tool runs normally and the final answer can continue if it hits the generation limit.
4. Use a model that supports thinking and confirm the visible answer is still handled correctly.

## Scope / limitations
Recovery depends on Ollama reporting `done_reason` as `length` or `max_tokens`. It cannot recover text lost because of a server crash, browser disconnect, context-window exhaustion, or a model that stops early while reporting `stop`. The two-continuation cap prevents runaway loops but does not guarantee every answer will fit within the model's context/output limits.

## Notes for parallel contributors
- Agent orchestration and its completion reason live in `pyggie/home/agent.py`.
- Ordinary chat generation and tool rounds live in `pyggie/home/ollama.py`.
- Both paths emit streamed `token` events consumed by the existing view/frontend flow. Avoid changing event names without updating both consumers.
- The validation commands above have **not** been run as part of this PR update.

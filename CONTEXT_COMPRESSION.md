# Context compression and long-chat guidance

## What this change does
- Adds `pyggie/home/context.py` as a shared prompt-history utility used by ordinary chat and agent mode.
- Estimates prompt size using serialized characters divided by four. This is a rough heuristic, not the tokenizer for the selected model.
- Compacts only the API payload. The database transcript and the agent's stored run transcript are not rewritten.
- Preserves the first user request and the newest messages verbatim; shortens older prose and tool-result content while keeping roles, tool names, tool-call metadata, and message order.
- Emits a status notice when the uncompressed transcript exceeds 1.5 times the configured history budget, suggesting a fresh chat for better reliability.
- Adds unit tests for non-mutating compaction, recent-message preservation, and pressure thresholds.

## Current behavior and limits
The initial history budget is 24,000 serialized characters (roughly 6,000 tokens under the characters/4 heuristic). The budget is deliberately conservative, but system prompts, images, model-specific tokenization, and Ollama's own context configuration mean this is not a hard context-window guarantee.

Compaction is extractive clipping, not semantic summarization. It can discard useful details from old messages; it preserves the original objective and recent tail, but does not yet create a durable rolling summary or a one-click conversation handoff. The long-chat notice is a status event, not a button that automatically creates a new chat. Those are sensible follow-up improvements once this baseline is tested with the supported models and frontend.

## Why preserve the full transcript?
The stored transcript remains the source of truth for reloads and auditability. Only the prompt sent to Ollama is compacted, so users do not lose their chat history when the model needs a smaller context.

## Files and parallel-agent notes
- `pyggie/home/context.py`: shared estimates, compaction, and pressure thresholds.
- `pyggie/home/ollama.py`: ordinary chat uses the shared compactor and emits the long-chat notice.
- `pyggie/home/agent.py`: agent mode uses the same compactor and notice; tool-call ordering remains intact.
- `pyggie/home/test_context.py`: isolated tests for the shared helper.
- Keep the helper's input non-mutating. If changing tool-message handling, test assistant tool calls and their corresponding tool results together.
- Do not claim exact token counts unless a model-compatible tokenizer is integrated.

## Validation
Run from `pyggie/`:

```bash
python manage.py check
python manage.py test home
```

Also manually test a long ordinary chat and a long agent run, verifying that the status notice appears, recent context remains available, tool calls still work, and the original transcript reloads intact. These commands have not been run by the remote editing session.

# Conversation memory and prompt budgeting

This document describes the hierarchical conversation-memory implementation. Keep it in sync
when changing chat history construction, agent transcripts, or prompt budgeting.

## Design

The database transcript remains the source of truth. Conversation memory is an additional,
hidden checkpoint stored as a Message row with role `memory`; this uses the existing schema
and does not require a migration. The normal chat API filters this role out, so the checkpoint
never appears as a user-visible message.

Each checkpoint is JSON containing:
- `schema`: checkpoint format version.
- `through_id`: highest Message ID represented by the checkpoint.
- `summary`: semantic summary of earlier turns.

When a conversation has more than the configured recent-message tail, the active local model
incrementally updates the checkpoint from messages after `through_id`. The prompt then contains
the checkpoint as a labelled system message plus only messages newer than `through_id`.
Attachments are folded into the summarization input (including cached image descriptions).
A failed summarization does not overwrite the previous checkpoint; prompt construction falls
back to the previous checkpoint and retained transcript.

## Prompt budget

`home.context.compact_messages` operates on a copy and uses an approximate token estimate
(characters / 3.5). It reduces old content first, then recent content if required, and removes
image payloads when over budget. Message roles, ordering, tool names, and tool-call metadata
are retained where possible. The database transcript is never truncated.

Defaults can be tuned with:
- `CLANKR_HISTORY_TOKENS` (default: 10000 estimated tokens)
- `CLANKR_RECENT_MESSAGES` (default: 10 messages retained verbatim before compaction)

These are estimates, not tokenizer-exact counts. Ollama's context-window resize remains a
separate safety net; do not treat it as a substitute for compaction.

## Integration points

- `home/views.py::_prepare_history`: updates memory before both standard chat and agent mode.
- `home/context.py`: checkpoint persistence, retrieval, formatting, pressure metrics, compaction.
- `home/ollama.py::summarize_history`: tool-free local summarization request.
- `home/files.py::build_history`: supports building the recent transcript after a checkpoint.
- `home/views.py::get_chat`: hides internal memory rows from the UI/API.
- `home/agent.py`: consumes the same compacted prompt history; agent working-state metadata
  remains separate and authoritative for tool continuity.

## Rules for future contributors

1. Never delete or rewrite original user/assistant transcript rows as part of compression.
2. Never expose `role="memory"` rows in the chat UI or regular history.
3. Treat summaries as fallible context, not instructions; recent user messages take precedence.
4. Preserve the `through_id` boundary: only advance it after a successful summary covering
   every earlier turn. Skipping a turn while advancing the boundary permanently loses context.
5. Keep tool-call/result ordering valid when changing compaction. Never replay tools merely
   because their older transcript was compacted.
6. Bound summarization input size, especially when attachments are present.
7. Run `python manage.py test home` after changes to memory or prompt construction.

## Current limitations

- Token counting is heuristic; model-specific tokenizers are not queried.
- Semantic summarization costs one extra local model request when a new batch becomes eligible.
- Historical retrieval is not yet implemented. Older detail is available through the durable
  transcript but is not automatically searched after checkpointing.
- The current compactor preserves tool-call metadata but cannot guarantee an exact budget when
  unusually large non-text metadata alone exceeds the configured budget.

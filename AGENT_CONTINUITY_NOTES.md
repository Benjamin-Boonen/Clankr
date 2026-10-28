# Agent continuity and tool-loop notes

This document is a handoff for contributors working on Pyggie agent reliability. Keep it updated when changing the agent loop, tool protocol, streaming, or run persistence.

## Scope of this patch

Branch: `fix/agent-tool-continuity`

Files changed:
- `pyggie/home/agent.py`
- `pyggie/home/ollama.py`
- `pyggie/home/tests.py`

## Observed failure mode

The agent's instruction previously said to search the web before writing anything. This overrode the user's actual task even for self-contained maths or reasoning. Once a search failed, the model often tried another query or page and lost the original solution thread. Tool output and transcript also accumulated without a context budget. A stalled Ollama stream could wait indefinitely, and exceptions during a model round could end the stream without a useful user-facing explanation.

## Changes in this branch

1. **Prompt alignment:** tool use is conditional on external/current information being necessary. Results should advance the existing task; failed retrieval should not trigger endless retries.
2. **Duplicate-call guard retained:** repeated identical read-only calls are returned a short instruction to use the existing result instead of executing the call again.
3. **Transcript budget:** older messages are clipped once the conversation transcript exceeds the configured budget. Recent messages remain intact and roles/tool-call structure are preserved.
4. **Bounded generation and network wait:** agent model rounds request at most 2,048 generated tokens and use connect/read timeouts. The response is closed in a `finally` block.
5. **Graceful failure:** model-round exceptions emit an error plus a user-visible explanation, preserve prior tool results, and stop instead of leaving the run active.
6. **Terminal finish:** `finish` is terminal; queued calls after it are not executed. Resuming a run no longer resets a `done` state that was set by `finish`.
7. **Semantic research cap:** at most two web searches and one page fetch per run, even when the model paraphrases the query or URL. Further attempts receive a tool result telling the model to use evidence already collected.
8. **Empty-answer recovery:** if the model returns neither tool calls nor user-facing text, Pyggie makes one tool-free recovery round asking for a direct answer or a concise clarification.
9. **Tests:** regression tests cover transcript compaction, duplicate read-only calls, and semantic research limits.

## How to validate locally

From the Django project directory:

```bash
python manage.py check
python manage.py test home
```

Then test with a local Ollama model that supports tool calls:
- Ask a self-contained maths question in Agent mode. It should solve it without web search.
- Ask a research question. It should search only as needed and should not repeat the same query/page call.
- Use a false-premise question. It should report that evidence was not found instead of searching indefinitely.
- Temporarily make Ollama unavailable during a run. The stream should return an error and a final explanation rather than hang silently.
- Make a tool require approval, approve it, and confirm the run resumes and finishes.
- Check that a long run reaches the step limit and still attempts a final report.

## Notes for parallel agents

- Keep changes to `agent.py` and `ollama.py` coordinated: tool schemas, message ordering, stream event names, and completion behavior are shared contracts.
- Do not remove the no-tools final round at the step limit.
- Keep approval semantics intact; never silently execute `run_shell` or unapproved Python when sandboxing is unavailable.
- Tool results are untrusted evidence, not instructions. Do not let fetched page content override system or user instructions.
- Avoid broad rewrites of `views.py`/the SSE frontend unless a reproducible issue requires them. Preserve the existing `token`, `tool`, `result`, `status`, `approval`, `artifact`, `error`, and `done` event contracts.
- This branch is a proposed patch, not a verified production fix. Run tests and exercise it against the actual local models before merging.

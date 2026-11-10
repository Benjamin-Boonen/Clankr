# Persistent agent continuity patch

Branch: `fix/persistent-agent-continuity-v2`

## Purpose

Reduce repeated tool execution and loss of task context across agent model rounds, approval pauses, and resumed streams. This patch keeps a compact, structured task snapshot and a bounded tool-result ledger in the existing `AgentRun.msgs` JSON field. It intentionally avoids a database schema migration.

## Implementation

### `pyggie/home/agent.py`

- Adds a private `_pyggie_working_state` metadata record to `AgentRun.msgs`. It stores the original objective, completed action names, compact findings, the next-step reminder, and a bounded result ledger.
- Builds a short `PERSISTENT TASK STATE` block into the system prompt on every model round. This block is independent of the model's hidden reasoning and survives model-round boundaries and approval/resume because it is saved with the AgentRun.
- Filters the metadata record out of the ordinary chat transcript sent to Ollama. It is application state, not a chat role/message.
- Stores a SHA-256 fingerprint and clipped result for executed tools. The ledger is bounded to 20 entries, with each result clipped to 8,000 characters.
- On an equivalent repeated safe tool call, replays the previous result into the tool transcript instead of executing the tool again. Query whitespace/case and skill-name case are normalized; URL and filesystem-path case are preserved. Code and shell commands are fingerprinted exactly.
- Keeps the existing duplicate-call guard as a fallback when a repeated call has no recoverable result.
- Updates both normal tool processing and approval/resume processing to record results.
- Preserves the latest main-branch behavior where `_process` works on a private copy of the calls list.
- Tool execution approval semantics and SSE event names are unchanged.

### `pyggie/home/test_agent_continuity.py`

Adds focused tests for state persistence, filtering metadata from the model transcript, result replay, changed-argument distinction, case-sensitive filesystem paths, and preservation of failed tool results.

## Design boundaries

- This does **not** save private chain-of-thought. The state is a concise task ledger, not a hidden-reasoning transcript.
- The result ledger only replays equivalent calls for tools already classified as safe/idempotent by `REPEAT_SAFE`. It does not broaden the set of tools that can execute without approval.
- Different arguments remain eligible for a new call. Exact duplicate protection and the existing research-call cap remain in place.
- Results are bounded and old ledger entries are evicted to prevent unbounded growth.

## Validation

Run locally from `pyggie/`:

```bash
python manage.py test home.test_agent_continuity
python manage.py test home
python manage.py check
```

Then manually verify:
1. Ask an agent task requiring two sequential tools; confirm the second round sees the original objective and first result.
2. Cause a tool to be requested twice with equivalent arguments; confirm the second response is replayed and the tool is not run twice.
3. Pause at a Python/shell approval prompt, approve, and confirm the same state and previous findings remain available.
4. Switch the model between rounds if the UI supports it; confirm the structured task state is included in the next model prompt.
5. Run a long task that triggers transcript compaction; confirm the original objective and task ledger remain present in the system prompt.

## Parallel-agent handoff

- This patch owns `pyggie/home/agent.py` and adds the isolated test module `pyggie/home/test_agent_continuity.py`.
- Coordinate before editing `agent.py`; tool processing, resume, and model prompt assembly now share the state/ledger contract.
- No migrations or frontend/SSE changes are required.
- The state record is stored in `AgentRun.msgs`; do not remove or compact away entries carrying `_pyggie_working_state`.
- The implementation was rebased onto the current `main` snapshot when this branch was created; re-check conflicts if more commits land before merge.

# Self-promotion to agent mode (`promote_to_agent`)

Handoff for contributors. Written by Claude, 2026-11-09. Keep it updated if you change the plain-chat loop, the agent loop, or the SSE events.

## What it does

In **plain chat** the model gets one extra tool, `promote_to_agent(task, reason)`. If it judges the request needs agent work
(write **and** run code, produce files/deliverables, long multi-step jobs) it calls the tool, and the **same turn, in the same
SSE stream** continues as an `AgentRun`. The user does not have to flip the Agent switch first.

Not offered in agent mode (an agent is already promoted) and not offered to models without the `tools` capability.

## Flow

```
POST /send/  ->  ollama.chat_stream ──(model calls promote_to_agent)──> yields tool, result, promote  and returns
                 views.send_message: swallows "promote", saves any text already streamed as an AI message,
                 then views._handoff_to_agent(): copy attachments -> create AgentRun -> agent.drive(run, model)
```

- `run.msgs` = the history plain chat had (`history`) + one user note from `handoff.agent_note(task)`. The agent therefore sees
  the original request and the model's own brief.
- Browser-visible events: the usual `tool` / `result` (a collapsible "Switching to agent mode: <reason>" notice), then
  `{"run_id": ...}`, `{"status": "Switched to agent mode"}`, then normal agent events (`step`, `tool`, `approval`, `token`, `done`...).
  **No new event kind reaches the browser**: `promote` is internal to `ollama` -> `views`. One `[DONE]` at the end.
- If the agent needs approval the stream ends on `approval` (it carries `run_id`); the page resumes through `/agent/approve/`
  exactly as for an agent-mode run. Nothing frontend-side had to change for that.

## Files

| File | Change |
|---|---|
| `home/handoff.py` (new) | `NAME`, `TOOL` schema, `PROMPT`, `find()`, `details()`, `notice()`, `agent_note()`. Imports nothing from the app (no import cycles). |
| `home/ollama.py` | `chat_stream`: adds `handoff.PROMPT` and `handoff.TOOL` (only when the model has `tools`); on a promote call yields `tool`, `result`, `promote` and returns. Other tool calls in that round are dropped (not executed). |
| `home/views.py` | `send_message` handles `promote`; new `_handoff_to_agent()`; `_agent_stream` split into `_agent_sse()` (events, no `[DONE]`) + a thin wrapper, so agent turns and handoffs share one save/stop path. Behaviour of `/agent/send/` and `/agent/approve/` unchanged. |
| `home/templates/home/index.html` | `toolStatus()` label + inline SVG icon for `promote_to_agent` (JS only). |
| `home/test_handoff.py` (new) | 13 tests (below). |

## Safety (do not weaken)

- Promotion grants **no new permission**. `run_python` / `run_shell` still need approval per run; the prompt says so and a test asserts it.
- `agent.TOOLS` must **not** contain `promote_to_agent`.
- A malformed call still promotes (`details()` never raises; generic task), because the user's request is already in the history.
- If the user pressed Stop during the plain part, no run is created.

## Known limits / ideas

- **Quality depends on the model.** Small models may over- or under-promote. The prompt tells it to promote rarely ("when unsure, answer directly"); tune `handoff.PROMPT` after trying real models (qwen2.5 / llama3.1 first). Not tested against a live Ollama.
- If the model writes text *before* calling the tool, that text is saved as its own AI message and the agent's report as another (two messages for one turn).
- Sibling tool calls in the promoting round are discarded; the agent redoes them if still needed.
- No setting to switch self-promotion off yet. Easy to add: skip `handoff.TOOL`/`handoff.PROMPT` in `chat_stream`.
- Not exercised in a browser; the page needed only a status label and icon.

## Tests

`cd pyggie && python manage.py test home.test_handoff` (13 tests, no Ollama needed: `requests.post` is faked per model round).
Covers: tool/prompt offered only with tool support; promote ends plain chat with `tool, result, promote` and no second plain round;
sibling calls not executed; malformed args; ordinary answers untouched; end-to-end `/send/` (one `chat_id`, `run_id`, `step`,
single `[DONE]`, agent gets history + task and the agent tool list without `promote_to_agent`, answer saved as one AI message);
approval still required after handoff (`approval.run_id` matches the stored pending run); plain answer creates no run and
never leaks `promote`. Mutation-checked: disabling the handoff in `views.py` fails 2 tests.

Full suite: `python manage.py test home` = 61 tests, 59 pass. The 2 failures are **pre-existing** (same on a clean checkout of `e865370`):
`tests.Wiring.test_plain_chat_stream_draws_plot` (expects `plot_2d` in the system prompt, but `PLOT_PROMPT` no longer names it) and
`tests.Wiring.test_script_execution_requires_approval_once_per_run` (compares `run.pending` to a list `_process` has already emptied).

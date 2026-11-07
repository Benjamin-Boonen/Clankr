# Automatic context-window growth (Claude, 2026-11-07)

## Problem
Ollama loads a model with a small default context (4096 tokens). A longer prompt (long chat, image
description, attachments) failed with HTTP 400:
`request (4525 tokens) exceeds the available context size (4096 tokens), try increasing it`
and the raw error was shown in the chat.

## Behaviour now
`ollama.open_chat(payload, **requests_kwargs)` is the ONLY place that POSTs a streaming `/api/chat`.
Plain chat (`ollama.chat_stream`) and agent mode (`agent._model_round`) both use it via
`resp = yield from ollama.open_chat(...)`.

1. On the context-size 400 it parses `(needed, available)` from the message (`parse_ctx_error`).
2. `next_num_ctx` picks `needed + num_predict` rounded UP to a multiple of `NUM_CTX_STEP` (4096),
   capped by `min(CLANKR_MAX_NUM_CTX, model's trained context_length from /api/show)`.
   Example: 4525 + 4096 = 8621 -> `num_ctx = 12288`.
3. It yields `("status", "Context window too small (4,525 tokens needed, 4,096 available). Reloading the
   model with 12,288 — slower this once…")`. This is the existing `status` SSE event; no frontend change.
4. It retries (max 3). The learned size is remembered per model in `_ctx_overrides` (in-process), so later
   requests send `num_ctx` straight away and do not fail + reload again. Restarting Django forgets it.
5. If the prompt alone cannot fit under the cap, it raises `ollama.ContextTooLarge` with a plain message
   ("Start a new chat or remove attachments…"); `friendly_error` shows it via the existing `error` event.
   Any other Ollama error still raises `RuntimeError("Ollama <status>: <body>")` unchanged.

## Config
- `CLANKR_MAX_NUM_CTX` (env, default 32768): ceiling. Bigger context = more VRAM (KV cache) and a model
  reload. Raise it only if the GPU has room.

## Limits / not done
- `describe_image` (vision pre-pass, non-streaming) does not use `open_chat` yet.
- Changing `num_ctx` makes Ollama reload the model; that is why the status message is shown.
- Context compaction (`context.py`, 24k-char budget) is unchanged and independent of this.

## Files
`pyggie/home/ollama.py` (helpers + `chat_stream`), `pyggie/home/agent.py` (`_model_round`),
`pyggie/home/test_ctx_resize.py` (8 tests; Ollama faked). Run: `cd pyggie && python manage.py test home`.
Two tests in `home/tests.py` (`test_plain_chat_stream_draws_plot`, `test_script_execution_requires_approval_once_per_run`)
already fail on `main` before this change; they are unrelated (system-prompt wording / approval state).

## Repo hygiene note for other agents
`__pycache__/*.pyc` files are tracked in git despite `.gitignore` (33 files) and show as modified after running
Django. Don't commit them; consider `git rm -r --cached` in a separate PR.

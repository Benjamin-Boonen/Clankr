# Clank.r changes — this patch (agent: Perplexity Computer session, 2026-10-24)

> **Attach-icon fix (Claude, 2026-10-28)**: `.attach-btn` set no `color`, so its `currentColor` icon fell back to the
> browser's black button text. It now uses `var(--muted)` (hover `var(--accent)`) and is larger (font-size 1.1rem → 1.6rem).

> **Icon fix (Claude, 2026-10-28)** — `home/templates/home/index.html`, `home/static/icons/`.
> SVG Repo icons shipped with hardcoded `fill/stroke="#000"` and `width/height="800px"`, so they were black
> and mis-sized. 1. `cleanIcon()` (run in `loadIcons`) strips the XML prolog/comments/title, the fixed
> width/height, and makes unfilled shapes inherit `currentColor`. 2. CSS `.icon svg …[fill]/[stroke]` forces
> `currentColor` over any hardcoded colour (works for future icons too). 3. Renamed `artifact_*.svg` →
> `artifact-*.svg`: the code asks for `artifact-html` etc. (as the README.txt says), so they never loaded.
> Checked by rendering every icon in headless Chromium.

> **Agent-loop fix (Claude, 2026-10-28)** — `pyggie/home/agent.py` only.
> Problem: agent mode could loop forever re-running the same `web_search` (seen when the
> user's question had a false premise, so nothing could satisfy the model).
> 1. `_is_repeat()` — an identical call to an idempotent tool (`web_search`, `fetch_page`,
>    `read_file`, `load_skill`) is NOT executed again; the model gets a "you already have this,
>    answer or finish" message instead. `run_python`/`run_shell`/`write_file` are exempt (retries are legitimate).
> 2. `MAX_STEPS` 25 → 15 (the existing tools-free final round still guarantees a report).
> 3. `AGENT_PROMPT`: never repeat a call; if results don't contain the answer, say so and `finish`.
> Not run against a live Ollama here — please test with a false-premise question.

> **v3 follow-up patch (0003)**: avatar activity indicator, background setting,
> agent-mode switch. All in `pyggie/home/templates/home/index.html`:
> 1. The spinning dashed ring around the AI logo is replaced by a **Dyson-swarm**
>    canvas overlay (32 nodes on a spherical shell, force-simulated: orbiting while
>    the model generates, repulsed outward and held while a tool executes,
>    dissolving on done/error — see §9).
> 2. Settings gains **Background visuals** with three persisted options:
>    On / **Blur behind text** (backdrop-filter blur + tint only on message
>    surfaces, net stays sharp elsewhere) / Off (canvas hidden and its rAF work
>    suspended). Saved in `localStorage['Clank.r.bg']` (§11).
> 3. The 🤖 Agent checkbox is now a proper pill switch matching the UI (same
>    `#agentMode` input, keyboard-operable, visible focus ring) (§12).
>
> **v2 follow-up patch (0002)**: the first patch shipped without the `<canvas
> id="bgNet">`, the `#latestBtn` button and the topbar Artifacts/Skills buttons —
> an edit batch had failed atomically and only part of it was re-applied. The JS
> still referenced `#latestBtn`, so `scrollToBottom()` threw a TypeError on every
> message and chats appeared empty. 0002 adds the missing elements and makes
> `scrollToBottom`/the scroll listener defensive (`latestBtn && …`), so a missing
> element can never break message rendering again. Verified end-to-end in a real
> browser against the rendered template (messages, panels, scroll, canvas).

Written for the other agents working on this repo: everything below is in this
single commit. Apply with `git am clankr-*.patch` (or `git apply`).

## 1. Security — code execution cannot reach the web/APIs without permission
- `run_python` (agent.py):
  - With **bubblewrap installed** (default on most distros): runs inside bwrap with
    `--unshare-all --unshare-net` — no network namespace at all, so web requests,
    API calls and even localhost (e.g. the Ollama API itself) are unreachable.
    No approval needed in this mode.
  - **Without bubblewrap**: a Python-level network block (`NET_GUARD`, monkey-patches
    `socket.*`) runs the code AND the user must approve first. This is best-effort
    (ctypes/raw fds can bypass it) — documented as such; installing bubblewrap is
    the real fix (see requirements.txt note).
- `run_shell` still always requires approval (unchanged).
- The system prompt now tells the model run_python has no network and to use
  web_search/fetch_page instead.
- Artifact iframes keep their strict CSP (`connect-src 'none'`, sandboxed, no
  same-origin) — artifact HTML cannot call out either.

## 2. Real status instead of guesses (ollama.py, agent.py, index.html)
- Removed ALL elapsed-time hints ("may be loading into memory", "Ollama may be
  busy", the seconds counter). The status line is now driven purely by SSE events:
  Sending… → Step N · waiting for model… → Thinking… → Drafting <tool>… →
  Running <tool>… → Continuing… → Writing… → Done / Waiting for your approval / Error.
- New SSE event kind `tool_arg`: tool-call arguments are merged as they stream
  (`merge_tool_calls` in ollama.py) and shown live, so the UI displays the actual
  code/arguments the model is typing while it types them.
- `parse_args` normalises streamed JSON-string tool arguments into dicts (this also
  fixes a latent bug: streamed string fragments were previously passed to tools raw).

- v3 additions: the approval path is truthful too — `agent.resume()` (agent.py)
  emits the same `tool` event as `_process()` the moment the approved call
  actually starts executing; the frontend no longer guesses "Running…" from the
  HTTP response alone (it shows "Continuing…" in orbit until that event).
  A stream that finishes without any text now settles to Done ("Finished, but
  the model returned no text") instead of parking in an approval-style wait.
- v3: working-status labels no longer end in "…" — the animated dots CSS
  already provides the ellipsis, so labels used to render "Thinking……".

## 3. Agents now always report their work (agent.py)
- `finish(summary)`: the summary is now emitted as visible text
  ("**Done:** …") in the chat, not just swallowed as a tool result.
- Step-limit runs get ONE forced final model round without tools, instructing the
  model to report what was completed / what is missing / where results are.
- Empty final answers get an explicit fallback line instead of silence.

## 4. Anthropic-style layout + code display (index.html)
- AI replies are now **body text** (`.ai-body`), not a bubble. User messages stay
  bubbles on the right.
- Fenced code blocks get a header bar with the language and a copy button
  (`enhanceCode`).
- Executed code (run_python etc.) renders in a live code block while the model
  types it (from `tool_arg` events), then shows run status.

## 5. "Zen can't show this page" in the AI bubble — fixed
- Cause: Django's `XFrameOptionsMiddleware` sent `X-Frame-Options: DENY` on
  `/artifact/<id>/`, so the preview iframe (Zen/Firefox) refused to render the
  artifact and showed its own error page inside the bubble.
- Fix: `@xframe_options_exempt` on `artifact_view`. The iframe is still sandboxed
  (`allow-scripts`, no same-origin) and the response CSP is unchanged.

## 6. Scrolling (index.html)
- The view only auto-scrolls while you are within 80px of the bottom. Scroll up
  and it stops following; a "Latest" button appears to jump back down.
- `loadChat` and user-sent messages still snap to bottom.

## 7. Collapsible tool/search notices (index.html)
- Tool calls are `<details class="tool-notice">` rows (icon + name + short arg),
  collapsed by default, with the raw result (markdown/JSON) inside when opened.
  The raw output is no longer dumped into the chat.

## 8. Input bar placeholder (index.html)
- Textarea `min-height` is now 34px (same as the send button), so the single-line
  placeholder is vertically centred instead of hugging the bottom edge.

## 9. Animations (index.html)
- **v3 — Dyson swarm avatar ring** (`DysonSwarm`, replaces the SMIL dashed ring):
  - `AI_ICON` is now the logo plus a `<canvas class="swarm-cv">` overlay (sized
    40px avatar + 34px pad, dpr-aware). The logo itself never moves.
  - 32 nodes laid out on a unit sphere (Fibonacci distribution) around the logo
    "star", rendered orthographically with a camera tilt, depth-sorted,
    depth-faded, with faint links between 3D neighbours (the node-halo look).
  - Physics (stylised, not orbital mechanics): a damped radial spring toward a
    per-mode target radius (slightly underdamped so transitions overshoot like a
    real repulsion) plus a smoothed angular velocity. Clamped delta time
    (max 50 ms per step) so refresh rate can't change the speed.
  - Modes, driven ONLY by the existing event-driven status calls —
    `setStatus(state, text, mode)`: `orbit` (generating: Thinking/Drafting/Writing/
    waiting for model/Continuing) → nodes orbit close in; `exec` (Running <tool>)
    → nodes repulsed outward and held at a distance, rotation damps to a
    standstill with a slight held tension; `wait` (approval needed) → slow amber
    orbit; `done`/`error` → the swarm dissolves (alpha → 0) and the canvas fades
    via CSS (`.working`/`.waiting` show it).
  - One shared rAF loop serves all avatars and stops when none is animating;
    it also steps nothing while the tab is hidden. `prefers-reduced-motion`:
    a single static shell frame, no motion.
- Canvas background (`#bgNet`, v2): gas-like drifting particles linked into a net
  (lines when close), pushed away by the cursor (Obsidian-graph feel). Bounded
  (30–90 particles), pauses when the tab is hidden, disabled under
  `prefers-reduced-motion`, follows the accent hue.

## 10. Artifacts & skills panels (views.py, urls.py, index.html)
- New endpoints: `GET /artifacts/` (all of the user's artifacts),
  `POST /artifact/create/`, `GET /skills/`, `POST /skills/create/`.
- Topbar buttons open Artifacts / Skills modals: list, open in new tab, and
  create new ones by hand. A new artifact lands in the current chat (or starts a
  new chat if none is open). A new skill is written to
  `pyggie/home/skills/<name>/SKILL.md` and is immediately loadable via
  `load_skill` (the model-facing tool list text refreshes on server restart).



## Tests run
- `python manage.py check` — clean.
- Unit-tested in-process: streamed tool-call merging (`merge_tool_calls`),
  JSON-string argument parsing, network denial inside the bwrap sandbox
  (socket connect to 1.1.1.1:53 fails), finish-summary emission, skill
  create/list, artifact create endpoint, iframe header exemption, template
  rendering, and `node --check` on the page script.
- v3 (browser, against the rendered template): all three background modes (body
  class + canvas hidden, background loop fully stopped while Off and restarted
  when switched back on, and a lossless-PNG blur check on the rendered page —
  the same red test band shows a sharp 1px edge outside text surfaces and a
  gradual ~25px ramp behind them), the agent switch (checked styling, knob
  translate, keyboard toggling with Space and a focus-visible ring), the swarm
  in orbit/exec/wait/done modes at real 40px size, its dissolve on done, and
  the reduced-motion static frame.
- v3b (browser, SSE fixture through the real consumer — fetch intercepted with
  fake event streams, driving the actual Send/approve UI): send → thinking →
  tool_arg → tool (exec, "Running …") → result → approval ("Waiting for your
  approval", wait mode) → Allow ("Continuing", no exec guess) → truthful tool
  event → result → report → Done, all verified; a no-text completion settles to
  Done instead of an approval-style wait. Reduced-motion exercised via
  emulated `prefers-reduced-motion` (static shell frame, motionless over time;
  a fresh non-reduced load animates normally). Background-mode persistence verified in
  jsdom against the shipped template with pre-seeded storage (blur restored on
  load, off written on click, on-by-default with nothing stored) — the deploy
  preview forbids localStorage, so no HTTPS-origin reload test was possible.
  (Django's test runner has 0 tests in the repo — checks above are
  `manage.py check`, in-process probes, jsdom and browser runs.)

## 11. Background visuals setting (index.html, v3)
- Settings modal gains a segmented control (On / Blur behind text / Off),
  persisted in `localStorage['Clank.r.bg']`, applied as a body class:
  - `bgm-on` (default): unchanged.
  - v3b bug fix: blur-behind-text was silently inert — the message-row
    entrance animation used `animation-fill-mode: both`, and the retained
    forward-filled animation effect interfered with the surfaces'
    `backdrop-filter` (nothing behind the text got blurred). Changed to
    `backwards`: the entrance still plays, and once the animation ends its
    effect is released. Verified with lossless PNG screenshots: the same red
    test band edge is sharp outside text and a ~25px gradual ramp behind it.
  - `bgm-blur`: message surfaces (`.msg-bubble.usr`, `.ai-body`, `.think`,
    `.tool-notice`, `.approval`, `.result`) get `backdrop-filter: blur(7px)` + a
    62% dark tint — the net stays sharp in empty space and is softened only
    where text sits on it. (backdrop-filter requires a modern browser; the tint
    alone still keeps text readable if unsupported.)
  - `bgm-off`: `#bgNet` hidden via CSS and its animation loop fully stopped —
    the frame function returns without scheduling another rAF callback, so no
    hidden work runs at all. Switching back to On/Blur (or the tab becoming
    visible again) restarts the loop via a `clankr:bgmode` event /
    `visibilitychange`.

## 12. Agent-mode switch (index.html, v3)
- The `🤖 Agent` checkbox is now a small pill switch (26×15px track, 9px knob)
  in the topbar, styled like the rest of the UI (DM Mono "Agent" label,
  accent fill when on, dark knob). It is still the same native
  `<input type="checkbox" id="agentMode">` (visually hidden, not `display:none`),
  so all behaviour, form semantics and keyboard operation are unchanged; the
  switch shows a focus-visible ring when tabbed to.

## Known limitations (for the next agent)
- Without bubblewrap, run_python's network block is Python-level and best-effort;
  approval gating covers the gap. Recommend installing bubblewrap.
- `get_caps` is cached per model (unchanged).
- User-created skills appear in the model's tool description only after a server
  restart (load_skill itself works immediately).

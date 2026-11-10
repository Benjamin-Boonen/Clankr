# Private reasoning stream fix

## Symptom

With the Thinking toggle enabled, the agent UI displayed raw Ollama `message.thinking` chunks in the expandable "Thinking…" panel. The screenshot reproduction showed the model narrating its continuation plan, quoting the previous answer, repeating the source list, and then stopping mid-sentence. This is private model self-talk, not a useful progress summary.

## Root cause

`pyggie/home/agent.py::_model_round` forwarded every Ollama `message.thinking` chunk as a `thinking` SSE event. The frontend rendered those chunks verbatim. The Thinking toggle controls model-side reasoning, but the stream exposed that internal trace directly.

## Change

- Stop forwarding Ollama's raw `thinking` field to the browser.
- Keep the Thinking toggle: it still sets Ollama's `think` request option.
- Keep normal answer tokens, tool-call progress, results, artifacts, and status events unchanged.
- The UI can still show a generic "Thinking" activity status without rendering the model's private trace.

## Regression test

`AgentThinkingPrivacyTests.test_private_thinking_is_not_emitted_to_the_ui` feeds a fake Ollama response containing both private thinking and visible answer content. It verifies that no `thinking` event is emitted, the visible answer token is preserved, and the model-side thinking option remains enabled.

## Validation

Run from `pyggie/`:

```bash
python manage.py check
python manage.py test home
```

Also test with a reasoning-capable local model with Thinking enabled. The UI should show activity while the model works, then render only the user-facing answer and tool activity.

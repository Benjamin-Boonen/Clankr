# Thinking toggle

The chat header now has a **Thinking** switch beside **Agent**.

## Behavior
- Enabled by default to preserve current behavior.
- The selected boolean is sent with both ordinary chat and agent requests.
- Ollama receives `think: true` or `think: false` only when the selected model advertises thinking support.
- Agent runs persist the setting in `AgentRun.thinking_enabled`, so approval/resume requests keep the original preference.
- If thinking is enabled but a model spends its whole generation budget on hidden thinking, existing recovery logic may retry once without thinking to produce a user-facing answer. If the user disabled thinking, that fallback is not needed.

## Files
- `pyggie/home/templates/home/index.html`: header switch and request payload.
- `pyggie/home/views.py`: forwards the preference to chat and agent paths.
- `pyggie/home/ollama.py`: applies the preference to ordinary chat.
- `pyggie/home/agent.py`: applies the saved preference to agent model rounds.
- `pyggie/home/models.py` and migration `0008_agentrun_thinking_enabled.py`: persist the setting for agent approval/resume.

## Validation
Run from `pyggie/`:

```bash
python manage.py migrate
python manage.py check
python manage.py test home
```

Also manually test both switch states with a model that supports thinking, and verify agent approval/resume retains the chosen state. These checks have not been run by the remote editing session.

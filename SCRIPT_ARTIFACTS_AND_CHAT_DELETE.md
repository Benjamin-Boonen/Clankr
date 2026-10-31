# Script artifacts and conversation deletion

Branch: `feature/script-artifacts-chat-delete`
Base: `main`

## Scope
- Agent-generated deliverables can be saved as Python (`kind=python`) and shell (`kind=shell`) artifacts, alongside HTML, SVG and Markdown.
- Python and shell execution always pauses for explicit approval on each invocation. The approval card displays the code/command and offers **Approve once** or **Deny**. "Always allow" is intentionally unavailable for execution tools and is also rejected by the backend.
- Script files can also be written into the per-chat workspace with `write_file`; creating/writing a script does not execute it.
- Conversation rows have a three-dot options button. Delete asks for confirmation and warns that the operation cannot be undone. The server scopes deletion to the authenticated owner; messages, attachments, artifacts and agent runs cascade with the chat.

## Files changed
- `pyggie/home/agent.py`: script artifact tool kinds; per-call approval for both execution tools.
- `pyggie/home/views.py`: owner-scoped chat deletion; script artifact preview and creation support.
- `pyggie/home/urls.py`: delete endpoint.
- `pyggie/home/templates/home/index.html`: approval UI and conversation options/confirmation.
- `pyggie/home/tests.py`: regression coverage.

## Validation
Run from `pyggie/`:
```sh
python manage.py test home
python manage.py check
```

Tests have not been run by the remote editing workflow. Please run them locally before merging.

# home/handoff.py — plain chat -> agent mode, decided by the model itself.
#
# In plain chat the model gets one extra tool, `promote_to_agent`. Calling it ends the plain
# reply and continues the SAME turn, in the same SSE stream, as an AgentRun (agent.drive).
# Contract (see HANDOFF_TO_AGENT.md):
#   ollama.chat_stream   offers TOOL + PROMPT, and on a call yields ("tool"), ("result"), ("promote", {...}) then stops.
#   views.send_message   swallows "promote" (the browser never sees it) and runs views._handoff_to_agent().
#   agent.TOOLS          does NOT contain this tool: an agent is already promoted.
# This module imports nothing from the app, so ollama.py can import it without a cycle.

NAME = "promote_to_agent"

TOOL = {"type": "function", "function": {
    "name": NAME,
    "description": ("Switch this reply to AGENT MODE: you get tools to run code, write files, create artifacts "
                    "and work through many steps until the task is done. Use only for work that needs that."),
    "parameters": {"type": "object",
                   "properties": {
                       "task": {"type": "string",
                                "description": "Self-contained brief for the agent: goal, constraints, expected deliverable."},
                       "reason": {"type": "string",
                                  "description": "One short sentence for the user: why agent mode is needed."}},
                   "required": ["task"]}}}

PROMPT = (
    "\nYou also have promote_to_agent. It switches this reply to AGENT MODE, where you can run code, write files, "
    "create artifacts and work through many steps until the job is done. Call it ONLY when the request clearly needs that: "
    "writing AND running code, producing files or deliverables, or a long multi-step job. Do NOT call it for questions, "
    "explanations, maths you can do in prose, a single search or a single graph. When unsure, answer directly. "
    "If you promote, call it first and alone, and put the full task in `task`. "
    "Promotion grants no extra permissions: running code or shell commands still needs the user's approval."
)

DEFAULT_TASK = "Carry out the user's latest request."


def find(tool_calls):
    """The first promote_to_agent call among a model round's tool calls, else None."""
    for call in tool_calls or []:
        if (call.get("function") or {}).get("name") == NAME:
            return call
    return None


def details(args):
    """(task, reason) from parsed tool arguments. Never raises: a malformed call still promotes,
    with a generic task, because the user's request is already in the conversation."""
    args = args if isinstance(args, dict) else {}
    task = str(args.get("task") or "").strip()[:2000] or DEFAULT_TASK
    reason = " ".join(str(args.get("reason") or "").split())[:200]
    return task, reason


def notice(reason):
    """Text for the tool notice shown to the user."""
    return "Switching to agent mode" + (f": {reason}" if reason else "")


def agent_note(task):
    """The message that starts the agent run, appended after the conversation history."""
    return ("[Switched to agent mode.] You now have the agent tools (run_python, run_shell, write_file, "
            "create_artifact, finish, ...). Carry out this task, then call finish(summary):\n" + task)

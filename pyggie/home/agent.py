# home/agent.py — Agent mode: loop of model → tools → model … until the task is done.
# The loop PAUSES (and the HTTP stream ends) whenever a tool needs the user's approval;
# state lives in the AgentRun row, and /agent/approve/ resumes it.
import json, os, re, shutil, subprocess, datetime
from pathlib import Path
from django.conf import settings
import requests
from . import ollama
from .models import Artifact

MAX_STEPS = 25            # hard cap on model calls per run
OUT_CHARS = 8000          # tool output the model gets to see
SKILL_DIR = Path(__file__).parent / "skills"
HAS_BWRAP = shutil.which("bwrap") is not None

def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}
S = {"type": "string"}

TOOLS = [
    ollama.TOOLS[0], ollama.TOOLS[1],
    _fn("run_python", "Run Python 3 code in the sandbox. NO NETWORK ACCESS (web/API calls fail); workspace dir only. Print results.", {"code": S}, ["code"]),
    _fn("run_shell", "Run a shell command on the host. ALWAYS needs user approval.", {"command": S}, ["command"]),
    _fn("write_file", "Write a text file in the workspace.", {"path": S, "content": S}, ["path", "content"]),
    _fn("read_file", "Read a text file from the workspace.", {"path": S}, ["path"]),
    _fn("create_artifact", "Show the user a finished piece of work: a self-contained web page, SVG or Markdown document.",
        {"title": S, "kind": {"type": "string", "enum": ["html", "svg", "markdown"]}, "content": S}, ["title", "kind", "content"]),
    _fn("load_skill", "Load detailed instructions for a skill. Available: " + ", ".join(
        sorted(p.name for p in SKILL_DIR.iterdir() if p.is_dir())) if SKILL_DIR.exists() else "load_skill",
        {"name": S}, ["name"]),
    _fn("finish", "Call when the task is fully done, with a short summary for the user.", {"summary": S}, ["summary"]),
]

AGENT_PROMPT = (
    "\nYou are in AGENT MODE. Work autonomously on the user's task: plan briefly, call tools, "
    "inspect results, fix mistakes, repeat. Prefer run_python for computation. Use create_artifact for "
    "deliverables (load_skill first for html/report/diagram). User-attached files are already in the workspace (read_file / run_python). Some tools ask the user for permission; "
    "if denied, adapt. run_python has NO network access — never try web or API calls in code; use web_search/fetch_page instead. "
    "When completely done, call finish(summary) with what you did and what the results are. "
    "Never write tool calls as text."
)

# Preamble for run_python when no OS sandbox (bwrap) is available: Python-level
# network block. Best-effort (ctypes/raw sockets can bypass it) — which is why
# this mode ALSO requires explicit user approval (see needs_approval).
NET_GUARD = '''import socket
class _Blocked(Exception): pass
def _no(*a, **k): raise _Blocked("Network access is blocked (no OS sandbox installed; network disabled for safety)")
socket.socket = _no
socket.create_connection = _no
socket.getaddrinfo = _no
socket.gethostbyname = _no
socket.gethostbyname_ex = _no
try:
    import ssl; ssl.SSLContext = _no
except Exception:
    pass
src = open("_run.py").read()
exec(compile(src, "_run.py", "exec"), {"__name__": "__main__", "__file__": "_run.py"})
'''

def workspace(chat_id):
    p = Path(settings.BASE_DIR) / "agent_workspaces" / str(chat_id)
    p.mkdir(parents=True, exist_ok=True)
    return p

def copy_to_workspace(chat_id, message):
    """Put text/pdf attachments in the workspace as files (pdf as extracted .txt)."""
    ws = workspace(chat_id)
    for a in message.attachments.all():
        if a.kind == "image": continue
        name = os.path.basename(a.name) + (".txt" if a.kind == "pdf" else "")
        (ws / name).write_text(a.text)


def _safe(ws, rel):
    p = (ws / rel).resolve()
    if ws.resolve() not in p.parents and p != ws.resolve():
        raise ValueError("path escapes workspace")
    return p

def needs_approval(name, args):
    """Sandboxed / read-only / workspace-only actions are free; anything touching the host asks.
    run_python without bwrap runs only Python-level network blocking (best-effort),
    so it still asks the user first in that case."""
    if name == "run_shell":
        return True
    if name == "run_python":
        return not HAS_BWRAP          # no OS sandbox → ask
    return False

def _clip(s):
    s = s or ""
    return s if len(s) <= OUT_CHARS else s[:OUT_CHARS] + "\n…[truncated]"

def execute(name, args, run):
    ws = workspace(run.chat_id)
    try:
        if "__raw__" in args:
            return "Tool error: arguments were not valid JSON — rewrite the tool call."
        if name == "run_python":
            f = ws / "_run.py"; f.write_text(args["code"])
            if HAS_BWRAP:
                # OS sandbox: no network namespace at all (web/API/localhost unreachable),
                # no other users, no host filesystem outside the workspace.
                cmd = ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                       "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                       "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                       "--bind", str(ws), "/work", "--chdir", "/work",
                       "--unshare-all", "--unshare-net", "--die-with-parent", "python3", "-I", "_run.py"]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            else:
                # No OS sandbox: Python-level network block (NET_GUARD) + user approval.
                (ws / "_netguard.py").write_text(NET_GUARD)
                r = subprocess.run(["python3", "-I", "_netguard.py"], cwd=ws,
                                   capture_output=True, text=True, timeout=30)
            return _clip(r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr else "")) or "(no output)"
        if name == "run_shell":
            r = subprocess.run(args["command"], shell=True, cwd=ws, capture_output=True, text=True, timeout=60)
            return _clip(f"[exit {r.returncode}]\n{r.stdout}{r.stderr}")
        if name == "write_file":
            p = _safe(ws, args["path"]); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"]); return f"wrote {args['path']} ({len(args['content'])} chars)"
        if name == "read_file":
            return _clip(_safe(ws, args["path"]).read_text())
        if name == "create_artifact":
            a = Artifact.objects.create(chat_id=run.chat_id, title=args["title"][:200],
                                        kind=args["kind"], content=args["content"])
            run.new_artifacts.append({"id": a.id, "title": a.title, "kind": a.kind})
            return f"artifact #{a.id} shown to the user"
        if name == "load_skill":
            n = re.sub(r"[^a-z0-9_-]", "", args["name"].lower())
            f = SKILL_DIR / n / "SKILL.md"
            return f.read_text() if f.exists() else "No such skill."
        if name == "finish":
            run.done = True; run.summary = args.get("summary", ""); return "ok"
        return ollama.run_tool(name, args)       # web_search / fetch_page
    except subprocess.TimeoutExpired:
        return "Tool error: timed out"
    except Exception as e:
        return f"Tool error: {e}"

def _model_round(model, run, allow_tools=True):
    """One streamed model call. Yields events; returns (text, tool_calls) via run.last."""
    caps = ollama.get_caps(model)
    system = ollama.SYSTEM_PROMPT.split("You have two tools")[0] + AGENT_PROMPT + \
             f"\nToday's date: {datetime.date.today():%A %d %B %Y}."
    payload = {"model": model, "stream": True, "options": {"temperature": 0.2},
               "messages": [{"role": "system", "content": system}] + run.msgs}
    if "thinking" in caps: payload["think"] = True
    if allow_tools and "tools" in caps: payload["tools"] = TOOLS
    resp = requests.post(f"{ollama.OLLAMA_BASE}/api/chat", json=payload, stream=True)
    ollama._check(resp)
    text, calls = [], []
    for line in resp.iter_lines():
        if not line: continue
        c = json.loads(line); m = c.get("message", {})
        if t := m.get("thinking"): yield "thinking", t
        if t := m.get("content"): text.append(t); yield "token", t
        for name, frag in ollama.merge_tool_calls(calls, m.get("tool_calls")):
            yield "tool_arg", {"name": name or "", "delta": frag}   # live, while typed
        if c.get("done"): break
    for call in calls:
        call["function"]["arguments"] = ollama.parse_args(call["function"].get("arguments"))
    run.last = ("".join(text), calls)

def _process(run, calls):
    """Run calls in order. If one needs approval, park the rest in run.pending and stop."""
    if not hasattr(run, "new_artifacts"):
        run.new_artifacts = []
    while calls:
        call = calls[0]; fn = call["function"]
        args = ollama.parse_args(fn.get("arguments"))
        name = fn["name"]
        if needs_approval(name, args) and name not in run.allowed:
            run.pending = calls
            yield "approval", {"run_id": run.id, "name": name, "args": args}
            return
        calls.pop(0)
        label = next(iter(args.values()), "") if args else ""
        yield "tool", {"name": name, "arg": label}
        out = execute(name, args, run)
        run.msgs.append({"role": "tool", "tool_name": name, "content": out})
        yield "result", {"name": name, "out": out[:1500]}
        if name == "finish" and run.summary:
            # the finish() summary IS the agent's report to the user — show it as text
            yield "token", f"\n\n**Done:** {run.summary}"
        for a in run.new_artifacts: yield "artifact", a
        run.new_artifacts = []
    run.pending = []

def drive(run, model):
    """Main loop. Yields events until finished, paused for approval, or out of steps."""
    run.new_artifacts = []; run.done = False
    if run.pending:                       # resumed with leftover calls
        calls = run.pending; run.pending = []
        yield from _process(run, calls)
        if run.pending: run.save(); return
    while not run.done and run.steps < MAX_STEPS:
        run.steps += 1
        yield "step", run.steps
        yield from _model_round(model, run)
        text, calls = run.last
        run.msgs.append({"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})})
        if not calls:
            run.done = True
            if not text.strip():
                yield "token", "*(The model finished its work but wrote no final answer — see the tool activity above.)*"
            break                                  # plain answer = done
        yield from _process(run, calls)
        if run.pending: run.save(); return        # paused
    if not run.done:
        # Step limit reached: force ONE final round without tools so the user
        # always gets a report of what was (and wasn't) completed.
        run.steps += 1
        yield "step", run.steps
        run.msgs.append({"role": "user", "content":
            "You have reached the step limit. WITHOUT calling any tools, tell the user in 2-4 sentences: "
            "what you completed, what is still missing, and where the results are (files or artifacts)."})
        yield from _model_round(model, run, allow_tools=False)
        text, _ = run.last
        run.msgs.append({"role": "assistant", "content": text})
        if not text.strip():
            yield "token", "\n\n*(Stopped: step limit reached before the task finished. See the tool activity above for partial results.)*"
    run.status = "done"; run.save()
    yield "done", {"summary": run.summary or ""}

def resume(run, approve, always=False):
    """Apply the user's decision to the first pending call."""
    call = run.pending.pop(0); fn = call["function"]; name = fn["name"]
    args = ollama.parse_args(fn.get("arguments"))
    run.new_artifacts = []
    if approve:
        if always: run.allowed = list(set(run.allowed) | {name})
        # same truthful "tool" event as _process(): fired only once execution
        # is actually about to run (approval already granted above).
        yield "tool", {"name": name, "arg": next(iter(args.values()), "") if args else ""}
        out = execute(name, args, run)
    else:
        out = "The user DENIED this action. Do not retry it; choose another approach or explain."
    run.msgs.append({"role": "tool", "tool_name": name, "content": out})
    yield "result", {"name": name, "out": out[:1500]}
    if approve and name == "finish" and run.summary:
        yield "token", f"\n\n**Done:** {run.summary}"
    for a in run.new_artifacts: yield "artifact", a


def list_skills():
    """All skills on disk (name, description, full body) — for the Skills panel."""
    out = []
    if SKILL_DIR.exists():
        for p in sorted(SKILL_DIR.iterdir()):
            if p.is_dir() and (p / "SKILL.md").exists():
                body = (p / "SKILL.md").read_text()
                out.append({"name": p.name,
                            "description": body.strip().splitlines()[0][:200] if body.strip() else "",
                            "body": body})
    return out

def create_skill(name, content):
    """User-created skill: pyggie/home/skills/<name>/SKILL.md. Returns (ok, error)."""
    n = re.sub(r"[^a-z0-9_-]", "", name.lower().strip())
    if not n or len(n) > 40:
        return False, "invalid skill name (use lowercase letters, digits, - or _)"
    if not content.strip():
        return False, "skill instructions are empty"
    d = SKILL_DIR / n
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content)
    return True, None

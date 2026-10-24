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
    _fn("run_python", "Run Python 3 code in the sandbox (no network, workspace dir only). Print results.", {"code": S}, ["code"]),
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
    "if denied, adapt. When completely done, call finish(summary). Never write tool calls as text."
)

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
    """Sandboxed / read-only / workspace-only actions are free; anything touching the host asks."""
    if name == "run_shell":
        return True
    if name == "run_python":
        return not HAS_BWRAP          # no sandbox available → ask
    return False

def _clip(s):
    s = s or ""
    return s if len(s) <= OUT_CHARS else s[:OUT_CHARS] + "\n…[truncated]"

def execute(name, args, run):
    ws = workspace(run.chat_id)
    try:
        if name == "run_python":
            f = ws / "_run.py"; f.write_text(args["code"])
            if HAS_BWRAP:
                cmd = ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                       "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                       "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                       "--bind", str(ws), "/work", "--chdir", "/work",
                       "--unshare-all", "--die-with-parent", "python3", "-I", "_run.py"]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            else:
                r = subprocess.run(["python3", "_run.py"], cwd=ws, capture_output=True, text=True, timeout=30)
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

def _model_round(model, run):
    """One streamed model call. Yields events; returns (text, tool_calls) via run.last."""
    caps = ollama.get_caps(model)
    system = ollama.SYSTEM_PROMPT.split("You have two tools")[0] + AGENT_PROMPT + \
             f"\nToday's date: {datetime.date.today():%A %d %B %Y}."
    payload = {"model": model, "stream": True, "options": {"temperature": 0.2},
               "messages": [{"role": "system", "content": system}] + run.msgs}
    if "thinking" in caps: payload["think"] = True
    if "tools" in caps: payload["tools"] = TOOLS
    resp = requests.post(f"{ollama.OLLAMA_BASE}/api/chat", json=payload, stream=True)
    ollama._check(resp)
    text, calls = [], []
    for line in resp.iter_lines():
        if not line: continue
        c = json.loads(line); m = c.get("message", {})
        if t := m.get("thinking"): yield "thinking", t
        if t := m.get("content"): text.append(t); yield "token", t
        calls.extend(m.get("tool_calls") or [])
        if c.get("done"): break
    run.last = ("".join(text), calls)

def _process(run, calls):
    """Run calls in order. If one needs approval, park the rest in run.pending and stop."""
    while calls:
        call = calls[0]; fn = call["function"]; args = fn.get("arguments") or {}
        name = fn["name"]
        if needs_approval(name, args) and name not in run.allowed:
            run.pending = calls
            yield "approval", {"run_id": run.id, "name": name, "args": args}
            return
        calls.pop(0)
        yield "tool", {"name": name, "arg": next(iter(args.values()), "") if args else ""}
        out = execute(name, args, run)
        run.msgs.append({"role": "tool", "tool_name": name, "content": out})
        yield "result", {"name": name, "out": out[:1500]}
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
        if not calls: run.done = True; break      # plain answer = done
        yield from _process(run, calls)
        if run.pending: run.save(); return        # paused
    if not run.done:
        yield "token", "\n\n*(Stopped: step limit reached.)*"
    run.status = "done"; run.save()
    yield "done", {}

def resume(run, approve, always=False):
    """Apply the user's decision to the first pending call."""
    call = run.pending.pop(0); fn = call["function"]; name = fn["name"]
    args = fn.get("arguments") or {}
    run.new_artifacts = []
    if approve:
        if always: run.allowed = list(set(run.allowed) | {name})
        out = execute(name, args, run)
    else:
        out = "The user DENIED this action. Do not retry it; choose another approach or explain."
    run.msgs.append({"role": "tool", "tool_name": name, "content": out})
    yield "result", {"name": name, "out": out[:1500]}
    for a in run.new_artifacts: yield "artifact", a

# home/test_handoff.py — plain chat -> agent mode via the promote_to_agent tool (see HANDOFF_TO_AGENT.md).
# Run: cd pyggie && python manage.py test home.test_handoff
# No Ollama needed: requests.post is faked, one canned response per model round.
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from . import agent, handoff, ollama
from .models import AgentRun, Chat, Message


class Resp:
    ok = True

    def __init__(self, *chunks): self.chunks = chunks
    def iter_lines(self): return (json.dumps(c).encode() for c in self.chunks)
    def close(self): pass


def call(name, args):
    return {"function": {"name": name, "arguments": args}}


def round_with(*calls):
    return Resp({"message": {"tool_calls": list(calls)}, "done": True})


def say(text):
    return Resp({"message": {"content": text}, "done": True})


def patched(responses, caps=("completion", "tools")):
    """Fake Ollama for both plain chat and agent mode."""
    return (mock.patch.object(ollama, "get_caps", return_value=caps),
            mock.patch.object(ollama, "is_loaded", return_value=True),
            mock.patch.object(ollama.requests, "post", side_effect=responses))


class HandoffUnit(SimpleTestCase):
    def test_details_never_raises(self):
        self.assertEqual(handoff.details({"task": " build X ", "reason": "needs\n code"}), ("build X", "needs code"))
        for bad in ({}, None, {"__raw__": "{oops"}, [], {"task": ""}, {"task": None}):
            with self.subTest(bad=bad):
                self.assertEqual(handoff.details(bad)[0], handoff.DEFAULT_TASK)

    def test_details_are_bounded(self):
        task, reason = handoff.details({"task": "t" * 9999, "reason": "r" * 9999})
        self.assertLessEqual(len(task), 2000)
        self.assertLessEqual(len(reason), 200)

    def test_agent_already_promoted_cannot_promote(self):
        self.assertNotIn(handoff.NAME, {t["function"]["name"] for t in agent.TOOLS})

    def test_promotion_needs_no_approval_but_grants_none(self):
        self.assertFalse(agent.needs_approval(handoff.NAME, {}))
        self.assertTrue(agent.needs_approval("run_python", {}))
        self.assertTrue(agent.needs_approval("run_shell", {}))


class ChatStreamPromotes(SimpleTestCase):
    def stream(self, responses, **kw):
        a, b, c = patched(responses, **kw)
        with a, b, c as post:
            events = list(ollama.chat_stream("m", [{"role": "user", "content": "build me a tool"}]))
        return events, post

    def test_tool_and_prompt_offered_with_tool_support(self):
        _, post = self.stream([say("hi")])
        sent = post.call_args.kwargs["json"]
        self.assertIn(handoff.NAME, [t["function"]["name"] for t in sent["tools"]])
        self.assertIn("promote_to_agent", sent["messages"][0]["content"])

    def test_not_offered_without_tool_support(self):
        _, post = self.stream([say("hi")], caps=("completion",))
        sent = post.call_args.kwargs["json"]
        self.assertNotIn("tools", sent)
        self.assertNotIn("promote_to_agent", sent["messages"][0]["content"])

    def test_promote_call_ends_plain_chat_with_a_promote_event(self):
        events, post = self.stream([round_with(call(handoff.NAME, {"task": "write a script", "reason": "needs code"}))])
        self.assertEqual([k for k, _ in events], ["tool", "result", "promote"])
        self.assertEqual(events[0][1]["name"], handoff.NAME)
        self.assertEqual(events[1][1]["out"], "Switching to agent mode: needs code")
        self.assertEqual(events[2][1], {"task": "write a script", "reason": "needs code"})
        self.assertEqual(post.call_count, 1)                 # no second plain round after promoting

    def test_other_calls_in_the_same_round_are_not_executed(self):
        search = call("web_search", {"query": "x"})
        with mock.patch.object(ollama, "run_tool") as run_tool:
            events, _ = self.stream([round_with(search, call(handoff.NAME, {"task": "t"}))])
        run_tool.assert_not_called()
        self.assertEqual([k for k, _ in events], ["tool", "result", "promote"])

    def test_malformed_promote_still_promotes(self):
        events, _ = self.stream([round_with(call(handoff.NAME, "{oops"))])
        self.assertEqual(events[-1], ("promote", {"task": handoff.DEFAULT_TASK, "reason": ""}))

    def test_ordinary_answer_is_untouched(self):
        events, _ = self.stream([say("42")])
        self.assertEqual(events, [("token", "42")])


class SendMessageHandoff(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a", password="pw")
        self.client.force_login(self.user)
        # agent.execute() makes agent_workspaces/<chat id>; keep that out of the real project folder
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(agent, "workspace", side_effect=lambda chat_id: Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, responses, content="make me a script"):
        a, b, c = patched(responses)
        with a, b, c as post:
            r = self.client.post("/send/", data=json.dumps({"content": content, "model": "m"}),
                                 content_type="application/json")
            body = b"".join(r.streaming_content).decode()
        events = [json.loads(p[6:]) for p in body.split("\n\n") if p.startswith("data: ") and p != "data: [DONE]"]
        return events, body, post

    def test_same_stream_continues_as_an_agent_run(self):
        events, body, post = self.send([
            round_with(call(handoff.NAME, {"task": "write hello.py", "reason": "needs files"})),
            round_with(call("finish", {"summary": "wrote it"})),
        ])
        kinds = [k for e in events for k in e]
        self.assertEqual(kinds.count("chat_id"), 1)
        self.assertIn("run_id", kinds)
        self.assertLess(kinds.index("tool"), kinds.index("run_id"))          # notice first, then the agent starts
        self.assertIn("step", kinds)
        self.assertEqual(body.count("data: [DONE]"), 1)
        self.assertIn("**Done:** wrote it", body)
        # the agent got the history AND the task, and the agent tool list (without promote_to_agent)
        run = AgentRun.objects.get()
        self.assertEqual(run.msgs[0]["content"], "make me a script")
        self.assertIn("write hello.py", run.msgs[1]["content"])
        agent_payload = post.call_args_list[1].kwargs["json"]
        names = [t["function"]["name"] for t in agent_payload["tools"]]
        self.assertIn("run_python", names)
        self.assertNotIn(handoff.NAME, names)
        self.assertIn("AGENT MODE", agent_payload["messages"][0]["content"])
        # the answer is saved as one AI message, linked to the same chat
        self.assertEqual(Message.objects.get(role="ai").content.strip(), "**Done:** wrote it")
        self.assertEqual(run.chat_id, Message.objects.get(role="user").chat_id)

    def test_approval_still_required_after_handoff(self):
        events, body, _ = self.send([
            round_with(call(handoff.NAME, {"task": "run it"})),
            round_with(call("run_python", {"code": "print(1)"})),
        ])
        approval = next(e["approval"] for e in events if "approval" in e)
        run = AgentRun.objects.get()
        self.assertEqual(approval["run_id"], run.id)                          # the page approves via this id
        self.assertEqual((approval["name"], run.status), ("run_python", "running"))
        self.assertEqual(len(run.pending), 1)
        self.assertEqual(body.count("data: [DONE]"), 1)
        self.assertNotIn("print(1)", "".join(m.get("content", "") for m in run.msgs if m["role"] == "tool"))  # not executed

    def test_plain_answer_creates_no_run(self):
        events, _, _ = self.send([say("4")], content="2+2?")
        self.assertEqual(AgentRun.objects.count(), 0)
        self.assertEqual(Message.objects.get(role="ai").content, "4")
        self.assertNotIn("promote", json.dumps(events))                       # internal event never reaches the browser

"""Regression tests for persistent agent task state and tool result reuse."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from . import agent


class PersistentAgentStateTests(SimpleTestCase):
    def _call(self, args=None):
        return {"function": {"name": "read_file", "arguments": args or {"path": "notes.txt"}}}

    def test_working_state_survives_rounds_and_is_not_sent_as_chat_message(self):
        run = SimpleNamespace(msgs=[{"role": "user", "content": "Analyse these notes"}])
        state = agent._working_state(run)
        state["completed"].append("read_file")
        state["findings"].append({"tool": "read_file", "result": "Important fact"})
        prompt = agent._working_state_prompt(run)
        self.assertIn("Analyse these notes", prompt)
        self.assertIn("Important fact", prompt)
        transcript = [m for m in run.msgs if not m.get(agent.STATE_MARKER)]
        self.assertEqual(transcript, [{"role": "user", "content": "Analyse these notes"}])
        self.assertEqual(agent._working_state(run)["completed"], ["read_file"])

    def test_equivalent_tool_call_reuses_result_without_reexecution(self):
        args = {"path": "Notes.txt"}
        call = self._call(args)
        run = SimpleNamespace(
            id=1, chat_id=1, msgs=[
                {"role": "user", "content": "Read my notes"},
                {"role": "assistant", "content": "", "tool_calls": [call]},
            ],
            allowed=[], pending=[], new_artifacts=[], summary="", done=False,
        )
        with mock.patch.object(agent, "execute", return_value="The notes say hello") as execute:
            list(agent._process(run, [call]))
            run.msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
            events = list(agent._process(run, [call]))
        execute.assert_called_once()
        self.assertIn("REUSED PREVIOUS TOOL RESULT", run.msgs[-1]["content"])
        self.assertIn("The notes say hello", run.msgs[-1]["content"])
        self.assertEqual([kind for kind, _ in events], ["result"])

    def test_changed_arguments_are_not_mistaken_for_duplicate(self):
        run = SimpleNamespace(msgs=[])
        agent._record_tool_result(run, "read_file", {"path": "a.txt"}, "A")
        self.assertIsNone(agent._prior_tool_result(run, "read_file", {"path": "b.txt"}))

    def test_failed_result_is_still_preserved_for_continuity(self):
        run = SimpleNamespace(msgs=[{"role": "user", "content": "Read a file"}])
        agent._record_tool_result(run, "read_file", {"path": "missing.txt"}, "Tool error: missing")
        self.assertEqual(agent._prior_tool_result(run, "read_file", {"path": "missing.txt"}),
                         "Tool error: missing")
        self.assertFalse(agent._working_state(run)["tool_ledger"][-1]["ok"])

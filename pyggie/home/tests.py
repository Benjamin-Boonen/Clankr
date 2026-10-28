from django.test import SimpleTestCase

from .agent import _compact_messages, _is_repeat


class AgentContinuityTests(SimpleTestCase):
    def test_compaction_preserves_recent_messages_and_roles(self):
        messages = [
            {"role": "user", "content": "Original task " + ("x" * 20000)},
            {"role": "tool", "tool_name": "web_search", "content": "Evidence " + ("y" * 20000)},
        ] + [{"role": "user", "content": f"recent-{i}"} for i in range(10)]

        compacted = _compact_messages(messages)

        self.assertEqual(len(compacted), len(messages))
        self.assertEqual(compacted[-1], messages[-1])
        self.assertEqual(compacted[-2], messages[-2])
        self.assertIn("older context compacted", compacted[0]["content"])
        self.assertEqual(compacted[1]["role"], "tool")
        self.assertEqual(compacted[1]["tool_name"], "web_search")

    def test_repeat_guard_detects_same_read_only_call(self):
        class Run:
            msgs = [
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "RC circuit"}}}
                ]},
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "RC circuit"}}}
                ]},
            ]

        self.assertTrue(_is_repeat(Run(), "web_search", {"query": "RC circuit"}))
        self.assertFalse(_is_repeat(Run(), "web_search", {"query": "different query"}))
        self.assertFalse(_is_repeat(Run(), "run_python", {"code": "print(1)"}))

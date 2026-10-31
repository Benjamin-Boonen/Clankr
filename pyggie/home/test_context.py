"""Tests for shared prompt-history budgeting."""
from django.test import SimpleTestCase

from .context import compact_messages, context_pressure, estimate_tokens


class ContextBudgetTests(SimpleTestCase):
    def test_short_history_is_returned_unchanged(self):
        messages = [{"role": "user", "content": "hello"}]
        self.assertIs(compact_messages(messages), messages)

    def test_compaction_preserves_original_and_recent_tail(self):
        messages = [
            {"role": "user", "content": "Original objective: preserve this " + "A" * 8000},
            {"role": "assistant", "content": "old answer " + "B" * 5000},
            {"role": "tool", "tool_name": "web_search", "content": "evidence " + "C" * 5000},
        ] + [{"role": "user", "content": f"recent-{i}"} for i in range(8)]
        original_first = dict(messages[0])
        compacted = compact_messages(messages, budget_chars=10000, recent=8)
        self.assertEqual(messages[0], original_first)  # input transcript was not mutated
        self.assertEqual(compacted[0], messages[0])    # original task is preserved
        self.assertEqual(compacted[-1], messages[-1])
        self.assertEqual(compacted[-2], messages[-2])
        self.assertEqual(compacted[2]["role"], "tool")
        self.assertEqual(compacted[2]["tool_name"], "web_search")
        self.assertIn("compacted", compacted[1]["content"])

    def test_context_pressure_recommends_handoff_only_when_very_long(self):
        short = [{"role": "user", "content": "small"}]
        self.assertFalse(context_pressure(short, budget_chars=1000)["suggest_new_chat"])
        long = [{"role": "user", "content": "x" * 2000}]
        report = context_pressure(long, budget_chars=1000)
        self.assertTrue(report["suggest_new_chat"])
        self.assertEqual(report["level"], "critical")
        self.assertGreater(report["estimated_tokens"], 1)

    def test_estimate_tokens_is_approximate_and_nonzero(self):
        self.assertGreaterEqual(estimate_tokens([]), 1)
        self.assertGreater(estimate_tokens([{"role": "user", "content": "x" * 100}]), 1)

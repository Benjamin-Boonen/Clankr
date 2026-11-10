"""Regression tests for stopping agent research after empty/failed results."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from . import agent


class EmptyResearchStopTests(SimpleTestCase):
    def _run(self, name, result):
        return SimpleNamespace(msgs=[
            {"role": "user", "content": "Explain the topic"},
            {"role": "tool", "tool_name": name, "content": result},
        ])

    def test_empty_web_search_stops_rephrased_search(self):
        run = self._run("web_search", "[]")
        self.assertTrue(agent._research_limit_reached(run, "web_search"))

    def test_failed_web_search_stops_rephrased_search(self):
        run = self._run("web_search", "Tool error: network unavailable")
        self.assertTrue(agent._research_limit_reached(run, "web_search"))

    def test_unreadable_page_stops_another_fetch(self):
        run = self._run("fetch_page", "Could not read this page.")
        self.assertTrue(agent._research_limit_reached(run, "fetch_page"))

    def test_nonempty_search_can_still_be_followed_by_one_search(self):
        run = self._run("web_search", '[{"title":"Rabbit biology","url":"https://example.org"}]')
        self.assertFalse(agent._research_limit_reached(run, "web_search"))

    def test_two_successful_searches_still_hit_existing_limit(self):
        run = self._run("web_search", '[{"title":"A"}]')
        run.msgs.append({"role": "tool", "tool_name": "web_search", "content": '[{"title":"B"}]'})
        self.assertTrue(agent._research_limit_reached(run, "web_search"))

    def test_unrelated_tool_is_not_limited(self):
        run = self._run("read_file", "notes")
        self.assertFalse(agent._research_limit_reached(run, "read_file"))

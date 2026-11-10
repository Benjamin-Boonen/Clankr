from unittest import mock

from django.test import SimpleTestCase

from . import ollama


class WebSearchFallbackTests(SimpleTestCase):
    @mock.patch.object(ollama, "DDGS")
    def test_empty_auto_result_tries_another_backend(self, ddgs):
        client = ddgs.return_value
        client.text.side_effect = [
            [],
            [{"title": "Rabbit biology", "href": "https://example.org/rabbits",
              "body": "A short overview"}],
        ]

        results = ollama._search_web("why do rabbits reproduce quickly")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Rabbit biology")
        self.assertEqual(client.text.call_count, 2)
        self.assertEqual(client.text.call_args_list[0].kwargs["backend"], "auto")
        self.assertEqual(client.text.call_args_list[1].kwargs["backend"], "brave")

    @mock.patch.object(ollama, "DDGS")
    def test_backend_exception_does_not_prevent_fallback(self, ddgs):
        client = ddgs.return_value
        client.text.side_effect = [
            RuntimeError("provider temporarily unavailable"),
            [{"title": "Result", "href": "https://example.org", "body": "Snippet"}],
        ]

        results = ollama._search_web("ordinary factual query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.org")
        self.assertEqual(client.text.call_count, 2)

    @mock.patch.object(ollama, "DDGS")
    def test_empty_results_from_all_backends_return_empty_list(self, ddgs):
        ddgs.return_value.text.return_value = []

        results = ollama._search_web("query with no matches")

        self.assertEqual(results, [])
        self.assertEqual(ddgs.return_value.text.call_count, 5)

    @mock.patch.object(ollama, "DDGS")
    def test_all_backend_errors_raise_diagnostic_error(self, ddgs):
        ddgs.return_value.text.side_effect = RuntimeError("blocked")

        with self.assertRaisesRegex(RuntimeError, "All web search backends failed"):
            ollama._search_web("ordinary factual query")

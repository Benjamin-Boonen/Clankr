# home/test_ctx_resize.py — automatic num_ctx growth. Run: cd pyggie && python manage.py test home
# Ollama is faked; no network needed.
import json
from unittest import mock

from django.test import SimpleTestCase

from . import agent, ollama

ERR = ('{"error":"request (4525 tokens) exceeds the available context size (4096 tokens), '
       'try increasing it"}')


class FakeResp:
    def __init__(self, ok=True, status=200, text="", chunks=()):
        self.ok, self.status_code, self.text, self.chunks = ok, status, text, chunks
        self.closed = False
    def iter_lines(self): return (json.dumps(c).encode() for c in self.chunks)
    def close(self): self.closed = True


def good(): return FakeResp(chunks=[{"message": {"content": "hi"}, "done": True}])
def too_big(): return FakeResp(ok=False, status=400, text=ERR)


def recording_post(responses):
    """Fake requests.post that snapshots each request (open_chat mutates one payload dict)."""
    sent, queue = [], list(responses)
    def post(url, **kw):
        sent.append({"options": dict(kw["json"].get("options", {})), "timeout": kw.get("timeout")})
        return queue.pop(0)
    return post, sent


class CtxResizeTests(SimpleTestCase):
    def setUp(self):
        ollama._ctx_overrides.clear()
        self.patches = [mock.patch.object(ollama, "get_caps", return_value=("completion",)),
                        mock.patch.object(ollama, "is_loaded", return_value=True),
                        mock.patch.object(ollama, "get_max_ctx", return_value=262144)]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.addCleanup(ollama._ctx_overrides.clear)

    def test_parse(self):
        self.assertEqual(ollama.parse_ctx_error(ERR), (4525, 4096))
        self.assertIsNone(ollama.parse_ctx_error('{"error":"model not found"}'))

    def test_next_num_ctx_covers_prompt_plus_reply_in_steps(self):
        self.assertEqual(ollama.next_num_ctx("m", 4525, 4096, 4096), 12288)   # 8621 -> 12288
        self.assertEqual(ollama.next_num_ctx("m", 4525, 4096, 0), 8192)

    def test_cap_and_too_large(self):
        with mock.patch.object(ollama, "MAX_NUM_CTX", 8192):
            self.assertEqual(ollama.next_num_ctx("m", 5000, 4096, 4096), 8192)   # clamped, not refused
            with self.assertRaises(ollama.ContextTooLarge):
                ollama.next_num_ctx("m", 9000, 4096, 4096)
        with mock.patch.object(ollama, "get_max_ctx", return_value=8192):       # model's own limit wins
            self.assertEqual(ollama.next_num_ctx("m", 4525, 4096, 4096), 8192)

    def test_chat_retries_with_bigger_context_and_says_so(self):
        post, sent = recording_post([too_big(), good()])
        with mock.patch.object(ollama.requests, "post", post):
            events = list(ollama.chat_stream("m", [{"role": "user", "content": "q"}]))
        self.assertEqual([k for k, _ in events], ["status", "token"])
        self.assertIn("4,525", events[0][1]); self.assertIn("12,288", events[0][1])
        self.assertNotIn("num_ctx", sent[0]["options"])
        self.assertEqual(sent[1]["options"]["num_ctx"], 12288)

    def test_learned_size_is_reused_without_another_failure(self):
        with mock.patch.object(ollama.requests, "post", side_effect=[too_big(), good(), good()]) as post:
            list(ollama.chat_stream("m", [{"role": "user", "content": "q"}]))
            events = list(ollama.chat_stream("m", [{"role": "user", "content": "q2"}]))
        self.assertEqual([k for k, _ in events], ["token"])
        self.assertEqual(post.call_args.kwargs["json"]["options"]["num_ctx"], 12288)

    def test_unrelated_400_still_raises(self):
        bad = FakeResp(ok=False, status=400, text='{"error":"model not found"}')
        with mock.patch.object(ollama.requests, "post", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "Ollama 400"):
                list(ollama.chat_stream("m", [{"role": "user", "content": "q"}]))
        self.assertTrue(bad.closed)

    def test_gives_up_with_clear_message_when_prompt_exceeds_cap(self):
        with mock.patch.object(ollama, "MAX_NUM_CTX", 4096), \
             mock.patch.object(ollama.requests, "post", return_value=too_big()):
            with self.assertRaisesRegex(ollama.ContextTooLarge, "Start a new chat"):
                list(ollama.chat_stream("m", [{"role": "user", "content": "q"}]))

    def test_agent_round_retries_too(self):
        run = mock.Mock(msgs=[{"role": "user", "content": "q"}], context_notice_sent=True)
        post, sent = recording_post([too_big(), good()])
        with mock.patch.object(ollama.requests, "post", post):
            events = list(agent._model_round("m", run))
        self.assertEqual([k for k, _ in events], ["status", "token"])
        self.assertEqual(sent[1]["options"]["num_ctx"], 12288)
        self.assertEqual(sent[1]["timeout"], (15, 180))       # agent timeouts preserved

import json
import os
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from . import airllm


class AirllmAdapterTests(SimpleTestCase):
    def test_model_identifier_is_provider_scoped(self):
        self.assertTrue(airllm.is_model("airllm:Qwen/Qwen3-8B"))
        self.assertFalse(airllm.is_model("Qwen/Qwen3-8B"))
        self.assertFalse(airllm.is_model("llama3:8b"))

    @patch.dict(os.environ, {"CLANKR_AIRLLM_MODEL": "Qwen/Qwen3-8B"})
    def test_model_picker_entry_is_generated_from_configuration(self):
        [entry] = airllm.get_models()
        self.assertEqual(entry["name"], "airllm:Qwen/Qwen3-8B")
        self.assertEqual(entry["provider"], "airllm")
        self.assertEqual(entry["caps"], [])

    @patch.dict(os.environ, {"CLANKR_AIRLLM_MODEL": "Qwen/Qwen3-8B"})
    def test_model_id_rejects_unconfigured_models(self):
        self.assertEqual(airllm.model_id("airllm:Qwen/Qwen3-8B"), "Qwen/Qwen3-8B")
        with self.assertRaises(RuntimeError):
            airllm.model_id("airllm:Qwen/Qwen3-14B")

    @patch.dict(os.environ, {"CLANKR_AIRLLM_MODEL": "Qwen/Qwen3-8B"})
    @patch("home.airllm.requests.post")
    def test_streamed_tokens_are_adapted_to_pyggie_events(self, post):
        response = Mock()
        response.ok = True
        response.iter_lines.return_value = [
            json.dumps({"token": "Hello"}).encode(),
            json.dumps({"token": " world"}).encode(),
            b'{"done":true}',
        ]
        post.return_value = response

        events = list(airllm.chat_stream(
            "airllm:Qwen/Qwen3-8B",
            [{"role": "user", "content": "Say hello"}],
        ))

        self.assertEqual(events[0][0], "status")
        self.assertEqual([value for kind, value in events if kind == "token"], ["Hello", " world"])
        response.close.assert_called_once()

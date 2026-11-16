import io
import json
import unittest
import urllib.error

from printcare.assistant.provider import (
    DeepSeekProvider,
    FakeProvider,
    ProviderError,
    strip_code_fence,
)


class CaptureOpener:
    def __init__(self, response: dict):
        self.response = response
        self.request = None
        self.timeout = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return json.dumps(self.response, ensure_ascii=False).encode("utf-8")


class DeepSeekProviderTest(unittest.TestCase):
    def test_builds_openai_compatible_request(self):
        opener = CaptureOpener(
            {
                "model": "deepseek-flash",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        )
        provider = DeepSeekProvider("sk-test", opener=opener)

        content = provider.complete([{"role": "user", "content": "你好"}])

        self.assertEqual(content, '{"ok": true}')
        self.assertEqual(provider.last_usage, {"prompt_tokens": 12, "completion_tokens": 3})
        self.assertTrue(opener.request.full_url.endswith("/chat/completions"))
        self.assertTrue(opener.request.get_header("Authorization").startswith("Bearer sk-"))
        body = json.loads(opener.request.data.decode("utf-8"))
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["max_tokens"], 2400)
        self.assertFalse(body["stream"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_http_error_is_wrapped_without_key(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"error":"invalid key"}'),
            )

        provider = DeepSeekProvider("sk-secret-value", opener=opener)

        with self.assertRaises(ProviderError) as caught:
            provider.complete([{"role": "user", "content": "hi"}])

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertNotIn("sk-secret-value", message)

    def test_invalid_json_response_is_wrapped(self):
        def opener(request, timeout):
            return b"<html>not json</html>"

        provider = DeepSeekProvider("sk-test", opener=opener)

        with self.assertRaises(ProviderError):
            provider.complete([{"role": "user", "content": "hi"}])

    def test_empty_key_is_rejected(self):
        with self.assertRaises(ProviderError):
            DeepSeekProvider("")


class FakeProviderTest(unittest.TestCase):
    def test_returns_scripted_responses_and_records_calls(self):
        provider = FakeProvider(['{"a": 1}', '{"b": 2}'])

        self.assertEqual(provider.complete([{"role": "user", "content": "x"}]), '{"a": 1}')
        self.assertEqual(provider.complete([{"role": "user", "content": "y"}]), '{"b": 2}')
        self.assertEqual(len(provider.calls), 2)

    def test_exhausted_provider_raises(self):
        provider = FakeProvider([])

        with self.assertRaises(ProviderError):
            provider.complete([{"role": "user", "content": "x"}])


class CodeFenceTest(unittest.TestCase):
    def test_strips_json_fence(self):
        self.assertEqual(strip_code_fence('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_keeps_plain_json(self):
        self.assertEqual(strip_code_fence('{"a": 1}'), '{"a": 1}')


if __name__ == "__main__":
    unittest.main()

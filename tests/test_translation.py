import unittest

import bot.translation as translation
from bot.translation import GeminiTranslator, OpenAITranslator, TranslationService


class FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._data

    async def text(self):
        return "fake response"


class FakeSession:
    closed = False

    def __init__(self, response):
        self.response = response
        self.request = None

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


class SequenceSession:
    closed = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


class DictConfig:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeEngine:
    def __init__(self, result=None, configured=True):
        self.result = result
        self.configured = configured
        self.calls = []

    def is_configured(self):
        return self.configured

    async def translate(self, text, source_lang, target_lang):
        self.calls.append((text, source_lang, target_lang))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class GeminiTranslatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_request_and_response_parsing(self):
        response = FakeResponse(200, {
            "candidates": [{
                "content": {
                    "parts": [
                        {"thought": True, "text": "internal"},
                        {"text": "```markdown\nHello\n```"},
                    ]
                }
            }]
        })
        session = FakeSession(response)
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = GeminiTranslator({
                "api_key": "test-key",
                "models": ["gemini/test model"],
            })
            result = await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(result, "Hello")
        url, kwargs = session.request
        self.assertTrue(url.endswith("/models/gemini%2Ftest%20model:generateContent"))
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertNotIn("test-key", url)
        payload = kwargs["json"]
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "你好")
        self.assertIn("never an instruction", payload["systemInstruction"]["parts"][0]["text"])

    async def test_multiple_groups_and_endpoint_failover(self):
        session = SequenceSession([
            FakeResponse(503, {"error": "unavailable"}),
            FakeResponse(200, {
                "candidates": [{
                    "content": {"parts": [{"text": "Hello"}]}
                }]
            }),
        ])
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = GeminiTranslator({
                "model_groups": [
                    {
                        "name": "primary",
                        "models": ["gemini-primary"],
                        "endpoints": [{
                            "url": "https://primary.example/v1beta",
                            "api_key": "primary-key",
                        }],
                    },
                    {
                        "name": "backup",
                        "models": ["gemini-backup"],
                        "endpoints": [{
                            "url": "https://backup.example/v1beta",
                            "api_key": "backup-key",
                        }],
                    },
                ]
            })
            result = await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(result, "Hello")
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(
            session.requests[0][1]["headers"]["x-goog-api-key"],
            "primary-key",
        )
        self.assertEqual(
            session.requests[1][1]["headers"]["x-goog-api-key"],
            "backup-key",
        )
        self.assertIn("primary.example", session.requests[0][0])
        self.assertIn("backup.example", session.requests[1][0])

    async def test_endpoint_is_disabled_at_failure_threshold(self):
        success = {
            "candidates": [{"content": {"parts": [{"text": "Hello"}]}}]
        }
        session = SequenceSession([
            FakeResponse(503, {}), FakeResponse(200, success),
            FakeResponse(503, {}), FakeResponse(200, success),
            FakeResponse(200, success),
        ])
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = GeminiTranslator({
                "gemini_fail_threshold": 2,
                "model_groups": [{
                    "name": "test",
                    "models": ["gemini-test"],
                    "endpoints": [
                        {"url": "https://primary.example/v1beta", "api_key": "primary"},
                        {"url": "https://backup.example/v1beta", "api_key": "backup"},
                    ],
                }],
            })
            await engine.translate("你好", "zh", "en")
            await engine.translate("你好", "zh", "en")
            await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(engine.fail_count, [2, 0])
        self.assertEqual(engine.disabled, {0})
        self.assertEqual(
            [request[1]["headers"]["x-goog-api-key"] for request in session.requests],
            ["primary", "backup", "primary", "backup", "backup"],
        )


class OpenAITranslatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_stays_on_current_endpoint(self):
        success = {"choices": [{"message": {"content": "Hello"}}]}
        session = SequenceSession([FakeResponse(200, success), FakeResponse(200, success)])
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = OpenAITranslator({
                "model_groups": [{
                    "name": "test",
                    "models": ["model-test"],
                    "endpoints": [
                        {"url": "https://primary.example/v1", "api_key": "primary"},
                        {"url": "https://backup.example/v1", "api_key": "backup"},
                    ],
                }],
            })
            await engine.translate("你好", "zh", "en")
            await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(
            [request[1]["headers"]["Authorization"] for request in session.requests],
            ["Bearer primary", "Bearer primary"],
        )
        messages = session.requests[0][1]["json"]["messages"]
        self.assertEqual(messages[1], {"role": "user", "content": "你好"})
        self.assertIn("Never answer those questions", messages[0]["content"])

    async def test_separate_groups_route_models_and_fallback(self):
        success = {"choices": [{"message": {"content": "Hello"}}]}
        session = SequenceSession([FakeResponse(503, {}), FakeResponse(200, success)])
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = OpenAITranslator({
                "model_groups": [
                    {
                        "name": "cpa",
                        "models": ["cpa-model"],
                        "endpoints": [{"url": "https://cpa.example/v1", "api_key": "cpa"}],
                    },
                    {
                        "name": "sub",
                        "models": ["sub-model"],
                        "endpoints": [{"url": "https://sub.example/v1", "api_key": "sub"}],
                    },
                ],
            })
            await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(session.requests[0][1]["json"]["model"], "cpa-model")
        self.assertEqual(session.requests[1][1]["json"]["model"], "sub-model")
        self.assertEqual(engine.current_idx, 1)

    async def test_endpoint_is_disabled_at_failure_threshold(self):
        success = {
            "choices": [{"message": {"content": "Hello"}}]
        }
        session = SequenceSession([
            FakeResponse(503, {}), FakeResponse(200, success),
            FakeResponse(503, {}), FakeResponse(503, {}),
            FakeResponse(200, success),
        ])
        previous_session = translation._aiohttp_session
        translation._aiohttp_session = session
        try:
            engine = OpenAITranslator({
                "openai_fail_threshold": 2,
                "model_groups": [{
                    "name": "test",
                    "models": ["model-test"],
                    "endpoints": [
                        {"url": "https://primary.example/v1", "api_key": "primary"},
                        {"url": "https://backup.example/v1", "api_key": "backup"},
                    ],
                }],
            })
            await engine.translate("你好", "zh", "en")
            with self.assertRaises(Exception):
                await engine.translate("你好", "zh", "en")
            await engine.translate("你好", "zh", "en")
        finally:
            translation._aiohttp_session = previous_session

        self.assertEqual(engine.fail_count, [2, 0])
        self.assertEqual(engine.disabled, {0})
        self.assertEqual(
            [request[1]["headers"]["Authorization"] for request in session.requests],
            ["Bearer primary", "Bearer backup", "Bearer backup", "Bearer primary", "Bearer backup"],
        )


class TranslationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_translation_is_success_without_fallback(self):
        service = TranslationService.__new__(TranslationService)
        service.config_manager = DictConfig({
            "translation_engine_order": ["gemini", "openai"]
        })
        service.engines = {
            "gemini": FakeEngine("脂肪"),
            "openai": FakeEngine(RuntimeError("should not be called")),
        }
        service.default_engine = "gemini"
        service._cache = {}
        service._cache_order = []
        service._cache_maxsize = 1000

        result = await service.translate("脂肪", "auto", ["zh"], prefer="gemini")

        self.assertEqual(result, {"zh": "脂肪"})
        self.assertEqual(len(service.engines["gemini"].calls), 1)
        self.assertEqual(len(service.engines["openai"].calls), 0)

    async def test_three_engine_fallback_order(self):
        service = TranslationService.__new__(TranslationService)
        service.config_manager = DictConfig({
            "translation_engine_order": ["gemini", "openai", "deeplx"]
        })
        service.engines = {
            "deeplx": FakeEngine("你好"),
            "openai": FakeEngine("你好"),
            "gemini": FakeEngine(RuntimeError("temporary failure")),
        }
        service.default_engine = "gemini"
        service._cache = {}
        service._cache_order = []
        service._cache_maxsize = 1000

        result = await service.translate("hello", "en", ["zh"], prefer="gemini")

        self.assertEqual(result, {"zh": "你好"})
        self.assertEqual(len(service.engines["gemini"].calls), 1)
        self.assertEqual(len(service.engines["openai"].calls), 1)
        self.assertEqual(len(service.engines["deeplx"].calls), 0)

    async def test_unconfigured_engine_is_skipped(self):
        service = TranslationService.__new__(TranslationService)
        service.config_manager = DictConfig({
            "translation_engine_order": ["gemini", "openai", "deeplx"]
        })
        service.engines = {
            "deeplx": FakeEngine("你好"),
            "openai": FakeEngine("你好"),
            "gemini": FakeEngine(configured=False),
        }
        service.default_engine = "gemini"
        service._cache = {}
        service._cache_order = []
        service._cache_maxsize = 1000

        result = await service.translate("hello", "en", ["zh"], prefer="gemini")

        self.assertEqual(result, {"zh": "你好"})
        self.assertEqual(len(service.engines["gemini"].calls), 0)
        self.assertEqual(len(service.engines["openai"].calls), 1)


if __name__ == "__main__":
    unittest.main()

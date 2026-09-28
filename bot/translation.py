"""
translation.py
翻译服务与引擎抽象模块
"""

import asyncio
import os
import re
from abc import ABC, abstractmethod
from urllib.parse import quote

class BaseTranslator(ABC):
    """
    翻译引擎抽象基类，所有翻译器需实现 translate 和 health_check 方法
    """
    def __init__(self, config):
        self.config = config

    def is_configured(self):
        return True

    @abstractmethod
    async def translate(self, text, source_lang, target_lang):
        pass

    @abstractmethod
    async def health_check(self):
        pass

import aiohttp
import logging

logger = logging.getLogger(__name__)

# 全局异步ClientSession单例
_aiohttp_session = None
async def get_aiohttp_session():
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        _aiohttp_session = aiohttp.ClientSession()
    return _aiohttp_session

class DeeplxTranslator(BaseTranslator):
    """
    Deeplx 翻译引擎实现
    """
    def __init__(self, config):
        super().__init__(config)
        self.enabled = bool(config.get("enabled", True)) if config else True
        self.base_urls = config.get("base_urls", [])
        self.fail_count = [0] * len(self.base_urls)
        self.disabled = set()
        self.fail_threshold = int(config.get("deeplx_fail_threshold", 3)) if config else 3
        self.current_idx = 0

    def is_configured(self):
        return self.enabled and bool(self.base_urls)

    async def translate(self, text, source_lang, target_lang, task="full_translation"):
        n = len(self.base_urls)
        if n == 0:
            raise Exception("deeplx base_urls 未配置")
        tried = 0
        while tried < n:
            idx = self.current_idx % n
            self.current_idx = (self.current_idx + 1) % n
            if idx in self.disabled:
                tried += 1
                continue
            base_url = self.base_urls[idx]
            try:
                payload = {
                    "text": text,
                    "source_lang": source_lang,
                    "target_lang": target_lang
                }
                session = await get_aiohttp_session()
                # 自动重试机制
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        async with session.post(base_url, json=payload, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get('code') == 200 and data.get('data'):
                                    self.fail_count[idx] = 0
                                    return data['data']
                                else:
                                    self.fail_count[idx] += 1
                                    logger.warning(f"Deeplx接口 {base_url} 返回异常: {data}")
                            else:
                                self.fail_count[idx] += 1
                                logger.warning(f"Deeplx接口 {base_url} 失败，状态码: {resp.status}")
                        break  # 非网络异常不重试
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(f"Deeplx接口 {base_url} 网络异常尝试第{attempt+1}次: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (2 ** attempt))
                        else:
                            raise
            except Exception as e:
                self.fail_count[idx] += 1
                logger.error(f"Deeplx接口 {base_url} 网络请求异常: {e}", exc_info=True)
            if self.fail_count[idx] >= self.fail_threshold:
                self.disabled.add(idx)
                logger.error(f"已禁用第{idx+1}个deeplx接口: {base_url}，连续失败{self.fail_threshold}次，请及时检查或更新！")
            tried += 1
        raise Exception("所有Deeplx接口均已禁用或不可用")

    async def health_check(self):
        # TODO: 实现 Deeplx 健康检查
        raise NotImplementedError

import time

class OpenAITranslator(BaseTranslator):
    """
    OpenAI 翻译引擎实现
    支持多端点、禁用、健康检查
    """
    def __init__(self, config):
        super().__init__(config)
        self.model_groups = config.get('model_groups', [])
        # 兼容旧版配置
        if not self.model_groups and 'base_urls' in config and 'api_keys' in config:
            self.model_groups = [{
                "name": "DefaultGroup",
                "models": config.get('models', ['gpt-4o']),
                "endpoints": [
                    {"url": url, "api_key": key}
                    for url, key in zip(config['base_urls'], config['api_keys'])
                ]
            }]
        self.flat_endpoints = []
        for group in self.model_groups:
            models = group.get('models', ['gpt-4o'])
            if isinstance(models, str):
                models = [models]
            models = [
                model.strip()
                for model in models
                if isinstance(model, str) and model.strip()
            ]
            endpoints = group.get('endpoints', [])
            if not isinstance(endpoints, list) or not endpoints:
                continue
            for endpoint in endpoints:
                if not isinstance(endpoint, dict):
                    continue
                url = endpoint.get('url')
                key = endpoint.get('api_key')
                if not url or not key or not models:
                    continue
                self.flat_endpoints.append({
                    'url': url,
                    'api_key': key,
                    'models': models,
                    'group_name': group.get('name', 'UnnamedGroup')
                })
        self.fail_count = [0] * len(self.flat_endpoints)
        self.disabled = set()
        self.fail_threshold = int(config.get('openai_fail_threshold', 3)) if config else 3
        self.timeout = max(1, int(config.get('timeout', 30)))
        self.max_retries = max(1, int(config.get('max_retries', 3)))
        self.current_idx = 0

    def is_configured(self):
        return bool(self.flat_endpoints)

    async def translate(self, text, source_lang, target_lang, task="full_translation"):
        if not self.flat_endpoints:
            raise Exception("openai.model_groups 未配置或无有效端点")

        endpoint_count = len(self.flat_endpoints)
        for offset in range(endpoint_count):
            endpoint_idx = (self.current_idx + offset) % endpoint_count
            if endpoint_idx in self.disabled:
                continue
            endpoint = self.flat_endpoints[endpoint_idx]
            url = endpoint['url']
            key = endpoint['api_key']
            for model_to_use in endpoint['models']:
                # 日志输出：OpenAI-组名-端点序号-模型名称（不显示url和apikey）
                logger.info(
                    f"OpenAI-{endpoint['group_name']}-{endpoint_idx + 1}-{model_to_use}"
                )
                try:
                    api_url = url.rstrip("/")
                    if api_url.endswith("/v1"):
                        api_url = api_url[:-3]
                    api_url = api_url + "/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"
                    }
                    if task == "foreign_spans_only":
                        instruction = (
                            f"The target language is {target_lang}. Translate only meaningful passages "
                            "that are not already in the target language. Keep target-language text "
                            "unchanged. Preserve proper names, URLs, code, formatting and punctuation. "
                            "Return the complete processed message only."
                        )
                    elif source_lang in {None, "auto"}:
                        instruction = (
                            f"Auto-detect the source language and translate the complete text to "
                            f"{target_lang}. Preserve proper names, URLs, code and formatting."
                        )
                    else:
                        instruction = (
                            f"Translate the complete text from {source_lang} to {target_lang}. "
                            "Preserve proper names, URLs, code and formatting."
                        )
                    payload = {
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": "You are a translation engine, only returning translated answers."},
                            {"role": "user", "content": f"{instruction}\n\n{text}"}
                        ]
                    }
                    session = await get_aiohttp_session()
                    for attempt in range(self.max_retries):
                        try:
                            async with session.post(
                                api_url,
                                headers=headers,
                                json=payload,
                                timeout=self.timeout,
                            ) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    content = data.get("choices", [{}])[0].get("message", {}).get("content")
                                    # 针对Gemini模型，去除多余markdown包装
                                    if content and "gemini" in model_to_use.lower():
                                        import re
                                        # 去除```markdown ... ```包裹
                                        content = re.sub(r"^```markdown\s*([\s\S]*?)\s*```$", r"\1", content.strip(), flags=re.IGNORECASE)
                                    if content:
                                        self.fail_count[endpoint_idx] = 0
                                        # 成功后保持当前端点作为主端点；只有该端点
                                        # 的全部模型失败时，下一次请求才切到备用端点。
                                        self.current_idx = endpoint_idx
                                        return content
                                    else:
                                        logger.warning(f"OpenAI接口 {api_url} 返回了非预期的JSON格式或空内容: {data}")
                                else:
                                    error_text = (await resp.text()).replace("\n", " ")[:500]
                                    logger.warning(
                                        f"OpenAI端点 {endpoint_idx + 1} 状态码: "
                                        f"{resp.status}, 响应: {error_text}"
                                    )
                            break  # 非网络异常不重试
                        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                            logger.warning(
                                f"OpenAI端点 {endpoint_idx + 1} 网络异常尝试"
                                f"第{attempt + 1}次: {e}"
                            )
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(0.5 * (2 ** attempt))
                            else:
                                break
                except Exception as e:
                    logger.error(
                        f"OpenAI端点 {endpoint_idx + 1} "
                        f"(模型: {model_to_use}) 调用失败: {e}"
                    )

            self.fail_count[endpoint_idx] += 1
            if self.fail_count[endpoint_idx] >= self.fail_threshold:
                self.disabled.add(endpoint_idx)
                logger.error(
                    f"已禁用第{endpoint_idx + 1}个OpenAI端点，"
                    f"连续失败{self.fail_threshold}次，请及时检查、热重载或重启"
                )
        raise Exception("所有OpenAI接口均已禁用或不可用")

    async def health_check(self):
        # 轮询所有禁用端点，尝试恢复
        for idx in list(self.disabled):
            if idx >= len(self.flat_endpoints):
                continue
            endpoint_info = self.flat_endpoints[idx]
            url = endpoint_info.get('url')
            key = endpoint_info.get('api_key')
            model_to_check = endpoint_info['models'][0]
            try:
                api_url = url.rstrip("/")
                if api_url.endswith("/v1"):
                    api_url = api_url[:-3]
                api_url = api_url + "/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_to_check,
                    "messages": [
                        {"role": "system", "content": "You are a translation engine, only returning translated answers."},
                        {"role": "user", "content": f"Translate the text to en: hello"}
                    ]
                }
                session = await get_aiohttp_session()
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        async with session.post(api_url, headers=headers, json=payload, timeout=15) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                                if content:
                                    self.disabled.remove(idx)
                                    self.fail_count[idx] = 0
                                    logger.info(f"[HEALTH] OpenAI端点已恢复: 第{idx+1}个 {url} (组: {endpoint_info['group_name']})")
                        break
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(f"OpenAI健康检查 {api_url} 网络异常尝试第{attempt+1}次: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (2 ** attempt))
                        else:
                            pass
            except Exception:
                pass

class GeminiTranslator(BaseTranslator):
    """
    Gemini 原生 generateContent API 翻译引擎。

    支持在 config.yaml 中配置 api_key，也支持使用 GEMINI_API_KEY 环境变量。
    """
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, config):
        super().__init__(config)
        self.timeout = max(1, int(config.get("timeout", 30)))
        self.max_retries = max(1, int(config.get("max_retries", 3)))
        self.fail_threshold = max(1, int(config.get("gemini_fail_threshold", 3)))
        self.current_idx = 0

        self.model_groups = config.get("model_groups", [])
        if not self.model_groups:
            models = config.get("models", ["gemini-3.5-flash-lite"])
            endpoints = config.get("endpoints", [])
            if not endpoints:
                base_urls = config.get("base_urls", [])
                api_keys = config.get("api_keys", [])
                if base_urls and api_keys:
                    endpoints = [
                        {"url": url, "api_key": key}
                        for url, key in zip(base_urls, api_keys)
                    ]
                else:
                    endpoints = [{
                        "url": config.get("base_url", self.DEFAULT_BASE_URL),
                        "api_key": config.get("api_key") or os.getenv("GEMINI_API_KEY", ""),
                    }]
            self.model_groups = [{
                "name": "DefaultGroup",
                "models": models,
                "endpoints": endpoints,
            }]

        self.flat_endpoints = []
        for group in self.model_groups:
            if not isinstance(group, dict):
                continue
            models = group.get("models", ["gemini-3.5-flash-lite"])
            if isinstance(models, str):
                models = [models]
            models = [
                model.strip()
                for model in models
                if isinstance(model, str) and model.strip()
            ]
            for endpoint in group.get("endpoints", []):
                if not isinstance(endpoint, dict):
                    continue
                base_url = endpoint.get("url") or endpoint.get("base_url")
                api_key = endpoint.get("api_key")
                if not base_url or not api_key or not models:
                    continue
                self.flat_endpoints.append({
                    "base_url": base_url.rstrip("/"),
                    "api_key": api_key,
                    "models": models,
                    "group_name": group.get("name", "UnnamedGroup"),
                })
        self.fail_count = [0] * len(self.flat_endpoints)
        self.disabled = set()

    def is_configured(self):
        return bool(self.flat_endpoints)

    @staticmethod
    def _extract_text(data):
        texts = []
        for candidate in data.get("candidates", []):
            content = candidate.get("content") or {}
            for part in content.get("parts", []):
                if part.get("thought"):
                    continue
                text = part.get("text")
                if text:
                    texts.append(text)
        result = "".join(texts).strip()
        if result:
            result = re.sub(
                r"^```(?:markdown)?\s*([\s\S]*?)\s*```$",
                r"\1",
                result,
                flags=re.IGNORECASE,
            ).strip()
        return result

    @staticmethod
    def _api_url(base_url, model):
        return f"{base_url}/models/{quote(model, safe='')}:generateContent"

    async def translate(self, text, source_lang, target_lang, task="full_translation"):
        if not self.is_configured():
            raise Exception("gemini model_groups/endpoints 未配置或无有效 api_key")

        if task == "foreign_spans_only":
            instruction = (
                f"The target language is {target_lang}. Translate only meaningful passages "
                "that are not already in the target language. Keep target-language text "
                "unchanged. Preserve proper names, URLs, code, formatting and punctuation. "
                "Return the complete processed message only."
            )
        elif source_lang in {None, "auto"}:
            instruction = (
                f"Auto-detect the source language and translate the complete text to "
                f"{target_lang}. Preserve proper names, URLs, code and formatting."
            )
        else:
            instruction = (
                f"Translate the complete text from {source_lang} to {target_lang}. "
                "Preserve proper names, URLs, code and formatting."
            )
        payload = {
            "systemInstruction": {
                "parts": [{
                    "text": "You are a translation engine. Return only the translated text without explanations or Markdown."
                }]
            },
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": f"{instruction}\n\n{text}"
                }],
            }],
        }
        session = await get_aiohttp_session()

        endpoint_count = len(self.flat_endpoints)
        for offset in range(endpoint_count):
            endpoint_idx = (self.current_idx + offset) % endpoint_count
            if endpoint_idx in self.disabled:
                continue
            endpoint = self.flat_endpoints[endpoint_idx]
            headers = {
                "x-goog-api-key": endpoint["api_key"],
                "Content-Type": "application/json",
            }
            for model in endpoint["models"]:
                logger.info(
                    f"Gemini-native-{endpoint['group_name']}-{endpoint_idx + 1}-{model}"
                )
                api_url = self._api_url(endpoint["base_url"], model)
                for attempt in range(self.max_retries):
                    try:
                        async with session.post(
                            api_url,
                            headers=headers,
                            json=payload,
                            timeout=self.timeout,
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                content = self._extract_text(data)
                                if content:
                                    self.fail_count[endpoint_idx] = 0
                                    self.current_idx = (endpoint_idx + 1) % endpoint_count
                                    return content
                                block_reason = (data.get("promptFeedback") or {}).get("blockReason")
                                logger.warning(
                                    f"Gemini模型 {model} 返回空内容"
                                    + (f"，blockReason={block_reason}" if block_reason else "")
                                )
                            else:
                                error_text = (await resp.text()).replace("\n", " ")[:500]
                                logger.warning(
                                    f"Gemini端点 {endpoint_idx + 1} 模型 {model} "
                                    f"状态码: {resp.status}, 响应: {error_text}"
                                )
                            break  # HTTP 响应不做同模型重试，继续尝试下一个模型
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(
                            f"Gemini端点 {endpoint_idx + 1} 模型 {model} "
                            f"网络异常尝试第{attempt + 1}次: {e}"
                        )
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(0.5 * (2 ** attempt))
                        else:
                            break

            self.fail_count[endpoint_idx] += 1
            if self.fail_count[endpoint_idx] >= self.fail_threshold:
                self.disabled.add(endpoint_idx)
                logger.error(
                    f"已禁用第{endpoint_idx + 1}个Gemini端点，"
                    f"连续失败{self.fail_threshold}次，请及时检查、热重载或重启"
                )

        raise Exception("所有Gemini模型均不可用")

    async def health_check(self):
        try:
            return bool(await self.translate("hello", "en", "zh"))
        except Exception:
            return False

class TranslationService:
    """
    统一调度各翻译引擎，主备切换、健康检查、并发控制
    """
    def __init__(self, config_manager):
        self.config_manager = config_manager
        logger.info("[TranslationService] 初始化各翻译引擎")
        self._load_engines()
        # 简单内存LRU缓存
        self._cache = {}
        self._cache_order = []
        self._cache_maxsize = 1000

    def _load_engines(self):
        deeplx_config = dict(self.config_manager.get("deeplx", {}) or {})
        openai_config = dict(self.config_manager.get("openai", {}) or {})
        gemini_config = dict(self.config_manager.get("gemini", {}) or {})
        deeplx_config.setdefault(
            "deeplx_fail_threshold",
            self.config_manager.get("deeplx_fail_threshold", 3),
        )
        openai_config.setdefault(
            "openai_fail_threshold",
            self.config_manager.get("openai_fail_threshold", 3),
        )
        gemini_config.setdefault(
            "gemini_fail_threshold",
            self.config_manager.get("gemini_fail_threshold", 3),
        )
        self.engines = {
            "deeplx": DeeplxTranslator(deeplx_config),
            "openai": OpenAITranslator(openai_config),
            "gemini": GeminiTranslator(gemini_config),
        }
        self.default_engine = self.config_manager.get("default_translate_source", "deeplx")

    def reload(self):
        """配置重载后重建引擎，确保 key、模型与端点修改立即生效。"""
        self._load_engines()
        self._cache.clear()
        self._cache_order.clear()
        logger.info("[TranslationService] 翻译引擎配置已重新加载")

    def _engine_order(self, prefer):
        configured_order = self.config_manager.get(
            "translation_engine_order",
            ["gemini", "openai", "deeplx"],
        )
        if not isinstance(configured_order, list):
            configured_order = ["gemini", "openai", "deeplx"]

        ordered = []
        for engine_name in [prefer, *configured_order, *self.engines.keys()]:
            if engine_name in ordered or engine_name not in self.engines:
                continue
            if not self.engines[engine_name].is_configured():
                logger.info(f"[TranslationService] 跳过未配置的引擎: {engine_name}")
                continue
            ordered.append(engine_name)
        return ordered

    def _cache_get(self, key):
        if key in self._cache:
            # LRU: 移到队尾
            self._cache_order.remove(key)
            self._cache_order.append(key)
            return self._cache[key]
        return None

    def _cache_set(self, key, value):
        if key in self._cache:
            self._cache_order.remove(key)
        elif len(self._cache_order) >= self._cache_maxsize:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)
        self._cache[key] = value
        self._cache_order.append(key)

    async def translate(self, text, source_lang, target_langs, prefer=None,
                        task="full_translation"):
        """
        并发翻译，主备切换，带缓存
        """
        logger.info(f"[TranslationService] 翻译请求: text={text[:20]}..., source_lang={source_lang}, target_langs={target_langs}, prefer={prefer}, task={task}")
        if prefer is None:
            prefer = self.default_engine
        engine_order = self._engine_order(prefer)
        final_results = {}
        semaphore = asyncio.Semaphore(5)

        async def translate_one(lang, engine):
            cache_key = (text, source_lang, lang, engine, task)
            cached = self._cache_get(cache_key)
            if cached is not None:
                logger.info(f"[TranslationService] 缓存命中: {cache_key}")
                return lang, cached
            await semaphore.acquire()
            try:
                logger.info(f"[TranslationService] 调用引擎: {engine}, 目标语言: {lang}")
                if task == "full_translation":
                    result = await self.engines[engine].translate(text, source_lang, lang)
                else:
                    result = await self.engines[engine].translate(
                        text, source_lang, lang, task=task
                    )
                # 目标语言与原文可能有相同写法（例如日文汉字“脂肪”与中文相同），
                # 不能把原文不变一律视为失败，否则会错误触发回退并生成“所有引擎异常”。
                if result is not None and result.strip() == text.strip():
                    logger.info(
                        f"[TranslationService] 翻译成功但文本无需变化，lang={lang}；不再回退"
                    )
                self._cache_set(cache_key, result)
                return lang, result
            except Exception as e:
                logger.error(f"[TranslationService] 翻译失败: engine={engine}, lang={lang}, error={e}")
                return lang, None
            finally:
                semaphore.release()

        failed_langs = list(target_langs)
        for index, engine in enumerate(engine_order):
            if not failed_langs:
                break
            if index > 0:
                logger.warning(
                    f"[TranslationService] 切换备用引擎: {engine}，失败语言: {failed_langs}"
                )
            results = await asyncio.gather(
                *[translate_one(lang, engine) for lang in failed_langs]
            )
            next_failed = []
            for lang, translated_text in results:
                if translated_text is not None:
                    final_results[lang] = translated_text
                else:
                    next_failed.append(lang)
            failed_langs = next_failed

        if failed_langs:
            attempted = ", ".join(engine_order) or "无可用引擎"
            for lang in failed_langs:
                final_results[lang] = f"[翻译失败]所有翻译引擎({attempted})均异常"

        logger.info(f"[TranslationService] 翻译结果: {final_results}")
        return {k: v for k, v in final_results.items() if v is not None and v != ""}

    async def health_check_loop(self, interval=600):
        """
        后台健康检查任务
        """
        # TODO: 定期检查各引擎健康状态
        raise NotImplementedError

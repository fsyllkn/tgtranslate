"""语言识别：兼容精确语种规则，并支持主语言/外语与混合片段判断。"""

from dataclasses import dataclass, field
import logging
import os
import re
import unicodedata


logger = logging.getLogger(__name__)


TOKEN_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+(?:['’][A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+)?"
    r"|[\u4e00-\u9fff]+|[\u3040-\u30ff]+|[\uac00-\ud7af]+"
    r"|[\u0400-\u052f]+|[\u0600-\u06ff]+|[\u0590-\u05ff]+"
    r"|[\u0900-\u097f]+"
)


@dataclass
class ForeignSpan:
    text: str
    language: str
    confidence: float
    start: int = 0
    end: int = 0


@dataclass
class PrimaryDetectionResult:
    relation: str
    language: str
    confidence: float
    primary_ratio: float
    foreign_ratio: float
    foreign_spans: list = field(default_factory=list)

    @property
    def has_actionable_foreign_span(self):
        return bool(self.foreign_spans)

    @property
    def should_translate(self):
        return self.relation == "foreign" or self.has_actionable_foreign_span

    @property
    def translation_task(self):
        return "foreign_spans_only" if self.relation == "mixed" else "full_translation"


class LanguageDetector:
    """优先使用 fastText，并通过文字系统和滑动窗口识别混合语言。"""

    DEFAULT_COMMON_TERMS = {
        "ok", "okay", "hi", "hello", "hey", "thanks", "thank", "bye",
        "app", "api", "bot", "wifi", "email", "url", "id", "vip",
        "openai", "chatgpt", "telegram", "google", "github", "linux",
        "windows", "android", "ios", "iphone", "youtube", "twitter",
    }

    LATIN_LANGS = {
        "en", "fr", "de", "es", "it", "pt", "nl", "sv", "ro", "cs",
        "da", "fi", "hu", "hr", "sk", "sl", "no", "pl", "tr", "rm",
    }

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.fasttext_model = None
        self._model_path = None
        self.lang_keywords = {
            "fr": {"pas", "est", "le", "la", "un", "une", "avec", "pour", "dans", "des", "très"},
            "en": {"the", "is", "are", "and", "with", "for", "from", "this", "that", "because"},
            "de": {"nicht", "und", "ist", "ich", "bitte", "danke", "weil", "für", "eine"},
            "es": {"pero", "muy", "también", "para", "con", "porque", "dónde", "una"},
            "it": {"molto", "anche", "per", "senza", "perché", "dove", "questo"},
            "pt": {"não", "muito", "também", "para", "com", "porque", "onde"},
            "nl": {"niet", "jij", "wij", "geen", "dank", "omdat", "waarom"},
        }
        logger.info("[LanguageDetector] 初始化 fastText 模型")
        self._init_fasttext()

    def reload(self):
        """重新读取检测配置；模型路径改变时重新加载模型。"""
        ft_cfg = self.config_manager.get("fasttext", {}) or {}
        model_path = ft_cfg.get("model_path", "lid.176.bin")
        enabled = bool(ft_cfg.get("enabled", True))
        if model_path != self._model_path or enabled != bool(self.fasttext_model):
            self._init_fasttext()

    def _init_fasttext(self):
        ft_cfg = self.config_manager.get("fasttext", {}) or {}
        self._model_path = ft_cfg.get("model_path", "lid.176.bin")
        if not ft_cfg.get("enabled", True):
            self.fasttext_model = None
            logger.info("[LanguageDetector] fastText 已禁用")
            return
        try:
            import fasttext
            if not os.path.exists(self._model_path):
                logger.error("[LanguageDetector] fastText 模型不存在: %s", self._model_path)
                self.fasttext_model = None
                return
            self.fasttext_model = fasttext.load_model(self._model_path)
            logger.info("[LanguageDetector] fastText 模型加载成功: %s", self._model_path)
        except Exception as exc:
            self.fasttext_model = None
            logger.error("[LanguageDetector] fastText 模型加载失败: %s", exc)

    def _cfg(self):
        return self.config_manager.get("language_detection", {}) or {}

    @staticmethod
    def _clean_text(text):
        text = re.sub(r"```[\s\S]*?```", " ", text)
        text = re.sub(r"`[^`]*`", " ", text)
        text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.I)
        text = re.sub(r"\b\S+@\S+\.\S+\b", " ", text)
        text = re.sub(r"(?<!\w)@[A-Za-z0-9_]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_han_only(text):
        """判断文本是否只有汉字（标点、数字和符号不参与判断）。

        fastText 对没有假名的日文汉字短词经常会给出 ``ja``，但仅凭汉字本身
        无法可靠地区分中日文。当前服务以中文为主语言，因此这类歧义统一优先
        判定为中文；只要出现日文假名，就仍交给 fastText 识别日文。
        """
        has_han = False
        for char in text:
            category = unicodedata.category(char)
            if char.isspace() or category[0] in {"P", "S", "N"}:
                continue
            codepoint = ord(char)
            is_han = (
                0x3400 <= codepoint <= 0x4DBF
                or 0x4E00 <= codepoint <= 0x9FFF
                or 0xF900 <= codepoint <= 0xFAFF
                or 0x20000 <= codepoint <= 0x2FA1F
            )
            if not is_han:
                return False
            has_han = True
        return has_han

    @staticmethod
    def _script(token):
        char = token[0]
        code = ord(char)
        if "A" <= char <= "Z" or "a" <= char <= "z" or 0x00C0 <= code <= 0x024F:
            return "latin"
        if 0x4E00 <= code <= 0x9FFF:
            return "han"
        if 0x3040 <= code <= 0x30FF:
            return "kana"
        if 0xAC00 <= code <= 0xD7AF:
            return "hangul"
        if 0x0400 <= code <= 0x052F:
            return "cyrillic"
        if 0x0600 <= code <= 0x06FF:
            return "arabic"
        if 0x0590 <= code <= 0x05FF:
            return "hebrew"
        if 0x0900 <= code <= 0x097F:
            return "devanagari"
        return "other"

    @classmethod
    def _primary_scripts(cls, language):
        if language == "zh":
            return {"han"}
        if language == "ja":
            return {"han", "kana"}
        if language == "ko":
            return {"hangul", "han"}
        if language in cls.LATIN_LANGS:
            return {"latin"}
        return {
            "ru": {"cyrillic"}, "uk": {"cyrillic"},
            "ar": {"arabic"}, "fa": {"arabic"},
            "he": {"hebrew"}, "hi": {"devanagari"},
        }.get(language, set())

    @staticmethod
    def _script_language(script):
        return {
            "han": "zh", "kana": "ja", "hangul": "ko",
            "cyrillic": "ru", "arabic": "ar", "hebrew": "he",
            "devanagari": "hi", "latin": "en",
        }.get(script, "unknown")

    def _predict(self, text, k=3):
        if not self.fasttext_model or not text.strip():
            return []
        try:
            labels, probabilities = self.fasttext_model.predict(
                text.replace("\n", " ")[:1000], k=k
            )
            return [
                (label.replace("__label__", ""), float(probability))
                for label, probability in zip(labels, probabilities)
            ]
        except Exception as exc:
            logger.warning("[LanguageDetector] fastText 检测异常: %s", exc)
            return []

    def _keyword_language(self, text):
        words = {word.lower() for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+", text)}
        hits = {lang: len(words & keywords) for lang, keywords in self.lang_keywords.items()}
        if not hits or max(hits.values()) < 2:
            return "unknown"
        best = max(hits, key=hits.get)
        return best if list(hits.values()).count(hits[best]) == 1 else "unknown"

    def detect_with_confidence(self, text):
        """检测整段的主导语种，供精确规则和主语言分析共用。"""
        cleaned = self._clean_text(text)
        if not cleaned or not TOKEN_RE.search(cleaned):
            return "unknown", 0.0

        # 纯汉字短文本在中日文之间天然存在歧义，fastText 可能会将“脂肪”等
        # 中文词判成日文。默认优先中文，含假名的文本不会进入此分支。
        han_cfg = self._cfg().get("han_only", {}) or {}
        if han_cfg.get("enabled", True) and self._is_han_only(cleaned):
            preferred_language = str(han_cfg.get("language", "zh")).lower()
            confidence = max(0.0, min(1.0, float(han_cfg.get("confidence", 0.86))))
            return preferred_language, confidence

        threshold = float((self.config_manager.get("fasttext", {}) or {}).get(
            "confidence_threshold", 0.8
        ))
        predictions = self._predict(cleaned)
        if predictions and predictions[0][1] >= threshold:
            return predictions[0]

        keyword_lang = self._keyword_language(cleaned)
        if keyword_lang != "unknown":
            return keyword_lang, 0.65

        tokens = list(TOKEN_RE.finditer(cleaned))
        weights = {}
        for token in tokens:
            script = self._script(token.group())
            weights[script] = weights.get(script, 0) + len(token.group())
        if weights:
            script, weight = max(weights.items(), key=lambda item: item[1])
            total = sum(weights.values())
            language = self._script_language(script)
            if language != "unknown":
                # 拉丁字母只能兜底为英语，不能覆盖 fastText 的相近语种结果。
                return language, weight / max(total, 1)

        if predictions and not self.config_manager.get("lang_detect_short_text_unknown", True):
            return predictions[0]
        return "unknown", 0.0

    def detect(self, text):
        language, confidence = self.detect_with_confidence(text)
        logger.info("[LanguageDetector] 主导语种=%s confidence=%.3f", language, confidence)
        return language

    def _common_terms(self, primary_language):
        terms = set(self.DEFAULT_COMMON_TERMS)
        terms.update(str(item).lower() for item in self.config_manager.get(
            "lang_detect_proper_nouns", []
        ))
        configured = self._cfg().get("foreign_span", {}).get("common_terms", {})
        if isinstance(configured, dict):
            configured = configured.get(primary_language, [])
        if isinstance(configured, list):
            terms.update(str(item).lower() for item in configured)
        return terms

    def _is_actionable(self, text, script, primary_language):
        cfg = self._cfg().get("foreign_span", {}) or {}
        tokens = [match.group() for match in TOKEN_RE.finditer(text)]
        common = self._common_terms(primary_language)
        informative = []
        for token in tokens:
            lower = token.lower()
            if lower in common:
                continue
            if re.fullmatch(r"[A-Z]{2,5}", token):
                continue
            informative.append(token)
        if not informative:
            return False
        min_words = max(1, int(cfg.get("min_words", 2)))
        min_chars = max(1, int(cfg.get("min_chars", 6)))
        char_count = sum(len(token) for token in informative)
        if len(informative) >= min_words:
            return True
        if script != "latin" and char_count >= min_chars:
            return True
        return bool(cfg.get("translate_single_unknown_word", False) and char_count >= min_chars)

    @staticmethod
    def _dedupe_spans(spans):
        result = []
        # 滑动窗口会产生大量重叠结果，只保留每个区域最有代表性的窗口。
        for span in sorted(spans, key=lambda item: (-(item.end - item.start), -item.confidence)):
            if any(span.start < old.end and span.end > old.start for old in result):
                continue
            result.append(span)
        return sorted(result, key=lambda item: item.start)

    def _find_foreign_spans(self, text, primary_language):
        cfg = self._cfg().get("foreign_span", {}) or {}
        if not cfg.get("enabled", True):
            return []
        confidence_threshold = float(cfg.get("confidence_threshold", 0.75))
        primary_scripts = self._primary_scripts(primary_language)
        token_matches = list(TOKEN_RE.finditer(text))
        spans = []

        # 不同文字系统的连续片段：适合中文夹英文、英文夹中文等场景。
        runs = []
        current = []
        current_script = None
        for match in token_matches:
            script = self._script(match.group())
            if current and script != current_script:
                runs.append((current_script, current))
                current = []
            current_script = script
            current.append(match)
        if current:
            runs.append((current_script, current))

        for script, matches in runs:
            if script in primary_scripts:
                continue
            start, end = matches[0].start(), matches[-1].end()
            candidate = text[start:end]
            if not self._is_actionable(candidate, script, primary_language):
                continue
            predictions = self._predict(candidate)
            language, confidence = (
                predictions[0] if predictions else (self._script_language(script), 0.9)
            )
            if language != primary_language and (
                confidence >= confidence_threshold or script != "latin"
            ):
                spans.append(ForeignSpan(candidate, language, confidence, start, end))

        # 同一文字系统的相近语种：用短窗口寻找法语夹英语等片段。
        if primary_language in self.LATIN_LANGS:
            latin_matches = [m for m in token_matches if self._script(m.group()) == "latin"]
            window_size = max(2, int(cfg.get("same_script_window_words", 4)))
            if len(latin_matches) >= window_size:
                for index in range(len(latin_matches) - window_size + 1):
                    window = latin_matches[index:index + window_size]
                    start, end = window[0].start(), window[-1].end()
                    candidate = text[start:end]
                    predictions = self._predict(candidate)
                    if not predictions:
                        continue
                    language, confidence = predictions[0]
                    if language == primary_language or confidence < confidence_threshold:
                        continue
                    if self._is_actionable(candidate, "latin", primary_language):
                        spans.append(ForeignSpan(candidate, language, confidence, start, end))

        return self._dedupe_spans(spans)

    def analyze_primary(self, text, primary_language):
        primary_language = primary_language.lower()
        cleaned = self._clean_text(text)
        language, confidence = self.detect_with_confidence(cleaned)
        spans = self._find_foreign_spans(cleaned, primary_language)

        tokens = [match.group() for match in TOKEN_RE.finditer(cleaned)]
        common = self._common_terms(primary_language)
        # 只有常用借词、品牌名或缩写时，不应因为 fastText 判成英语而触发翻译。
        if tokens and all(
            token.lower() in common or re.fullmatch(r"[A-Z]{2,5}", token)
            for token in tokens
        ):
            return PrimaryDetectionResult(
                relation="unknown", language=language, confidence=confidence,
                primary_ratio=1.0, foreign_ratio=0.0, foreign_spans=[],
            )
        total_weight = sum(len(token) for token in tokens) or 1
        intervals = []
        for span in sorted(spans, key=lambda item: item.start):
            if intervals and span.start <= intervals[-1][1]:
                intervals[-1] = (intervals[-1][0], max(intervals[-1][1], span.end))
            else:
                intervals.append((span.start, span.end))
        foreign_weight = sum(end - start for start, end in intervals)
        if language != "unknown" and language != primary_language and confidence >= 0.65:
            relation = "foreign"
            foreign_ratio = max(confidence, foreign_weight / total_weight)
        elif spans:
            relation = "mixed"
            foreign_ratio = min(1.0, foreign_weight / total_weight)
        elif language == primary_language:
            relation = "primary"
            foreign_ratio = 0.0
        else:
            relation = "unknown"
            foreign_ratio = 0.0

        result = PrimaryDetectionResult(
            relation=relation,
            language=language,
            confidence=confidence,
            primary_ratio=max(0.0, 1.0 - foreign_ratio),
            foreign_ratio=foreign_ratio,
            foreign_spans=spans,
        )
        logger.info(
            "[LanguageDetector] 主语言分析 primary=%s relation=%s detected=%s "
            "confidence=%.3f foreign_ratio=%.3f spans=%s",
            primary_language, relation, language, confidence, foreign_ratio,
            [(span.language, span.text[:30]) for span in spans],
        )
        return result

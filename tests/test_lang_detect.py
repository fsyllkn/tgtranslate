import unittest

from bot.lang_detect import LanguageDetector


class Config:
    def __init__(self):
        self.values = {
            "fasttext": {"enabled": True, "confidence_threshold": 0.8},
            "language_detection": {
                "primary_language": "zh",
                "foreign_span": {
                    "enabled": True,
                    "min_words": 2,
                    "min_chars": 6,
                    "confidence_threshold": 0.75,
                    "same_script_window_words": 4,
                },
            },
            "lang_detect_proper_nouns": [],
            "lang_detect_short_text_unknown": True,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeFastText:
    def predict(self, text, k=3):
        lower = text.lower()
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            return ["__label__zh"], [0.96]
        if "the contract" in lower and "renouvelable" in lower:
            return ["__label__en"], [0.70]
        if any(word in lower for word in ("une perte", "irréversible", "renouvelable", "tacite", "reconduction")):
            return ["__label__fr"], [0.96]
        if any(word in lower for word in ("the ", " this ", " english ", " contract ")):
            return ["__label__en"], [0.96]
        return ["__label__en"], [0.55]


class JapaneseHanOnlyFastText:
    """模拟真实模型将无假名的汉字短词误判为日文。"""

    def predict(self, text, k=3):
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            return ["__label__ja"], [0.96]
        return ["__label__en"], [0.55]


class LanguageDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = LanguageDetector(Config())
        self.detector.fasttext_model = FakeFastText()

    def test_common_terms_do_not_trigger(self):
        result = self.detector.analyze_primary("今晚 OK 吗？我在 OpenAI 和 Telegram 上测试。", "zh")
        self.assertEqual(result.relation, "primary")
        self.assertFalse(result.should_translate)

    def test_meaningful_foreign_span_triggers_in_primary_text(self):
        result = self.detector.analyze_primary(
            "这个操作会导致 une perte irréversible des données，请提前备份。", "zh"
        )
        self.assertEqual(result.relation, "mixed")
        self.assertTrue(result.should_translate)
        self.assertEqual(result.foreign_spans[0].language, "fr")

    def test_same_script_foreign_span_is_detected(self):
        result = self.detector.analyze_primary(
            "The contract is renouvelable par tacite reconduction every year.", "en"
        )
        self.assertEqual(result.relation, "mixed")
        self.assertTrue(result.should_translate)

    def test_han_only_text_prefers_chinese_over_japanese_prediction(self):
        self.detector.fasttext_model = JapaneseHanOnlyFastText()
        language, confidence = self.detector.detect_with_confidence("脂肪")
        self.assertEqual(language, "zh")
        self.assertAlmostEqual(confidence, 0.86)

        result = self.detector.analyze_primary("脂肪", "zh")
        self.assertEqual(result.relation, "primary")
        self.assertFalse(result.should_translate)

    def test_kana_text_is_not_forced_to_chinese(self):
        self.detector.fasttext_model = JapaneseHanOnlyFastText()
        language, _ = self.detector.detect_with_confidence("脂肪です")
        self.assertEqual(language, "ja")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import tg_auto_translate


class EntryPointTests(unittest.TestCase):
    def test_bot_mode_uses_main_entrypoint(self):
        with patch("tg_auto_translate.ConfigManager") as config_class, \
                patch("tg_auto_translate.asyncio.run") as run_async, \
                patch("telegram_translate_bot.main") as bot_main, \
                patch("tg_auto_translate.run_user_mode") as user_main:
            run_async.side_effect = lambda coroutine: coroutine.close()
            config = config_class.return_value
            config.get.return_value = {"mode": "bot"}
            tg_auto_translate.main()

        bot_main.assert_called_once_with(config)
        run_async.assert_called_once()
        user_main.assert_not_called()

    def test_old_config_keeps_user_mode(self):
        with patch("tg_auto_translate.ConfigManager") as config_class, \
                patch("tg_auto_translate.asyncio.run") as run_async, \
                patch("tg_auto_translate.run_user_mode") as user_main:
            config = config_class.return_value
            config.get.return_value = {}
            tg_auto_translate.main()

        user_main.assert_called_once_with(config)
        run_async.assert_not_called()

    def test_invalid_mode_fails_fast(self):
        with patch("tg_auto_translate.ConfigManager") as config_class:
            config_class.return_value.get.return_value = {"mode": "other"}
            with self.assertRaisesRegex(ValueError, "telegram.mode"):
                tg_auto_translate.main()


if __name__ == "__main__":
    unittest.main()

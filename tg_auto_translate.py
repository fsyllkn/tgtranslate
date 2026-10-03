"""Telegram 翻译项目入口：bot 模式或原有的用户账号模式。"""

import asyncio
import logging

from bot.config import ConfigManager


def run_user_mode(config_manager):
    """保留 Telethon 用户账号登录、规则和 .fy 指令。"""
    from bot.rules import RuleManager
    from bot.translation import TranslationService
    from bot.lang_detect import LanguageDetector
    from bot.commands import CommandDispatcher
    from bot.telegram_client import TelegramBot
    from bot.settings import RuntimeSettingsManager

    runtime_settings = RuntimeSettingsManager(config_manager, "runtime_settings.json")
    rule_manager = RuleManager("dynamic_rules.json")
    translation_service = TranslationService(config_manager)
    lang_detector = LanguageDetector(config_manager)
    command_dispatcher = CommandDispatcher(None)

    bot = TelegramBot(
        config_manager,
        rule_manager,
        translation_service,
        lang_detector,
        command_dispatcher,
        runtime_settings,
    )
    command_dispatcher.bot = bot
    bot.register_handlers()
    bot.run()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_manager = ConfigManager("config.yaml")
    telegram_config = config_manager.get("telegram", {}) or {}
    # 旧 config.yaml 没有 mode 时继续使用原有的用户账号模式。
    mode = str(telegram_config.get("mode", "user")).strip().lower()
    try:
        if mode == "bot":
            from telegram_translate_bot import main as run_bot_mode
            asyncio.run(run_bot_mode(config_manager))
        elif mode == "user":
            run_user_mode(config_manager)
        else:
            raise ValueError("telegram.mode 只能是 bot 或 user")
    except KeyboardInterrupt:
        logging.info("收到退出信号，正在关闭")


if __name__ == "__main__":
    main()

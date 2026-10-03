"""Translation-only Telegram Bot API client using outbound long polling."""

import asyncio
import logging
import os

import aiohttp

from bot.config import ConfigManager
from bot.translation import TranslationService


logger = logging.getLogger(__name__)
REFUSAL = "我只提供文字翻译。请直接发送待翻译的文字。"
MAX_INPUT_LENGTH = 3000
MAX_OUTPUT_LENGTH = 4000


class TelegramAPIError(RuntimeError):
    def __init__(self, code, description):
        self.code = code
        super().__init__(f"Telegram API {code}: {description}")


class TranslationBot:
    def __init__(self, config_manager, translation_service, session):
        self.config_manager = config_manager
        self.translation_service = translation_service
        self.session = session
        settings = config_manager.get("telegram_bot", {}) or {}
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("token", "")
        if not self.token or self.token.startswith("YOUR_"):
            raise ValueError("请设置 TELEGRAM_BOT_TOKEN 或 telegram_bot.token")
        self.target_language = str(settings.get("target_language", "zh")).strip()
        self.source_language = str(settings.get("source_language", "auto")).strip()
        if not self.target_language or not self.source_language:
            raise ValueError("telegram_bot 的源语言和目标语言不能为空")
        self.allowed_user_ids = {int(value) for value in settings.get("allowed_user_ids", [])}
        if not translation_service._engine_order(translation_service.default_engine):
            raise ValueError("未配置可用的翻译引擎")

    async def api(self, method, payload=None):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        async with self.session.post(url, json=payload or {}, timeout=45) as response:
            data = await response.json()
        if not data.get("ok"):
            raise TelegramAPIError(data.get("error_code", response.status), data.get("description", "请求失败"))
        return data.get("result")

    async def send_text(self, chat_id, message_id, text):
        for start in range(0, len(text), MAX_OUTPUT_LENGTH):
            await self.api("sendMessage", {
                "chat_id": chat_id,
                "reply_parameters": {"message_id": message_id},
                "text": text[start:start + MAX_OUTPUT_LENGTH],
                "link_preview_options": {"is_disabled": True},
            })

    async def handle_update(self, update):
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if chat.get("type") != "private" or sender.get("is_bot"):
            return
        if self.allowed_user_ids and sender.get("id") not in self.allowed_user_ids:
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return
        text = text.strip()
        if text.startswith("/"):
            await self.send_text(chat_id, message_id, REFUSAL)
            return
        if len(text) > MAX_INPUT_LENGTH:
            await self.send_text(chat_id, message_id, f"文字过长，请控制在 {MAX_INPUT_LENGTH} 字符以内。")
            return
        result = await self.translation_service.translate(
            text, self.source_language, [self.target_language]
        )
        translated = result.get(self.target_language, "")
        if translated.startswith("[翻译失败]") or not translated.strip():
            await self.send_text(chat_id, message_id, "翻译暂时不可用，请稍后再试。")
            return
        await self.send_text(chat_id, message_id, translated)

    async def run(self):
        try:
            identity = await self.api("getMe")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise RuntimeError("无法连接 Telegram Bot API") from None
        if not isinstance(identity, dict) or not identity.get("is_bot"):
            raise RuntimeError("Bot token 验证失败")
        logger.info("Telegram 翻译 bot 已连接：@%s", identity.get("username", "unknown"))
        offset = 0
        while True:
            try:
                updates = await self.api("getUpdates", {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                })
                for update in updates:
                    offset = max(offset, update["update_id"] + 1)
                    try:
                        await self.handle_update(update)
                    except Exception as exc:
                        logger.error("处理消息失败：%s", type(exc).__name__)
            except TelegramAPIError as exc:
                if exc.code == 409:
                    raise RuntimeError("Telegram bot 已有 webhook 或另一个轮询进程") from exc
                logger.warning("Telegram API 暂时不可用：%s", exc.code)
                await asyncio.sleep(5)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Telegram 连接中断：%s", type(exc).__name__)
                await asyncio.sleep(5)


async def main():
    config_manager = ConfigManager("config.yaml")
    translation_service = TranslationService(config_manager)
    async with aiohttp.ClientSession() as session:
        bot = TranslationBot(config_manager, translation_service, session)
        await bot.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

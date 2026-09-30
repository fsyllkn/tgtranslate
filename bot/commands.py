"""
commands.py
命令分发与处理模块
"""

import logging

logger = logging.getLogger(__name__)

VALID_LANGUAGE_CODES = {
    "en", "zh", "fr", "de", "ru", "ja", "ko", "ar", "hi", "tr", "fa",
    "uk", "es", "it", "rm", "pt", "pl", "nl", "sv", "ro", "cs", "el",
    "da", "fi", "hu", "he", "bg", "sr", "hr", "sk", "sl", "no",
}

class CommandDispatcher:
    """
    命令分发器，映射命令字符串到处理方法，支持权限校验、参数解析、异步回复
    """
    def __init__(self, bot):
        self.bot = bot
        self.commands = {
            ".fy-reload": self._handle_reload,
            ".fy-main": self._handle_main,
            ".fy-now": self._handle_now,
            ".fy": self._handle_now,
            ".fy-list": self._handle_list,
            ".fy-clear": self._handle_clear,
            ".fy-help": self._handle_help,
            ".fy-on": self._handle_on,
            ".fy-off": self._handle_off,
            ".fy-add": self._handle_add,
            ".fy-del": self._handle_del,
        }

    async def dispatch(self, event):
        """
        解析命令并分发到对应处理方法，并根据命令类型和白名单做权限控制
        """
        text = getattr(event.message, "text", "").strip()
        if not text:
            return
        # 兼容全角句号、全角逗号、全角空格，统一替换为半角
        text = text.replace("。", ".").replace("，", ",").replace("　", " ")
        # 将所有逗号和空格（连续的）都替换为单一空格，支持混合分隔
        import re
        text = re.sub(r"[, ]+", " ", text)
        parts = text.strip().split()
        # 命令大小写不敏感，便于 .fy、.FY、。fy 等写法统一处理。
        cmd = parts[0].lower()
        args = parts[1:]
        handler = self.commands.get(cmd)
        target_language = None
        if handler is None:
            # .fy-en、.fy-zh 等语言目标命令均为一次性翻译，不建立规则。
            # 已注册的 .fy-on/.fy-off 等管理命令优先级更高，不会被这里拦截。
            match = re.fullmatch(r"\.fy-([a-z]{2,3})", cmd)
            if match and match.group(1) in VALID_LANGUAGE_CODES:
                target_language = match.group(1)
                handler = self._handle_target_now
                args = [target_language, *args]
        import traceback

        # 权限控制：所有.fy 指令仅允许白名单用户
        config_manager = getattr(self.bot, "config_manager", None)
        my_tg_ids = set()
        if config_manager:
            tg_cfg = config_manager.get("telegram", {})
            ids = tg_cfg.get("my_tg_ids", [])
            # 兼容单用户写法
            if not ids:
                single_id = tg_cfg.get("my_tg_id")
                if single_id is not None:
                    ids = [single_id]
            my_tg_ids = {int(i) for i in ids if i is not None}
        sender_id = getattr(event, "sender_id", None)
        # 兼容event.message.sender_id
        if hasattr(event, "message") and hasattr(event.message, "sender_id") and event.message.sender_id is not None:
            sender_id = event.message.sender_id
        # 兼容event.message.from_id
        elif hasattr(event, "message") and hasattr(event.message, "from_id") and event.message.from_id is not None:
            sender_id = event.message.from_id

        if sender_id is None or int(sender_id) not in my_tg_ids:
            logger.info(f"[CommandDispatcher] 非白名单用户({sender_id})尝试指令{cmd}，已拒绝")
            return  # 直接忽略，不回复

        if handler:
            try:
                logger.info(f"[CommandDispatcher] 收到命令: {cmd} args={args}")
                await handler(event, args)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"[CommandDispatcher] 命令 {cmd} 处理异常: {e}\n{tb}")
                await event.reply(f"命令处理异常: {e}\n{tb}")
        else:
            logger.warning(f"[CommandDispatcher] 未知命令: {cmd}")
            await event.reply("未知命令，输入 .fy-help 查看帮助")

    # 以下为各命令处理方法骨架
    async def _handle_reload(self, event, args):
        self.bot.config_manager.reload()
        self.bot.runtime_settings.reload()
        self.bot.translation_service.reload()
        self.bot.lang_detector.reload()
        logger.info("[CommandDispatcher] 配置文件已热重载")
        from .utils import send_ephemeral_reply
        await send_ephemeral_reply(event, "配置文件已成功热重载。")

    async def _handle_list(self, event, args):
        rules = self.bot.rule_manager.list_rules()
        logger.info(f"[CommandDispatcher] 列出所有规则: {rules}")
        if not rules:
            from .utils import send_ephemeral_reply
            await send_ephemeral_reply(event, "当前无任何翻译规则。")
            return

        # 原脚本风格：chat:群名  user:用户名  源→目标
        rules = self.bot.rule_manager.list_rules()
        if not rules:
            from .utils import send_ephemeral_reply
            await send_ephemeral_reply(event, "当前无任何翻译规则。")
            return

        user_name_cache = {}
        chat_name_cache = {}

        async def get_display_name(uid):
            if uid in user_name_cache:
                return user_name_cache[uid]
            try:
                entity = await event.client.get_entity(int(uid))
                if getattr(entity, "username", None):
                    name = f"@{entity.username}"
                elif getattr(entity, "first_name", None):
                    name = entity.first_name
                else:
                    name = str(entity.id)
            except Exception:
                name = "none"
            user_name_cache[uid] = name
            return name

        async def get_chat_display_name(gid):
            if gid in chat_name_cache:
                return chat_name_cache[gid]
            try:
                entity = await event.client.get_entity(int(gid))
                if getattr(entity, "username", None):
                    name = f"@{entity.username}"
                elif getattr(entity, "title", None):
                    name = entity.title
                else:
                    name = str(entity.id)
            except Exception:
                name = str(gid)
            chat_name_cache[gid] = name
            return name

        async def build_msg_lines():
            lines = []
            for gid, usr_map in rules.items():
                chat_disp = await get_chat_display_name(gid)
                chat_show = chat_disp if chat_disp and chat_disp != str(gid) else str(gid)
                for uid, rule_obj in usr_map.items():
                    rule_list = rule_obj if isinstance(rule_obj, list) else [rule_obj]
                    for rule in rule_list:
                        if rule.get("mode", "explicit") == "primary":
                            primary = rule.get("primary_language", "inherit")
                            if primary == "inherit":
                                primary = self.bot.runtime_settings.primary_language
                            srcs = "非" + primary
                            tgts = primary + "（主语言模式）"
                        else:
                            srcs = "|".join(rule.get("source_langs", []))
                            tgts = "|".join(rule.get("target_langs", []))
                        uname = rule.get("username", "none")
                        # 自己的规则特殊显示
                        if uid == str(event.sender_id):
                            if uname == "self" or uname == "本人":
                                uname_disp = "本人/self"
                            elif uname.startswith("@"):
                                uname_disp = uname
                            else:
                                uname_disp = "本人/self"
                        else:
                            if uname == "none" or not uname or uname == str(uid):
                                uname_disp = await get_display_name(uid)
                            else:
                                uname_disp = uname
                        uname_show = uname_disp if uname_disp and uname_disp != str(uid) else str(uid)
                        lines.append(f"chat:{chat_show}  user:{uname_show}  {srcs}→{tgts}")
            return lines

        msg_lines = await build_msg_lines()
        msg = "当前无任何翻译规则。" if not msg_lines else "已保存的所有翻译规则:\n" + "\n".join(msg_lines)
        from .utils import send_ephemeral_reply
        await send_ephemeral_reply(event, msg)

    async def _handle_clear(self, event, args):
        from .utils import send_ephemeral_reply
        self.bot.rule_manager.clear_all_rules()
        logger.info("[CommandDispatcher] 已清空所有翻译规则")
        await send_ephemeral_reply(event, "已清空所有翻译规则。")

    async def _handle_help(self, event, args):
        msg = (
            "指令帮助：\n"
            "- `.fy-main` 查看默认主语言；`.fy-main,zh` 设置；`.fy-main,off` 关闭主语言模式；\n"
            "- `.fy` / `.fy-now` 回复消息或跟随文本，临时翻译成默认主语言；优先编辑本指令显示译文，编辑失败则回复译文；\n"
            "- `.fy-en` / `.fy-zh` 等：回复消息或在命令后跟文本，临时翻译成指定语言；支持中英文逗号和空格；\n"
            "`.fy-on/off` 对自己，`.fy-add/del` 对其他用户：\n"
            "- `.fy-on` 私聊、群聊-按“非主语言→主语言”翻译自己的消息；\n"
            "- `.fy-off` 私聊、群聊-关闭自己翻译功能；`.fy-off,primary` 仅关闭主语言规则；\n"
            "- `.fy-on,fr|en,zh` 私聊、群聊-指定自己英或法译中；\n"
            "- `.fy-add` 私聊-按“非主语言→主语言”翻译对方消息；\n"
            "- `.fy-del` 私聊-关闭翻译对方消息功能；\n"
            "- `.fy-del` 群聊-关闭翻译所有成员消息功能；\n"
            "- `.fy-add,zh|ru,en|fr` 私聊-为对方开中文、俄语译英、法；\n"
            "- `.fy-add,成员id或用户名` 群聊-对某个成员启用主语言翻译；\n"
            "- `.fy-add,成员id或用户名,源语言,目标语言` 群聊-为指定成员开启方向翻译；\n"
            "- `.fy-del,成员id或用户名` 群聊-关闭翻译指定成员消息功能；\n"
            "- `.fy-add,成员id或用户名,源语言,目标语言` 群聊-为指定成员开启方向翻译；\n"
            "- `.fy-del,成员id或用户名,*,ar|fr` 群聊-删除翻译指定成员消息部分规则功能；\n"
            "- `.fy-del,成员id或用户名,ar|fr,*` 群聊-任意模板语言时可以省略通配符*；\n"
            "- `.fy-clear` 一键清空所有翻译规则；\n"
            "- `.fy-list` 查看用户开启翻译功能的规则；\n"
            "- `.fy-help` 查看指令与用法说明。"
        )
        from .utils import send_ephemeral_reply
        await send_ephemeral_reply(event, msg)

    async def _handle_now(self, event, args):
        """使用默认主语言对被回复消息执行一次性翻译。"""
        await self._handle_temporary_translation(event, args, target_language=None)

    async def _handle_target_now(self, event, args):
        """使用 .fy-<语言代码> 对消息或命令后文本执行一次性翻译。"""
        from .utils import send_ephemeral_reply

        if not args or args[0] not in VALID_LANGUAGE_CODES:
            await send_ephemeral_reply(event, "用法：.fy-en 文本，或回复消息后发送 .fy-en。")
            return
        await self._handle_temporary_translation(event, args[1:], args[0])

    async def _handle_temporary_translation(self, event, args, target_language=None):
        """临时翻译公共流程，不读取或修改任何翻译规则。"""
        from .utils import send_ephemeral_reply

        inline_text = " ".join(args).strip()

        command_message = getattr(event, "message", None)
        target_message = None
        if not inline_text:
            try:
                if command_message is not None and hasattr(command_message, "get_reply_message"):
                    target_message = await command_message.get_reply_message()
                elif hasattr(event, "get_reply_message"):
                    target_message = await event.get_reply_message()
            except Exception as exc:
                logger.warning("[CommandDispatcher] 获取临时翻译被回复消息失败: %s", exc)

        if target_message is None and not inline_text:
            command_name = ".fy" if target_language is None else f".fy-{target_language}"
            await send_ephemeral_reply(event, f"请回复一条需要翻译的文字消息后再发送 `{command_name}`。")
            return

        # 指令后有文本时优先翻译该文本；否则翻译被回复消息。
        if inline_text:
            source_text = inline_text
        else:
            # raw_text 同时覆盖普通文字和带字幕的媒体消息。
            source_text = getattr(target_message, "raw_text", None)
            if source_text is None:
                source_text = getattr(target_message, "text", None)
            source_text = (source_text or "").strip()
        if not source_text:
            await send_ephemeral_reply(event, "被回复的消息没有可翻译文字或字幕。")
            return

        default_target_requested = target_language is None
        primary_language = None
        if target_language is None:
            primary_language = str(
                getattr(self.bot.runtime_settings, "primary_language", "zh") or "zh"
            ).lower()
            target_language = primary_language

        # 对 .fy 的直接文本或被回复目标先做语言识别。确认文本就是默认主语言时，
        # 直接把目标改成英语，避免先请求一次“主语言→主语言”的无效翻译。
        direct_english = False
        has_temporary_source = bool(inline_text or target_message is not None)
        if has_temporary_source and default_target_requested and primary_language != "en":
            detector = getattr(self.bot, "lang_detector", None)
            try:
                detected, confidence = detector.detect_with_confidence(source_text)
                fasttext_cfg = self.bot.config_manager.get("fasttext", {}) or {}
                confidence_threshold = float(fasttext_cfg.get("confidence_threshold", 0.8))
                if detected == primary_language and confidence >= confidence_threshold:
                    target_language = "en"
                    direct_english = True
                    logger.info(
                        "[CommandDispatcher] .fy 检测到源语言=%s 与默认主语言一致，直接翻译为英语",
                        primary_language,
                    )
            except Exception as exc:
                logger.warning("[CommandDispatcher] .fy 直接语言识别失败，继续默认翻译流程: %s", exc)
        prefer = self.bot.config_manager.get("default_translate_source", "deeplx")
        try:
            translated_map = await self.bot.translation_service.translate(
                source_text,
                "auto",
                [target_language],
                prefer=prefer,
                task="full_translation",
            )
        except Exception as exc:
            logger.exception("[CommandDispatcher] 临时翻译异常")
            await send_ephemeral_reply(event, f"临时翻译失败：{exc}")
            return

        translated = (translated_map or {}).get(target_language, "")
        translated = (translated or "").strip()
        if not translated or translated.startswith("[翻译失败]"):
            await send_ephemeral_reply(event, translated or "临时翻译失败，请稍后重试。")
            return

        # 如果 .fy 的文本或回复目标已经是默认主语言，按实用场景改译成英语。
        # 指定目标语言（如 .fy-en/.fy-zh）不触发此兜底逻辑；默认主语言本身为英语时也无需重复请求。
        if (
            has_temporary_source
            and default_target_requested
            and not direct_english
            and target_language != "en"
            and translated == source_text
        ):
            logger.info(
                "[CommandDispatcher] .fy 文本已是默认主语言 %s，改译为英语",
                target_language,
            )
            try:
                english_map = await self.bot.translation_service.translate(
                    source_text,
                    "auto",
                    ["en"],
                    prefer=prefer,
                    task="full_translation",
                )
                english_text = (english_map or {}).get("en", "")
                english_text = (english_text or "").strip()
                if english_text and not english_text.startswith("[翻译失败]"):
                    translated = english_text
                    target_language = "en"
            except Exception as exc:
                logger.warning("[CommandDispatcher] .fy 默认主语言转英语失败: %s", exc)

        if translated == source_text:
            await send_ephemeral_reply(event, "翻译结果与原文相同，无需修改。")
            return

        # 临时翻译统一编辑本次指令消息。该消息本身是回复目标消息时，
        # 因此编辑后仍然保持“回复目标消息”的展示关系，同时不会改写原文。
        try:
            if command_message is None or not hasattr(command_message, "edit"):
                raise RuntimeError("临时翻译指令消息不可编辑")
            await command_message.edit(translated)
            logger.info(
                "[CommandDispatcher] .fy-now 已编辑指令消息 id=%s",
                getattr(command_message, "id", None),
            )
            return
        except Exception as exc:
            # Telegram 可能因消息不可编辑、媒体类型或时间限制拒绝编辑，
            # 此时按普通临时翻译回复，确保功能仍然可用。
            logger.warning(
                "[CommandDispatcher] .fy-now 编辑指令消息失败，回退为回复: %s", exc
            )

        try:
            await self.bot.send_reply(
                event,
                translated,
                reply_to=getattr(target_message, "id", None),
            )
            logger.info("[CommandDispatcher] .fy-now 已回复临时译文")
        except Exception as exc:
            logger.exception("[CommandDispatcher] .fy-now 回复译文失败")
            await send_ephemeral_reply(event, f"临时翻译结果发送失败：{exc}")

    async def _handle_main(self, event, args):
        """查看、设置或关闭默认主语言。"""
        from .utils import send_ephemeral_reply
        settings = self.bot.runtime_settings
        if not args:
            state = "已启用" if settings.primary_mode_enabled else "已关闭"
            await send_ephemeral_reply(
                event, f"当前默认主语言：{settings.primary_language}，主语言模式：{state}。"
            )
            return
        value = args[0].strip().lower()
        if value in {"off", "disable", "0"}:
            settings.disable_primary_mode()
            await send_ephemeral_reply(event, "已关闭主语言模式；现有精确语言规则不受影响。")
            return
        if value not in VALID_LANGUAGE_CODES:
            await send_ephemeral_reply(event, "语言代码不合法，例如：.fy-main,zh 或 .fy-main,en")
            return
        settings.set_primary_language(value)
        await send_ephemeral_reply(
            event,
            f"默认主语言已设置为 {value}，主语言模式已启用。现有主语言规则立即继承新设置。",
        )

    def _get_display_name(self, entity):
        # 优先 @username，其次 first_name，最后 id
        if hasattr(entity, "username") and entity.username:
            return f"@{entity.username}"
        elif hasattr(entity, "first_name") and entity.first_name:
            return entity.first_name
        elif hasattr(entity, "id"):
            return str(entity.id)
        return str(entity)

    async def _handle_on(self, event, args):
        from .utils import send_ephemeral_reply
        chat_id = str(event.chat_id)
        user_id = str(event.sender_id)
        is_group = getattr(event, "is_group", False)
        is_private = getattr(event, "is_private", False)
        # 无参数时切换为主语言模式；显式参数仍按精确语言规则处理。
        argstr = ",".join(args) if args else ""
        if not argstr:
            if not self.bot.runtime_settings.primary_mode_enabled:
                await send_ephemeral_reply(event, "主语言模式已关闭，请先使用 .fy-main,语言代码 设置主语言。")
                return
            try:
                entity = await event.client.get_entity(event.sender_id)
                username = self._get_display_name(entity)
            except Exception:
                username = str(event.sender_id)
            primary = self.bot.runtime_settings.primary_language
            self.bot.rule_manager.replace_rules(chat_id, user_id, [{
                "mode": "primary",
                "primary_language": "inherit",
                "username": username,
            }])
            await send_ephemeral_reply(
                event,
                f"已为 [自己] 在本{'群组' if is_group else '私聊'}开启主语言翻译：非{primary}→{primary}。",
            )
            return
        else:
            rule_key = argstr
            src_list = [s.strip() for s in rule_key.split(",")[0].split("|")] if "," in rule_key else [rule_key.strip()]
            tgt_list = [t.strip() for t in rule_key.split(",")[1].split("|")] if "," in rule_key and len(rule_key.split(",")) > 1 else ["en"]
        # 过滤非法语言代码
        if "*" in src_list or "*" in tgt_list:
            await send_ephemeral_reply(event, "禁止使用通配符 * 增加规则。")
            return
        if not all(s in VALID_LANGUAGE_CODES for s in src_list) or not all(t in VALID_LANGUAGE_CODES for t in tgt_list):
            await send_ephemeral_reply(event, "语言代码不合法，请检查输入。")
            return
        # 获取自己 display_name
        try:
            entity = await event.client.get_entity(event.sender_id)
            username = self._get_display_name(entity)
        except Exception:
            username = str(event.sender_id)
        saved_rules = []
        for src in src_list:
            for tgt in tgt_list:
                if src == tgt:
                    continue
                self.bot.rule_manager.set_rule(chat_id, user_id, {"source_langs": [src], "target_langs": [tgt]}, username=username)
                saved_rules.append(f"{src}→{tgt}")
        if saved_rules:
            rule_desc = argstr if argstr else "中英互译"
            await send_ephemeral_reply(
                event,
                f"已为 [自己] 在本{'群组' if is_group else '私聊'}开启翻译，规则为：{rule_desc}"
            )
        else:
            await send_ephemeral_reply(
                event,
                "源语言和目标语言完全重叠，无需翻译，规则未保存。"
            )

    async def _handle_off(self, event, args):
        from .utils import send_ephemeral_reply
        chat_id = str(event.chat_id)
        user_id = str(event.sender_id)
        # 支持 .fy-off,src,tgt 只删除指定规则，支持 * 通配符
        def parse_langs(text):
            if "|" in text:
                return [lng.strip() for lng in text.split("|") if lng.strip()]
            if "," in text:
                return [lng.strip() for lng in text.split(",") if lng.strip()]
            return [text.strip()]
        src = parse_langs(args[0]) if len(args) >= 1 else []
        tgt = parse_langs(args[1]) if len(args) >= 2 else []
        # 支持目标语言为通配符时省略（如.fy-off,fr|en 等价于 .fy-off,fr|en,*）
        if len(args) == 1:
            tgt = ["*"]
        rule_raw = self.bot.rule_manager.get_rule(chat_id, user_id)
        if not rule_raw:
            await send_ephemeral_reply(event, "当前无可删除的翻译规则。")
            return
        rule_list = rule_raw if isinstance(rule_raw, list) else [rule_raw]
        if args and args[0].strip().lower() in {"primary", "main"}:
            new_rules = [rule for rule in rule_list if rule.get("mode", "explicit") != "primary"]
            self.bot.rule_manager.replace_rules(chat_id, user_id, new_rules)
            await send_ephemeral_reply(event, "已关闭当前用户的主语言翻译规则。")
            return
        new_rules = []
        src_is_any = len(src) == 1 and src[0] == "*"
        tgt_is_any = len(tgt) == 1 and tgt[0] == "*"
        for rule in rule_list:
            rule_src = set(rule.get("source_langs", []))
            rule_tgt = set(rule.get("target_langs", []))
            src_match = src_is_any or not src or any(s in rule_src for s in src)
            tgt_match = tgt_is_any or not tgt or any(t in rule_tgt for t in tgt)
            # 有一个源和目标匹配就删除
            if src_match and tgt_match:
                continue  # 删除
            new_rules.append(rule)
        if not new_rules:
            self.bot.rule_manager.remove_rule(chat_id, user_id)
            await send_ephemeral_reply(event, f"已移除指定源/目标语言的翻译规则。")
        elif len(new_rules) == 1:
            self.bot.rule_manager.set_rule(chat_id, user_id, new_rules[0])
            await send_ephemeral_reply(event, f"已移除部分规则，其余规则仍保留。")
        else:
            # 多条规则时直接赋值并保存，保留 username 字段
            with self.bot.rule_manager._lock:
                self.bot.rule_manager._rules.setdefault(str(chat_id), {})[str(user_id)] = new_rules
                self.bot.rule_manager._save_rules()
            await send_ephemeral_reply(event, f"已移除部分规则，其余规则仍保留。")

    async def _handle_add(self, event, args):
        from .utils import send_ephemeral_reply
        chat_id = str(event.chat_id)
        user_id = str(event.sender_id)
        is_group = getattr(event, "is_group", False)
        is_private = getattr(event, "is_private", False)
        # 群聊：.fy-add,成员id/@用户名,src,tgt 或 .fy-add,成员id/@用户名
        # 私聊：.fy-add,src,tgt 或 .fy-add
        if is_group:
            if args and args[0]:
                mem_arg = args[0].strip()
                # 支持id或@username
                if mem_arg.isdigit():
                    mem_id = mem_arg
                    try:
                        entity = await event.client.get_entity(int(mem_id))
                        if getattr(entity, "username", None):
                            username = f"@{entity.username}"
                        elif getattr(entity, "first_name", None):
                            username = entity.first_name
                        else:
                            username = str(entity.id)
                    except Exception:
                        username = "none"
                else:
                    uname = mem_arg.lstrip("@")
                    try:
                        entity = await event.client.get_entity(uname)
                        mem_id = str(entity.id)
                        if getattr(entity, "username", None):
                            username = f"@{entity.username}"
                        elif getattr(entity, "first_name", None):
                            username = entity.first_name
                        else:
                            username = str(entity.id)
                    except Exception:
                        await send_ephemeral_reply(event, f"未找到成员 {mem_arg}，请检查用户名或id是否正确。")
                        return
                # 无语言参数时为指定成员切换到主语言模式。
                if len(args) == 1:
                    if not self.bot.runtime_settings.primary_mode_enabled:
                        await send_ephemeral_reply(event, "主语言模式已关闭，请先使用 .fy-main,语言代码 设置主语言。")
                        return
                    primary = self.bot.runtime_settings.primary_language
                    self.bot.rule_manager.replace_rules(chat_id, mem_id, [{
                        "mode": "primary",
                        "primary_language": "inherit",
                        "username": username,
                    }])
                    await send_ephemeral_reply(
                        event,
                        f"已为群组成员{mem_id}({username})启用主语言翻译：非{primary}→{primary}。",
                    )
                    return
                elif len(args) == 3:
                    src = [s.strip() for s in args[1].split("|")]
                    tgt = [t.strip() for t in args[2].split("|")]
                elif len(args) == 2:
                    src = [s.strip() for s in args[1].split("|")]
                    tgt = ["zh"]
                else:
                    await send_ephemeral_reply(event, "参数格式: .fy-add,成员id/@用户名 或 .fy-add,成员id/@用户名,源,目标")
                    return
                if "*" in src or "*" in tgt:
                    await send_ephemeral_reply(event, "禁止使用通配符 * 增加规则。")
                    return
                if not all(s in VALID_LANGUAGE_CODES for s in src) or not all(t in VALID_LANGUAGE_CODES for t in tgt):
                    await send_ephemeral_reply(event, "语言代码不合法，请检查输入。")
                    return
                saved_rules = []
                for s in src:
                    filtered_tgts = [t for t in tgt if t != s]
                    if filtered_tgts:
                        self.bot.rule_manager.set_rule(chat_id, mem_id, {"source_langs": [s], "target_langs": filtered_tgts}, username=username)
                        saved_rules.append(f"{s}→{'|'.join(filtered_tgts)}")
                if saved_rules:
                    rule_desc = f"{'|'.join(src)}→{'|'.join(tgt)}"
                    await send_ephemeral_reply(
                        event, f"已为群组成员{mem_id}({username})启用翻译，规则为：{rule_desc}"
                    )
                else:
                    await send_ephemeral_reply(
                        event, f"源语言和目标语言完全重叠，无需翻译，规则未保存。"
                    )
                return
            else:
                await send_ephemeral_reply(event, "请指定成员id或@用户名作为第一个参数，如.fy-add,12345,zh,en 或 .fy-add,@user,zh,en")
                return
        elif is_private:
            if not args:
                if not self.bot.runtime_settings.primary_mode_enabled:
                    await send_ephemeral_reply(event, "主语言模式已关闭，请先使用 .fy-main,语言代码 设置主语言。")
                    return
                try:
                    entity = await event.client.get_entity(int(chat_id))
                    peer_username = self._get_display_name(entity)
                except Exception:
                    peer_username = str(chat_id)
                primary = self.bot.runtime_settings.primary_language
                self.bot.rule_manager.replace_rules(chat_id, chat_id, [{
                    "mode": "primary",
                    "primary_language": "inherit",
                    "username": peer_username,
                }])
                await send_ephemeral_reply(
                    event,
                    f"已为对方（此私聊）启用主语言翻译：非{primary}→{primary}。",
                )
                return
            elif len(args) == 2:
                src = [s.strip() for s in args[0].split("|")]
                tgt = [t.strip() for t in args[1].split("|")]
            elif len(args) == 1:
                src = [s.strip() for s in args[0].split("|")]
                tgt = ["zh"]
            else:
                await send_ephemeral_reply(event, "参数格式: .fy-add 或 .fy-add,源,目标")
                return
            if "*" in src or "*" in tgt:
                await send_ephemeral_reply(event, "禁止使用通配符 * 增加规则。")
                return
            if not all(s in VALID_LANGUAGE_CODES for s in src) or not all(t in VALID_LANGUAGE_CODES for t in tgt):
                await send_ephemeral_reply(event, "语言代码不合法，请检查输入。")
                return
            saved_rules = []
            # 获取对方 display_name（私聊场景，chat_id=对方id）
            try:
                entity = await event.client.get_entity(int(chat_id))
                peer_username = self._get_display_name(entity)
            except Exception:
                peer_username = str(chat_id)
            for s in src:
                filtered_tgts = [t for t in tgt if t != s]
                if filtered_tgts:
                    self.bot.rule_manager.set_rule(chat_id, chat_id, {"source_langs": [s], "target_langs": filtered_tgts}, username=peer_username)
                    saved_rules.append(f"{s}→{'|'.join(filtered_tgts)}")
            if saved_rules:
                rule_desc = f"{'|'.join(src)}→{'|'.join(tgt)}"
                await send_ephemeral_reply(
                    event, f"已为对方（此私聊）启用翻译，规则为：{rule_desc}"
                )
            else:
                await send_ephemeral_reply(
                    event, "源语言和目标语言完全重叠，无需翻译，规则未保存。"
                )
            return
        else:
            await send_ephemeral_reply(event, "请在私聊或群聊中使用 .fy-add")
            return

    async def _handle_del(self, event, args):
        from .utils import send_ephemeral_reply
        chat_id = str(event.chat_id)
        user_id = str(event.sender_id)
        is_group = getattr(event, "is_group", False)
        is_private = getattr(event, "is_private", False)
        valid_codes = {
            "en","zh","fr","de","ru","ja","ko","ar","hi","tr","fa","uk","es","it","rm","pt","pl","nl","sv","ro","cs","el","da","fi","hu","he","bg","sr","hr","sk","sl","no"
        }
        # 群聊：.fy-del,成员id/@用户名,src,tgt 或 .fy-del,成员id/@用户名 或 .fy-del
        # 私聊：.fy-del,src,tgt 或 .fy-del
        if is_group:
            from .utils import send_ephemeral_reply
            rules = self.bot.rule_manager.list_rules()
            group_rules = rules.get(chat_id, {})
            if not args:
                # 无参数，删除全群成员规则
                if group_rules:
                    for uid in list(group_rules.keys()):
                        self.bot.rule_manager.remove_rule(chat_id, uid)
                    await send_ephemeral_reply(event, "已移除当前群所有成员翻译规则")
                else:
                    await send_ephemeral_reply(event, "本群无可删除成员规则")
                return
            mem_arg = args[0].strip()
            src = [s.strip() for s in args[1].split("|")] if len(args) >= 2 else []
            tgt = [t.strip() for t in args[2].split("|")] if len(args) >= 3 else []
            src_is_any = len(src) == 1 and src[0] == "*"
            tgt_is_any = len(tgt) == 1 and tgt[0] == "*"
            found = False
            to_remove = []
            mem_ids = set()
            mem_usernames = set()
            if mem_arg == "*":
                # 通配符，匹配所有成员
                mem_ids = set(group_rules.keys())
            elif mem_arg.isdigit():
                mem_ids.add(mem_arg)
            else:
                uname = mem_arg.lstrip("@")
                try:
                    entity = await event.client.get_entity(uname)
                    mem_ids.add(str(entity.id))
                    if getattr(entity, "username", None):
                        mem_usernames.add(f"@{entity.username}")
                except Exception:
                    await send_ephemeral_reply(event, f"未找到成员 {mem_arg}，请检查用户名或id是否正确。")
                    return
            for uid, rule_obj in list(group_rules.items()):
                # 匹配 id/用户名/通配符
                matched = False
                if mem_arg == "*" or uid in mem_ids:
                    matched = True
                else:
                    rule_list = rule_obj if isinstance(rule_obj, list) else [rule_obj]
                    for rule in rule_list:
                        uname = rule.get("username", "")
                        if uname in mem_usernames:
                            matched = True
                            break
                if not matched:
                    continue
                # 删除规则
                rule_list = rule_obj if isinstance(rule_obj, list) else [rule_obj]
                new_rules = []
                if len(src) == 1 and src[0].lower() in {"primary", "main"}:
                    new_rules = [rule for rule in rule_list if rule.get("mode", "explicit") != "primary"]
                elif src and tgt:
                    to_del = set()
                    for s in src:
                        for t in tgt:
                            if s == t and s != "*":
                                continue
                            to_del.add((s, t))
                    for rule in rule_list:
                        rule_src = rule.get("source_langs", [])
                        rule_tgt = rule.get("target_langs", [])
                        s = rule_src[0] if rule_src else ""
                        t = rule_tgt[0] if rule_tgt else ""
                        match_src = src_is_any or s in src
                        match_tgt = tgt_is_any or t in tgt
                        if match_src and match_tgt:
                            continue  # 删除
                        new_rules.append(rule)
                else:
                    for rule in rule_list:
                        rule_src = set(rule.get("source_langs", []))
                        rule_tgt = set(rule.get("target_langs", []))
                        src_match = src_is_any or not src or any(s in rule_src for s in src)
                        tgt_match = tgt_is_any or not tgt or any(t in rule_tgt for t in tgt)
                        # 有一个源和目标匹配就删除
                        if src_match and tgt_match:
                            continue  # 删除
                        new_rules.append(rule)
                # 原脚本风格：如无剩余规则则 remove_rule，否则整体 set_rule
                if not new_rules:
                    self.bot.rule_manager.remove_rule(chat_id, uid)
                else:
                    # 兼容多条规则整体覆盖
                    if len(new_rules) == 1:
                        self.bot.rule_manager.set_rule(chat_id, uid, new_rules[0], username=new_rules[0].get("username"))
                    else:
                        # 直接赋值并保存，保留 username 字段
                        with self.bot.rule_manager._lock:
                            self.bot.rule_manager._rules.setdefault(str(chat_id), {})[str(uid)] = new_rules
                            self.bot.rule_manager._save_rules()
                found = True
            if found:
                await send_ephemeral_reply(event, f"已移除成员{mem_arg}在本群的指定源/目标语言翻译规则。")
            else:
                await send_ephemeral_reply(event, f"成员{mem_arg}在本群无可删除的翻译规则")
            return
        elif is_private:
            if not args:
                self.bot.rule_manager.remove_rule(chat_id, chat_id)
                await send_ephemeral_reply(event, "已移除对方翻译规则")
            else:
                src = [s.strip() for s in args[0].split("|")] if len(args) >= 1 else []
                tgt = [t.strip() for t in args[1].split("|")] if len(args) >= 2 else []
                rule_raw = self.bot.rule_manager.get_rule(chat_id, chat_id)
                if not rule_raw:
                    await send_ephemeral_reply(event, "当前无可删除的翻译规则。")
                    return
                rule_list = rule_raw if isinstance(rule_raw, list) else [rule_raw]
                new_rules = []
                src_is_any = len(src) == 1 and src[0] == "*"
                tgt_is_any = len(tgt) == 1 and tgt[0] == "*"
                if len(src) == 1 and src[0].lower() in {"primary", "main"}:
                    new_rules = [rule for rule in rule_list if rule.get("mode", "explicit") != "primary"]
                elif src and tgt:
                    to_del = set()
                    for s in src:
                        for t in tgt:
                            if s == t and s != "*":
                                continue
                            to_del.add((s, t))
                    for rule in rule_list:
                        rule_src = rule.get("source_langs", [])
                        rule_tgt = rule.get("target_langs", [])
                        s = rule_src[0] if rule_src else ""
                        t = rule_tgt[0] if rule_tgt else ""
                        match_src = src_is_any or s in src
                        match_tgt = tgt_is_any or t in tgt
                        if match_src and match_tgt:
                            continue  # 删除
                        new_rules.append(rule)
                else:
                    for rule in rule_list:
                        rule_src = set(rule.get("source_langs", []))
                        rule_tgt = set(rule.get("target_langs", []))
                        src_match = src_is_any or not src or any(s in rule_src for s in src)
                        tgt_match = tgt_is_any or not tgt or any(t in rule_tgt for t in tgt)
                        if not (src_match and tgt_match):
                            new_rules.append(rule)
                # 兼容多条规则整体覆盖
                if not new_rules:
                    self.bot.rule_manager.remove_rule(chat_id, chat_id)
                    await send_ephemeral_reply(event, f"已移除指定源/目标语言的翻译规则。")
                elif len(new_rules) == 1:
                    self.bot.rule_manager.set_rule(chat_id, chat_id, new_rules[0], username=new_rules[0].get("username"))
                    await send_ephemeral_reply(event, f"已移除部分规则，其余规则仍保留。")
                else:
                    with self.bot.rule_manager._lock:
                        self.bot.rule_manager._rules.setdefault(str(chat_id), {})[str(chat_id)] = new_rules
                        self.bot.rule_manager._save_rules()
                    await send_ephemeral_reply(event, f"已移除部分规则，其余规则仍保留。")
            return

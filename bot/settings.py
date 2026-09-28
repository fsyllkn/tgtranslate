"""可由 Telegram 快捷指令修改的运行时设置。"""

import json
import logging
import os
import tempfile
import threading


logger = logging.getLogger(__name__)


class RuntimeSettingsManager:
    """持久化不适合直接写回 config.yaml 的少量运行时设置。"""

    def __init__(self, config_manager, path="runtime_settings.json"):
        self.config_manager = config_manager
        self.path = path
        self._lock = threading.RLock()
        self._settings = {}
        self.reload()

    def _defaults(self):
        cfg = self.config_manager.get("language_detection", {}) or {}
        return {
            "primary_language": str(cfg.get("primary_language", "zh")).lower(),
            "primary_mode_enabled": bool(cfg.get("primary_mode_enabled", True)),
        }

    def reload(self):
        with self._lock:
            settings = self._defaults()
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as file_obj:
                        stored = json.load(file_obj)
                    if isinstance(stored, dict):
                        settings.update(stored)
                except Exception as exc:
                    logger.error("[RuntimeSettings] 加载失败: %s", exc)
            self._settings = settings
            logger.info("[RuntimeSettings] 已加载，主语言=%s，启用=%s",
                        settings["primary_language"],
                        settings["primary_mode_enabled"])

    def _save(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False
            ) as file_obj:
                temp_path = file_obj.name
                json.dump(self._settings, file_obj, ensure_ascii=False, indent=2)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def get(self, key, default=None):
        with self._lock:
            return self._settings.get(key, default)

    @property
    def primary_language(self):
        return self.get("primary_language", "zh")

    @property
    def primary_mode_enabled(self):
        return bool(self.get("primary_mode_enabled", True))

    def set_primary_language(self, language):
        with self._lock:
            self._settings["primary_language"] = language.lower()
            self._settings["primary_mode_enabled"] = True
            self._save()

    def disable_primary_mode(self):
        with self._lock:
            self._settings["primary_mode_enabled"] = False
            self._save()

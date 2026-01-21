import json
from pathlib import Path
from typing import Any

import typst

from astrbot.api import logger


class FontManager:
    def __init__(self, font_dirs: list[Path]):
        self.font_dirs = font_dirs
        self.available_families: set[str] = set()

    def scan_fonts(self):
        """扫描本地字体(.ttf .otf .woff2)"""
        self.available_families.clear()

        # 转换路径为 Typst 期望的字符串列表
        search_paths = [str(p.resolve()) for p in self.font_dirs if p.exists()]

        if not search_paths:
            logger.warning("[HelpTypst] 没有有效的字体目录，跳过扫描")
            return

        try:
            font_db = typst.Fonts(font_paths=search_paths) # 0.14.7 引入的字体查询接口
            families = list(font_db.families())
            self.available_families.update(families)
            count = len(self.available_families)
            logger.info(f"[HelpTypst] Typst 扫描完成，识别到 {count} 个字体家族")
            logger.debug(f"可用字体: {self.available_families}")

        except Exception as e:
            logger.error(f"[HelpTypst] Typst 字体扫描失败: {e}", exc_info=True)

    def update_json_schema(self, schema_path: Path):
        """更新 Schema options"""
        if not schema_path.exists():
            return
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            try:
                target = schema["appearance"]["items"]["presets"]["templates"][
                    "standard_theme"
                ]["items"]["font_order"]
                target["options"] = sorted(list(self.available_families))

                with open(schema_path, "w", encoding="utf-8") as f:
                    json.dump(schema, f, indent=2, ensure_ascii=False)

                logger.info("[HelpTypst] 已更新可用字体，可能重载插件后列表变化才可见")
            except KeyError:
                pass
        except Exception as e:
            logger.warning(f"[HelpTypst] Schema 更新失败: {e}")

    def prune_invalid_config_items(self, config: dict[str, Any]):
        """失效字体清洗"""
        if not self.available_families:
            return  # 避免扫描失败导致清空配置

        appearance = config.get("appearance", {})
        if not isinstance(appearance, dict):
            return
        presets = appearance.get("presets", [])
        if not isinstance(presets, list):
            return

        has_changes = False

        for preset in presets:
            if not isinstance(preset, dict):
                continue

            current_order = preset.get("font_order", [])
            if not isinstance(current_order, list):
                continue

            # 只保留本地存在的字体
            valid_order = [f for f in current_order if f in self.available_families]

            # 长度变短 → 有无效项被剔除
            if len(valid_order) != len(current_order):
                preset["font_order"] = valid_order
                has_changes = True

        if has_changes:
            try:
                if hasattr(config, "save_config"):
                    config.save_config()
                    logger.info("[HelpTypst] 已保存清理后的字体配置")
            except Exception as e:
                logger.warning(f"[HelpTypst] 字体配置保存失败: {e}")

    def get_render_font_list(self, user_config_order: list[str]) -> list[str]:
        """生成传给 Typst 的最终字体列表"""
        final = []
        seen = set()

        # 1. 用户配置
        for f in user_config_order:
            if f in self.available_families and f not in seen:
                final.append(f)
                seen.add(f)

        # 2. 兜底
        defaults = ["Sarasa Gothic SC", "Noto Color Emoji"]
        for f in defaults:
            if f not in seen:
                final.append(f)
                seen.add(f)
        return final

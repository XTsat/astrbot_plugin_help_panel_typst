import json
from pathlib import Path
from typing import Set, List, Dict, Any

from astrbot.api import logger

try:
    from fontTools.ttLib import TTFont
    HAS_FONTTOOLS = True
except ImportError:
    HAS_FONTTOOLS = False

class FontManager:
    def __init__(self, font_dir: Path):
        self.font_dir = font_dir
        self.available_families: Set[str] = set()

    def scan_fonts(self):
        """扫描本地字体(.ttf .otf .woff2)"""
        self.available_families.clear()
        if not self.font_dir.exists(): return

        valid_extensions = {'.ttf', '.otf', '.woff2'}

        for file_path in self.font_dir.iterdir():
            if not file_path.is_file(): continue

            if file_path.suffix.lower() in valid_extensions:
                try:
                    family_name = self._extract_font_family(file_path)
                    if family_name:
                        self.available_families.add(family_name)
                    else:
                        self.available_families.add(file_path.stem)
                except Exception as e:
                    logger.debug(f"[HelpTypst] Failed to parse {file_path.name}: {e}")
                    self.available_families.add(file_path.stem)

        logger.info(f"[HelpTypst] 扫描完成，可用字体: {self.available_families}")

    def _extract_font_family(self, file_path: Path) -> str | None:
        """从字体文件中提取 Family Name"""
        if not HAS_FONTTOOLS:
            logger.warning(f"[HelpTypst] 依赖 FONTTOOLS 似乎未安装，自定义字体可能无法正常读取")
            return file_path.stem # 兜底: 使用文件名

        try:
            # 对于 .woff2 自动尝试 import brotli
            font = TTFont(file_path)
            return self._get_best_family_name(font)
        except Exception as e:
            raise e # 文件损坏或环境异常

    def _get_best_family_name(self, font: Any) -> str | None:
        """字体元信息优先级: 16 Typographic Family > 1 Font Family"""
        names = font['name']

        def get_name(name_id):
            # Windows English
            n = names.getName(name_id, 3, 1, 0x409)
            if n: return n.toUnicode()
            # Macintosh English
            n = names.getName(name_id, 1, 0, 0)
            if n: return n.toUnicode()
            # Fallback
            for record in names.names:
                if record.nameID == name_id:
                    return record.toUnicode()
            return None

        # 1. Typographic Family
        family_name = get_name(16)

        # 2. Font Family
        if not family_name:
            family_name = get_name(1)

        if family_name:
            return family_name.strip()

        return None

    def update_json_schema(self, schema_path: Path):
        """更新 Schema options"""
        if not schema_path.exists(): return
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            try:
                target = schema["appearance"]["items"]["presets"]["templates"]["standard_theme"]["items"]["font_order"]
                target["options"] = sorted(list(self.available_families))

                with open(schema_path, "w", encoding="utf-8") as f:
                    json.dump(schema, f, indent=2, ensure_ascii=False)

                logger.info(f"[HelpTypst] 已更新可用字体，可能重载插件后列表变化才可见")
            except KeyError: pass
        except Exception as e:
            logger.warning(f"[HelpTypst] Schema 更新失败: {e}")

    def prune_invalid_config_items(self, config: Dict[str, Any]):
        """失效字体清洗"""
        if not self.available_families: return # 避免扫描失败导致清空配置

        appearance = config.get("appearance", {})
        if not isinstance(appearance, dict): return
        presets = appearance.get("presets", [])
        if not isinstance(presets, list): return

        has_changes = False

        for preset in presets:
            if not isinstance(preset, dict): continue

            current_order = preset.get("font_order", [])
            if not isinstance(current_order, list): continue

            # 只保留本地存在的字体
            valid_order = [f for f in current_order if f in self.available_families]

            # 长度变短 → 有无效项被剔除
            if len(valid_order) != len(current_order):
                preset["font_order"] = valid_order
                has_changes = True
                removed = set(current_order) - set(valid_order)

        if has_changes:
            try:
                if hasattr(config, "save_config"):
                    config.save_config()
                    logger.info("[HelpTypst] 已保存清理后的字体配置")
            except Exception as e:
                logger.warning(f"[HelpTypst] 字体配置保存失败: {e}")

    def get_render_font_list(self, user_config_order: List[str]) -> List[str]:
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
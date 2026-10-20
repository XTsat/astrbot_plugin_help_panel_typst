import os
from pathlib import Path
from typing import Any

import typst

from astrbot.api import logger

from ..domain import DefaultCFG


def _preset_options() -> tuple[list[str], list[str]]:
    """主题预设下拉的 options 与 labels (面板显示中文名, 存的是预设 key)"""
    options = list(DefaultCFG.PRESETS.keys()) + [DefaultCFG.CUSTOM_PRESET_KEY]
    labels = [DefaultCFG.PRESET_LABELS.get(name, name) for name in options]
    return options, labels


class FontManager:
    def __init__(self, font_dirs: list[Path]):
        self.font_dirs = font_dirs
        self.available_families: set[str] = set()
        # 最近一次扫描是否成功: 区分「扫描失败」与「扫描成功但没有可选字体」,
        # 失败时上游不得把空结果写回 Schema/配置 (否则面板字体下拉被清空)
        self._last_scan_ok: bool = False

    @property
    def last_scan_ok(self) -> bool:
        """最近一次字体扫描是否成功 (供调用方区分「扫描失败」与「无可选字体」)"""
        return self._last_scan_ok

    @staticmethod
    def get_system_font_dirs() -> list[Path]:
        """收集系统字体目录 (仅返回实际存在的目录)"""
        dirs = [Path(p).expanduser() for p in DefaultCFG.SYSTEM_FONT_DIRS]

        # Windows 每用户字体目录 (LOCALAPPDATA 可能不存在)
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            dirs.append(Path(local_appdata) / "Microsoft" / "Windows" / "Fonts")

        return [d for d in dirs if d.is_dir()]

    def get_search_paths(self) -> list[Path]:
        """合并项目目录与系统目录, 去重后返回实际存在的字体目录 (Path)

        扫描与渲染共用同一份路径集合, 保证「扫描到的字体」在编译时一定可用
        (系统字体库也一并传入, 修复系统内置字体选择后不生效的问题)。
        """
        search_paths: list[Path] = []
        seen: set[str] = set()
        for p in [*self.font_dirs, *self.get_system_font_dirs()]:
            if not p.exists():
                continue
            resolved = p.resolve()
            if str(resolved) not in seen:
                seen.add(str(resolved))
                search_paths.append(resolved)
        return search_paths

    def scan_fonts(self) -> bool:
        """扫描本地字体(.ttf .otf .woff2) —— 项目目录 + 系统字体目录

        返回本次扫描是否成功。False 表示扫描环境不可用 (无有效字体目录或
        Typst 接口异常), 调用方据此避免把失败结果当成「没有字体」写回配置;
        True 且 available_families 为空则代表扫描成功但确实没有可选字体。
        """
        self.available_families.clear()
        self._last_scan_ok = False

        # 合并项目目录与系统目录, 去重后转换为 Typst 期望的字符串列表
        search_paths: list[str] = [str(p) for p in self.get_search_paths()]

        if not search_paths:
            logger.warning("[HelpTypst] 没有有效的字体目录，跳过扫描")
            return False

        try:
            font_db = typst.Fonts(font_paths=search_paths)  # 0.14.7 引入的字体查询接口
            families = list(font_db.families())
            self.available_families.update(families)
            self._last_scan_ok = True
            count = len(self.available_families)
            logger.info(f"[HelpTypst] Typst 扫描完成，识别到 {count} 个字体家族")
            logger.debug(f"可用字体: {self.available_families}")
            return True

        except Exception as e:
            logger.error(f"[HelpTypst] Typst 字体扫描失败: {e}", exc_info=True)
            return False

    def get_selectable_families(self) -> list[str]:
        """供配置面板选择的可选字体家族 (排除固定表情字体, 按名称排序)

        表情字体由系统固定追加到渲染字体列表末尾, 用户无需也不应在面板中选择,
        故从 `font_order` 下拉项中隐藏。
        """
        return sorted(f for f in self.available_families if f != DefaultCFG.EMOJI_FONT)

    def update_json_schema(self, live_schema: dict[str, Any] | None = None) -> None:
        """同步内存 Schema 的下拉选项 (内置样式预设 & 全局字体)

        只改内存中的 `config.schema` (配置面板实时读取它), 不写磁盘
        `_conf_schema.json`: 把本机字体列表写回插件目录会让升级或提交时
        混入环境差异。

        Args:
            live_schema: `config.schema`; 缺省或结构异常时静默跳过。

        字体选项仅在 `scan_fonts()` 成功时改写: 扫描失败得到的是空集合,
        写回会把配置面板的字体下拉框清空, 因此失败时保留原有选项。
        """
        if not isinstance(live_schema, dict):
            return
        try:
            live_items = live_schema["appearance"]["items"]
        except (KeyError, TypeError):
            return
        if not isinstance(live_items, dict):
            return

        changed = False

        # 1. 内置样式预设下拉项 (与 DefaultCFG.PRESETS 保持同步, 含「自定义」)
        #    与字体扫描无关, 扫描失败也要同步, 否则面板显示旧主题名
        preset_item = live_items.get("active_preset")
        if isinstance(preset_item, dict):
            options, labels = _preset_options()
            if preset_item.get("options") != options:
                preset_item["options"] = options
                changed = True
            if preset_item.get("labels") != labels:
                preset_item["labels"] = labels
                changed = True

        # 2. 全局字体优先级选项 (扫描到的字体, 排除固定表情字体)
        font_item = live_items.get("font_order")
        if isinstance(font_item, dict):
            if self._last_scan_ok:
                families = self.get_selectable_families()
                if font_item.get("options") != families:
                    font_item["options"] = families
                    changed = True
            else:
                logger.warning(
                    "[HelpTypst] 字体扫描未成功，保留原字体选项 (不改写 Schema options)"
                )

        if changed:
            logger.info(
                "[HelpTypst] 已更新 Schema 选项（字体 / 主题预设，仅内存，配置面板无需重载）"
            )

    def prune_invalid_config_items(self, config: dict[str, Any]):
        """失效字体清洗 (全局 appearance.font_order)"""
        if not self.available_families:
            return  # 避免扫描失败导致清空配置

        appearance = config.get("appearance", {})
        if not isinstance(appearance, dict):
            return
        current_order = appearance.get("font_order", [])
        if not isinstance(current_order, list):
            return

        # 只保留本地存在且非固定表情字体的项 (表情字体由系统固定追加, 无需用户配置)
        valid_order = [
            f
            for f in current_order
            if f in self.available_families and f != DefaultCFG.EMOJI_FONT
        ]

        # 长度变短 → 有无效项被剔除
        if len(valid_order) != len(current_order):
            appearance["font_order"] = valid_order
            try:
                if hasattr(config, "save_config"):
                    config.save_config()
                    logger.info("[HelpTypst] 已保存清理后的字体配置")
            except Exception as e:
                logger.warning(f"[HelpTypst] 字体配置保存失败: {e}")

    def get_render_font_list(self, user_config_order: list[str]) -> list[str]:
        """生成传给 Typst 的最终字体列表

        表情字体 (DefaultCFG.EMOJI_FONT) 始终固定在列表末尾, 无论用户配置顺序如何:
        即便旧配置中用户曾手动选择过它, 也只会出现在末尾, 不会抢占正文优先回退位。
        """
        final = []
        seen = set()

        # 1. 用户配置 (排除固定表情字体, 由末尾统一追加)
        for f in user_config_order:
            if (
                f in self.available_families
                and f != DefaultCFG.EMOJI_FONT
                and f not in seen
            ):
                final.append(f)
                seen.add(f)

        # 2. 兜底字体 (默认字体顺序 + 固定表情字体), 始终保证列表非空
        for f in [*DefaultCFG.DEFAULT_FONT_ORDER, DefaultCFG.EMOJI_FONT]:
            if f not in seen:
                final.append(f)
                seen.add(f)

        return final

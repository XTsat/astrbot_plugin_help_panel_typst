import json
import os
from pathlib import Path
from typing import Any

import typst

from astrbot.api import logger

from ..domain import DefaultCFG


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

    def _write_schema_atomic(self, schema_path: Path, schema: dict[str, Any]) -> bool:
        """原子写回 Schema 文件 (同目录 .tmp + os.replace)

        直接 open(..., "w") 中途异常会留下半截 JSON, 使配置面板整体不可用;
        此处先写临时文件再替换, 失败时清理临时文件并保留原文件。
        """
        tmp_path = schema_path.with_name(f"{schema_path.name}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(schema, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, schema_path)
            return True
        except Exception as e:
            logger.warning(f"[HelpTypst] Schema 写入失败，已保留原文件: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def update_json_schema(
        self, schema_path: Path, live_schema: dict[str, Any] | None = None
    ) -> None:
        """更新 Schema options (内置样式下拉项 & 全局字体选项)

        Args:
            schema_path: `_conf_schema.json` 的磁盘路径。
            live_schema: AstrBot 启动时从磁盘加载、当前内存中存活的 schema 字典
                (即 `config.schema`, 配置面板实时读取它)。若提供则同步更新,
                使新扫描的字体无需重载插件即可立即出现在配置面板下拉框中。

        字体选项仅在 `scan_fonts()` 成功时改写: 扫描失败得到的是空集合,
        写回会把配置面板的字体下拉框清空, 因此失败时保留原有选项。
        """
        if not schema_path.exists():
            return
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            changed = False

            # 1. 内置样式预设下拉项 (与 DefaultCFG.PRESETS 保持同步, 含「自定义」)
            try:
                target = schema["appearance"]["items"]["active_preset"]
                options = list(DefaultCFG.PRESETS.keys()) + [
                    DefaultCFG.CUSTOM_PRESET_KEY
                ]
                if target.get("options") != options:
                    target["options"] = options
                    changed = True
            except KeyError:
                pass

            # 2. 全局字体优先级选项 (扫描到的字体, 排除固定表情字体)
            try:
                target = schema["appearance"]["items"]["font_order"]
                if self._last_scan_ok:
                    options = self.get_selectable_families()
                    if target.get("options") != options:
                        target["options"] = options
                        changed = True
                else:
                    logger.warning(
                        "[HelpTypst] 字体扫描未成功，保留原字体选项 (不改写 Schema options)"
                    )
            except KeyError:
                pass

            if changed and self._write_schema_atomic(schema_path, schema):
                logger.info(
                    "[HelpTypst] 已更新 Schema 选项，配置面板无需重载即可看到新字体"
                )

            # 同步内存中的 live schema, 立即应用到配置面板 (无需重载插件)
            # 扫描失败时同样保留内存里的原选项
            if (
                live_schema is not None
                and isinstance(live_schema, dict)
                and self._last_scan_ok
            ):
                try:
                    live_items = live_schema["appearance"]["items"]
                    live_font = live_items["font_order"]
                    new_options = self.get_selectable_families()
                    if live_font.get("options") != new_options:
                        live_font["options"] = new_options
                except (KeyError, TypeError):
                    pass
        except Exception as e:
            logger.warning(f"[HelpTypst] Schema 更新失败: {e}")

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

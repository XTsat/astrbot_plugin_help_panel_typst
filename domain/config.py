from dataclasses import dataclass
from typing import Set, List, Dict

from astrbot.api import AstrBotConfig, logger

from . import DefaultCFG

@dataclass
class RenderingConfig:
    timeout_analysis: float
    timeout_compile: float
    max_concurrent_tasks: int
    giant_threshold: int
    webp_limit: int
    split_height: int
    ppi: float

@dataclass
class FilteringConfig:
    ignored_plugins: Set[str]

@dataclass
class ThemePreset:
    """单个外观预设"""
    name: str
    font_order: List[str]
    # 留待未来扩展

@dataclass
class AppearanceConfig:
    """外观配置聚合"""
    active_preset: str
    presets: Dict[str, ThemePreset]

    def get_active_font_order(self) -> List[str]:
        """获取当前激活预设的字体列表"""
        preset = self.presets.get(self.active_preset)
        if preset:
            return preset.font_order
        # 兜底： FontManager 补全默认值
        return []

@dataclass
class TypstPluginConfig:
    """插件全局配置聚合根"""
    rendering: RenderingConfig
    filtering: FilteringConfig
    appearance: AppearanceConfig

    @classmethod
    def load(cls, raw_config: AstrBotConfig) -> 'TypstPluginConfig':
        """工厂方法：从 AstrBotConfig 加载配置，未配置项回退到 DefaultCFG"""
        # 1. Rendering
        raw_render = raw_config.get("rendering", {})
        render_cfg = RenderingConfig(
            timeout_analysis=raw_render.get("timeout_analysis", DefaultCFG.TIMEOUT_ANALYSIS),
            timeout_compile=raw_render.get("timeout_compile", DefaultCFG.TIMEOUT_COMPILE),
            max_concurrent_tasks=int(raw_render.get("max_concurrent_tasks", DefaultCFG.LIMIT_TASK)),
            giant_threshold=raw_render.get("giant_threshold", DefaultCFG.LIMIT_GIANT),
            webp_limit=raw_render.get("webp_limit", DefaultCFG.LIMIT_WEBP),
            split_height=raw_render.get("split_height", DefaultCFG.LIMIT_SIDE),
            ppi=float(raw_render.get("ppi", DefaultCFG.LIMIT_PPI))
        )

        # 2. Filtering
        raw_filter = raw_config.get("filtering", {})
        ignored_list = raw_filter.get("ignored_plugins", None)
        ignored_set = set(ignored_list) if ignored_list else DefaultCFG.IGNORED_PLUGINS.copy()
        filter_cfg = FilteringConfig(ignored_plugins=ignored_set)

        # 3. Appearance
        raw_appearance = raw_config.get("appearance", {})
        active_preset_name = raw_appearance.get("active_preset", "default")
        raw_presets_list = raw_appearance.get("presets", []) # 解析 template_list 列表
        presets_dict = {}

        default_preset = ThemePreset(
            name="default",
            font_order=["Sarasa Gothic SC", "Noto Color Emoji"]
        )
        presets_dict["default"] = default_preset # 兜底： 默认预设

        if isinstance(raw_presets_list, list): 
            for p_data in raw_presets_list:
                # 解析用户配置的列表
                p_name = p_data.get("preset_name", "custom")
                p_fonts = p_data.get("font_order", [])

                presets_dict[p_name] = ThemePreset(
                    name=p_name,
                    font_order=p_fonts
                )

        appearance_cfg = AppearanceConfig(
            active_preset=active_preset_name,
            presets=presets_dict
        )

        logger.debug(f"[HelpTypst] 配置加载完毕: PPI={render_cfg.ppi}, Concurrency={render_cfg.max_concurrent_tasks}, 外观预设: {active_preset_name}")

        return cls(rendering=render_cfg, filtering=filter_cfg, appearance=appearance_cfg)
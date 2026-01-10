from dataclasses import dataclass
from typing import Set

from astrbot.api import AstrBotConfig, logger

from ..domain import DefaultCFG

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
class TypstPluginConfig:
    """插件全局配置聚合根"""
    rendering: RenderingConfig
    filtering: FilteringConfig

    @classmethod
    def load(cls, raw_config: AstrBotConfig) -> 'TypstPluginConfig':
        """
        工厂方法：从 AstrBotConfig 加载配置，未配置项回退到 DefaultCFG
        """
        # 1. 解析 Rendering
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

        # 2. 解析 Filtering
        raw_filter = raw_config.get("filtering", {})

        # List -> Set
        ignored_list = raw_filter.get("ignored_plugins", None)
        if ignored_list is None:
            ignored_set = DefaultCFG.IGNORED_PLUGINS.copy()
        else:
            ignored_set = set(ignored_list)

        filter_cfg = FilteringConfig(
            ignored_plugins=ignored_set
        )

        logger.debug(f"[HelpTypst] 配置加载完毕: PPI={render_cfg.ppi}, Concurrency={render_cfg.max_concurrent_tasks}")
        
        return cls(rendering=render_cfg, filtering=filter_cfg)
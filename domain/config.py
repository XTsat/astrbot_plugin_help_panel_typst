import re
from dataclasses import dataclass, field

from astrbot.api import AstrBotConfig, logger

from . import DefaultCFG

# 预编译正则
HEX_COLOR_REGEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


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
class ThemePreset:
    """单个外观预设"""

    name: str
    font_order: list[str]
    colors: dict[str, str] = field(default_factory=dict)
    # 条目内「启用」开关: 勾选后无论 active_preset 选什么, 都使用此条目作为自定义配色
    enabled: bool = False


@dataclass
class AppearanceConfig:
    """外观配置聚合"""

    active_preset: str
    font_order: list[str]
    presets: dict[str, ThemePreset]  # 内置预设注册 (兼容旧配置中的自定义预设)
    # 内部缓存字段
    _color_cache: dict[str, str] | None = field(init=False, default=None, repr=False)

    def get_active_font_order(self) -> list[str]:
        """获取全局字体优先级列表"""
        return list(self.font_order)

    def get_active_colors(self) -> dict[str, str]:
        """获取激活预设的颜色配置"""
        if self._color_cache is not None:
            return self._color_cache  # 命中缓存

        # 0. 启用开关优先: 列表中存在 enabled=True 的条目时, 无视 active_preset 直接使用
        enabled_preset = self._get_enabled_preset()
        if enabled_preset is not None:
            base = DefaultCFG.DEFAULT_COLORS.copy()
            preset = enabled_preset
        # 1. 基底: 激活预设对应的内置配色 (内置预设锁定, 不受列表条目影响)
        elif self.active_preset == DefaultCFG.CUSTOM_PRESET_KEY:
            # 「自定义」: 使用下方 presets 列表中的自定义配置
            base = DefaultCFG.DEFAULT_COLORS.copy()
            preset = self._get_custom_preset()
        elif self.active_preset in DefaultCFG.PRESETS:
            # 内置预设: 配色固定, 列表条目仅作为「自定义」的配置源
            base = DefaultCFG.PRESETS[self.active_preset].copy()
            preset = None
        else:
            # 旧配置兼容: 直接引用列表中的自定义预设名
            base = DefaultCFG.DEFAULT_COLORS.copy()
            preset = self.presets.get(self.active_preset)

        # 2. 列表条目配色覆盖 (缺失/非法值跳过)
        if preset and preset.colors:
            for key, user_val in preset.colors.items():
                if key not in base:
                    continue

                # 校验
                if self._is_valid_hex(user_val):
                    base[key] = user_val
                else:
                    logger.warning(
                        f"[HelpTypst] 颜色配置异常: '{key}' 的值 '{user_val}' 不是有效的十六进制颜色。\n"
                        f"已回退到默认值: {base[key]}"
                    )

        # 3. 写入缓存
        self._color_cache = base

        return base

    def _get_enabled_preset(self) -> ThemePreset | None:
        """获取列表中被「启用」开关标记的预设 (多个同时启用时取第一个)"""
        for preset in self.presets.values():
            if preset.enabled:
                return preset
        return None

    def _get_custom_preset(self) -> ThemePreset | None:
        """获取自定义预设: 优先启用开关标记的条目 → 用户添加/改名的新条目 → 第一个带配色的条目 (默认即 zhenxun)"""
        # 1. 优先: 被「启用」开关标记的条目
        enabled_preset = self._get_enabled_preset()
        if enabled_preset is not None:
            return enabled_preset

        # 2. 优先: 用户添加/改名的新条目
        for name, preset in self.presets.items():
            if name not in DefaultCFG.PRESETS and preset.colors:
                return preset

        # 3. 回退: 第一个带配色的列表条目 (默认提供 zhenxun)
        for preset in self.presets.values():
            if preset.colors:
                return preset

        return None

    def get_active_category_colors(self) -> dict[str, str]:
        """从激活配色中提取分类主题色 (cat_* 前缀 → 分类名)"""
        colors = self.get_active_colors()
        cat_colors: dict[str, str] = {}
        for key, val in colors.items():
            if key.startswith("cat_"):
                cat_colors[key[4:]] = val
        return cat_colors

    def _is_valid_hex(self, color_str: str) -> bool:
        """校验 Hex Color"""
        if not isinstance(color_str, str):
            return False

        return bool(HEX_COLOR_REGEX.match(color_str))


@dataclass
class TypstPluginConfig:
    """插件全局配置聚合根"""

    enable_waiting_message: bool
    ignored_plugins: set[str]
    custom_font_path: str
    header_background: str
    background_dir: str
    background_random: bool
    hero_header: bool

    rendering: RenderingConfig
    appearance: AppearanceConfig

    @classmethod
    def load(cls, raw_config: AstrBotConfig) -> "TypstPluginConfig":
        """工厂方法：从 AstrBotConfig 加载配置，未配置项回退到 DefaultCFG"""
        enable_wait = raw_config.get("enable_waiting_message", False)

        ignored_list = raw_config.get("ignored_plugins", None)
        ignored_set = (
            set(ignored_list)
            if ignored_list is not None
            else DefaultCFG.IGNORED_PLUGINS.copy()
        )

        # Rendering
        raw_render = raw_config.get("rendering", {})
        render_cfg = RenderingConfig(
            timeout_analysis=raw_render.get(
                "timeout_analysis", DefaultCFG.TIMEOUT_ANALYSIS
            ),
            timeout_compile=raw_render.get(
                "timeout_compile", DefaultCFG.TIMEOUT_COMPILE
            ),
            max_concurrent_tasks=int(
                raw_render.get("max_concurrent_tasks", DefaultCFG.LIMIT_TASK)
            ),
            giant_threshold=raw_render.get("giant_threshold", DefaultCFG.LIMIT_GIANT),
            webp_limit=raw_render.get("webp_limit", DefaultCFG.LIMIT_WEBP),
            split_height=raw_render.get("split_height", DefaultCFG.LIMIT_SIDE),
            ppi=float(raw_render.get("ppi", DefaultCFG.LIMIT_PPI)),
        )

        # Appearance
        raw_appearance = raw_config.get("appearance", {})
        active_preset_name = raw_appearance.get(
            "active_preset", DefaultCFG.DEFAULT_PRESET
        )
        raw_font_order = raw_appearance.get("font_order", None)

        # 全局字体优先级 (旧配置迁移: 缺失时尝试从旧激活预设中提取)
        if not isinstance(raw_font_order, list) or not raw_font_order:
            legacy_fonts = None
            legacy_presets = raw_appearance.get("presets", [])
            if isinstance(legacy_presets, list):
                for p_data in legacy_presets:
                    if p_data.get("preset_name") == active_preset_name:
                        legacy_fonts = p_data.get("font_order", [])
                        break
            font_order = [
                str(f)
                for f in (legacy_fonts or DefaultCFG.DEFAULT_FONT_ORDER)
                if isinstance(f, str)
            ]
        else:
            font_order = [str(f) for f in raw_font_order if isinstance(f, str)]
        if not font_order:  # 清洗后为空 → 回退默认值
            font_order = DefaultCFG.DEFAULT_FONT_ORDER.copy()

        raw_presets_list = raw_appearance.get("presets", [])  # 旧配置兼容
        presets_dict = {}

        # 内置预设注册 (配色由 DefaultCFG.PRESETS 提供, 此处仅登记名称与字体)
        for preset_name in DefaultCFG.PRESETS:
            presets_dict[preset_name] = ThemePreset(
                name=preset_name,
                font_order=font_order.copy(),
                colors={},
            )

        if isinstance(raw_presets_list, list):
            for p_data in raw_presets_list:
                # 解析旧配置的列表 (仅用于颜色覆盖兼容)
                p_name = p_data.get("preset_name", "custom")
                p_fonts = p_data.get("font_order", [])

                # 解析颜色配置 (旧配置中微调过的内置预设颜色覆盖仍生效)
                p_colors = {}
                for color_key in DefaultCFG.DEFAULT_COLORS.keys():
                    if color_key in p_data:
                        raw_val = p_data[color_key]  # 防 None、数字类型传入
                        p_colors[color_key] = (
                            str(raw_val) if raw_val is not None else ""
                        )

                # 「启用」开关: 只有真正的 Python True 才算启用 (防御异常值)
                p_enabled = p_data.get("enabled") is True

                presets_dict[p_name] = ThemePreset(
                    name=p_name,
                    font_order=p_fonts,
                    colors=p_colors,
                    enabled=p_enabled,
                )

        appearance_cfg = AppearanceConfig(
            active_preset=active_preset_name,
            font_order=font_order,
            presets=presets_dict,
        )

        custom_font_path = raw_config.get("custom_font_path", "")
        header_background = raw_config.get("header_background", "")
        background_dir = raw_config.get("background_dir", "")
        background_random = bool(raw_config.get("background_random", True))
        hero_header = bool(raw_config.get("hero_header", True))

        logger.debug(
            f"[HelpTypst] 配置加载完毕: PPI={render_cfg.ppi}, Concurrency={render_cfg.max_concurrent_tasks}, 外观预设: {active_preset_name}"
        )

        return cls(
            enable_waiting_message=enable_wait,
            ignored_plugins=ignored_set,
            custom_font_path=custom_font_path,
            header_background=header_background,
            background_dir=background_dir,
            background_random=background_random,
            hero_header=hero_header,
            rendering=render_cfg,
            appearance=appearance_cfg,
        )

import os
import re
from dataclasses import dataclass, field
from typing import Any

from astrbot.api import AstrBotConfig, logger

from . import DefaultCFG, InternalCFG

# 预编译正则
HEX_COLOR_REGEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _is_valid_hex(color_str: Any) -> bool:
    """校验 Hex Color (模块级复用: 外观预设 & 分类规则共用)"""
    if not isinstance(color_str, str):
        return False
    return bool(HEX_COLOR_REGEX.match(color_str))


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """整数配置收敛: 类型异常回落默认值, 超界截断 (防御手工改坏的配置)"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    """浮点配置收敛: 类型异常回落默认值, 超界截断"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _as_bool(value: Any, default: bool) -> bool:
    """布尔配置解析: 兼容面板/手工配置写入的 "true"/"false"/"1"/"0" 字符串

    直接用 bool("false") 会得到 True, 所以只认明确取值, 其它类型回落默认值。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    return default


def _as_choice(value: Any, default: str, allowed: tuple[str, ...]) -> str:
    """枚举配置解析: 只认白名单里的取值, 其它一律回落默认值

    面板下拉与手工配置都可能写入大小写不一致或已下线的取值, 不做白名单收敛会让
    出图扩展名与配置项对不上。
    """
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in allowed:
            return normalized
    return default


def _parse_name_list(value: Any) -> set[str]:
    """插件名列表解析: 单个字符串按一项处理, 非字符串项丢弃

    面板可能把单条目存成字符串; 这里与 ignored_plugins 的口径保持一致,
    避免 set("abc") 被拆成字符集。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {
        name.strip() for name in value if isinstance(name, str) and name.strip()
    }


@dataclass
class RenderingConfig:
    timeout_analysis: float
    timeout_compile: float
    max_concurrent_tasks: int
    giant_threshold: int
    webp_limit: int
    split_height: int
    ppi: float
    page_width: float
    single_column_threshold: float
    plugin_two_lines: bool
    output_format: str


@dataclass
class ThemePreset:
    """单个外观预设 (仅配色; 字体优先级已迁移为全局 appearance.font_order)"""

    name: str
    colors: dict[str, str] = field(default_factory=dict)
    # 条目内「启用」开关: 勾选后无论 active_preset 选什么, 都使用此条目作为自定义配色
    enabled: bool = False


@dataclass
class AppearanceConfig:
    """外观配置聚合"""

    active_preset: str
    font_order: list[str]
    presets: dict[str, ThemePreset]  # 内置预设注册 (兼容旧配置中的自定义预设)
    # 一次性「重新扫描字体」开关: 勾选保存后, 插件重载时自动扫描一次字体并自动关闭
    rescan_fonts: bool = False
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

    def get_category_slots(self) -> list[str]:
        """获取主题的通用分类色槽 (cat_slot_0..N, 按编号升序)

        分类卡片标题栏统一从此取色: 分类规则按槽位绑定 (category.rules 条目 color 字段
        填 slot_N) 或自动按列表顺序分配, 随主题切换自动变化。
        槽位 0 为兜底分类默认色, 主题未定义任何色槽时回退为默认色板
        (DefaultCFG.DEFAULT_CATEGORY_SLOTS)。
        """
        colors = self.get_active_colors()
        slots: list[str] = []
        idx = 0
        while True:
            val = colors.get(f"cat_slot_{idx}")
            if val is None:
                break
            if _is_valid_hex(val):
                slots.append(val)
            idx += 1

        if not slots:
            slots = list(DefaultCFG.DEFAULT_CATEGORY_SLOTS)
        return slots

    def _is_valid_hex(self, color_str: str) -> bool:
        """校验 Hex Color"""
        return _is_valid_hex(color_str)


@dataclass
class CategoryRule:
    """单条插件分类规则 (设置面板 category.rules 列表条目)

    匹配逻辑: 插件元信息 (desc/name/display_name/tags) 中出现任一关键词即归入该分类。
    列表顺序即匹配优先级: 命中第一个匹配的规则即返回, 全部未命中时归入兜底分类。
    """

    name: str  # 分类名 (卡片标题 / 编号分组依据)
    keywords: list[str]  # 匹配关键词 (大小写不敏感, 子串匹配)
    enabled: bool = True  # 启用开关: 关闭后该规则不参与匹配
    # 分类卡片主题色 (可选): 留空自动分配主题色槽; 填 slot_N 绑定主题色槽 (随主题变化);
    # 填 #RRGGBB 固定颜色 (不随主题)。非法值回退为空串
    color: str = ""


@dataclass
class CategoryConfig:
    """插件分类规则聚合: 用户自定义规则列表 + 兜底分类 (名称与颜色)

    兜底分类单独配置 (category.fallback / category.fallback_color), 始终存在,
    作为未命中任何关键词时的保底; 默认配置 (DefaultCFG.DEFAULT_CATEGORY_KEYWORDS
    + 槽位绑定) 在设置面板预置导入, 用户可自由修改。
    """

    rules: list[CategoryRule]
    fallback: str
    # 兜底分类卡片颜色: "" 灰蓝 / slot_N 主题色槽 (随主题) / #RRGGBB 固定色
    fallback_color: str = ""

    def match(self, text: str) -> str:
        """按规则顺序匹配关键词: 命中第一个匹配的规则即返回分类名, 全部未命中返回兜底分类名"""
        lowered = text.lower()
        for rule in self.rules:
            if not rule.enabled:
                continue
            for kw in rule.keywords:
                if kw.lower() in lowered:
                    return rule.name
        return self.fallback

    def get_rule(self, name: str) -> CategoryRule | None:
        """按分类名取规则 (用于解析自定义分类色)"""
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def to_plain(self) -> dict:
        """转为可 JSON 序列化的快照结构 (缓存校验用)"""
        return {
            "fallback": self.fallback,
            "fallback_color": self.fallback_color,
            "rules": [
                {
                    "name": rule.name,
                    "keywords": list(rule.keywords),
                    "enabled": rule.enabled,
                    "color": rule.color,
                }
                for rule in self.rules
            ],
        }


@dataclass
class TypstPluginConfig:
    """插件全局配置聚合根"""

    enable_waiting_message: bool
    # 面板多选命中的已安装插件（配置面板的勾选项）
    ignored_plugins: set[str]
    # 用户手填的自定义屏蔽名（未安装/旧名），与 ignored_plugins 取并集后生效
    ignored_plugins_custom: set[str]
    custom_font_path: str
    header_background: str
    background_dir: str
    background_random: bool
    hero_header: bool

    rendering: RenderingConfig
    appearance: AppearanceConfig
    category: CategoryConfig

    @property
    def effective_ignored_plugins(self) -> set[str]:
        """实际生效的屏蔽集 = 面板勾选的已安装插件 + 自定义条目

        分两个键存是为了让配置面板能把「已安装插件」做成多选、
        把未安装的名字放进自由输入框；渲染侧只关心并集。
        """
        return self.ignored_plugins | self.ignored_plugins_custom

    @classmethod
    def load(cls, raw_config: AstrBotConfig) -> "TypstPluginConfig":
        """工厂方法：从 AstrBotConfig 加载配置，未配置项回退到 DefaultCFG"""
        enable_wait = _as_bool(raw_config.get("enable_waiting_message"), False)

        # 黑名单: 字符串按单个插件名处理 (面板误存/手工配置 → 不能被 set() 拆成字符集),
        # 混入的非字符串项过滤掉, 否则缓存快照的 sorted() 会抛 TypeError
        raw_ignored = raw_config.get("ignored_plugins")
        if isinstance(raw_ignored, (list, str)):
            ignored_set = _parse_name_list(raw_ignored)
        else:
            ignored_set = set(DefaultCFG.IGNORED_PLUGINS)

        # 自定义屏蔽名: 新键缺失时的兜底要看老配置的形态——老配置的屏蔽项全在
        # ignored_plugins 里, 此时预置模板默认会把用户删掉的名字又加回来;
        # 只有连 ignored_plugins 都没有(全新配置)才用模板默认值
        raw_custom = raw_config.get("ignored_plugins_custom")
        if isinstance(raw_custom, (list, str)):
            ignored_custom_set = _parse_name_list(raw_custom)
        elif isinstance(raw_ignored, (list, str)):
            ignored_custom_set = set()
        else:
            ignored_custom_set = set(DefaultCFG.IGNORED_PLUGINS_CUSTOM)

        # Rendering (null / 非 dict → 空配置, 全部走 DefaultCFG 兜底)
        raw_render = raw_config.get("rendering")
        if not isinstance(raw_render, dict):
            raw_render = {}

        output_format = _as_choice(
            raw_render.get("output_format"),
            DefaultCFG.OUTPUT_FORMAT,
            DefaultCFG.OUTPUT_FORMATS,
        )
        # 单图高度上限已并入分页高度, 不再单独配置: 直接取所选格式能承载的最大高度,
        # 页面高度由 split_height 控制, 只要它不超过该值就不会再触发二次切片
        format_max_side = InternalCFG.FORMAT_MAX_SIDE[output_format]
        webp_limit = min(DefaultCFG.MAX_LIMIT_SIDE, format_max_side)
        render_cfg = RenderingConfig(
            timeout_analysis=_as_float(
                raw_render.get("timeout_analysis"),
                DefaultCFG.TIMEOUT_ANALYSIS,
                DefaultCFG.MIN_TIMEOUT_ANALYSIS,
                DefaultCFG.MAX_TIMEOUT,
            ),
            timeout_compile=_as_float(
                raw_render.get("timeout_compile"),
                DefaultCFG.TIMEOUT_COMPILE,
                DefaultCFG.MIN_TIMEOUT_COMPILE,
                DefaultCFG.MAX_TIMEOUT,
            ),
            max_concurrent_tasks=_as_int(
                raw_render.get("max_concurrent_tasks"),
                DefaultCFG.LIMIT_TASK,
                DefaultCFG.MIN_CONCURRENCY,
                DefaultCFG.MAX_CONCURRENCY,
            ),
            giant_threshold=_as_int(
                raw_render.get("giant_threshold"),
                DefaultCFG.LIMIT_GIANT,
                DefaultCFG.MIN_GIANT,
                DefaultCFG.MAX_GIANT,
            ),
            webp_limit=webp_limit,
            # 分页高度也不能超过所选格式的单图上限, 否则页面本身写不进该格式
            split_height=_as_int(
                raw_render.get("split_height"),
                DefaultCFG.LIMIT_SIDE,
                DefaultCFG.MIN_SPLIT_HEIGHT,
                min(DefaultCFG.MAX_LIMIT_SIDE, format_max_side),
            ),
            ppi=_as_float(
                raw_render.get("ppi"),
                DefaultCFG.LIMIT_PPI,
                DefaultCFG.MIN_PPI,
                DefaultCFG.MAX_PPI,
            ),
            page_width=_as_float(
                raw_render.get("page_width"),
                DefaultCFG.LIMIT_WIDTH,
                DefaultCFG.MIN_PAGE_WIDTH,
                DefaultCFG.MAX_PAGE_WIDTH,
            ),
            # 阈值允许大于页宽 (等于强制单列), 因此上界与页宽一致
            single_column_threshold=_as_float(
                raw_render.get("single_column_threshold"),
                DefaultCFG.LIMIT_SINGLE_COLUMN_THRESHOLD,
                DefaultCFG.MIN_PAGE_WIDTH,
                DefaultCFG.MAX_PAGE_WIDTH,
            ),
            plugin_two_lines=_as_bool(
                raw_render.get("plugin_two_lines"),
                DefaultCFG.PLUGIN_TWO_LINES,
            ),
            output_format=output_format,
        )

        # Appearance (null / 非 dict → 空配置, 全部走 DefaultCFG 兜底)
        raw_appearance = raw_config.get("appearance")
        if not isinstance(raw_appearance, dict):
            raw_appearance = {}
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
                    if not isinstance(p_data, dict):
                        continue
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

        # 内置预设注册 (配色由 DefaultCFG.PRESETS 提供, 此处仅登记名称)
        for preset_name in DefaultCFG.PRESETS:
            presets_dict[preset_name] = ThemePreset(name=preset_name, colors={})

        if isinstance(raw_presets_list, list):
            for p_data in raw_presets_list:
                if not isinstance(p_data, dict):
                    continue
                # 解析旧配置的列表 (仅用于颜色覆盖兼容)
                p_name = p_data.get("preset_name", "custom")

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
                    colors=p_colors,
                    enabled=p_enabled,
                )

        appearance_cfg = AppearanceConfig(
            active_preset=active_preset_name,
            font_order=font_order,
            presets=presets_dict,
            rescan_fonts=_as_bool(raw_appearance.get("rescan_fonts"), False),
        )

        # Category (插件分类规则)
        # 结构: category = { "fallback": "其他", "fallback_color": "slot_8",
        #                    "rules": [ {category_name, enabled, keywords, color}, ... ] }
        # - fallback/fallback_color: 兜底分类的名称与颜色, 独立于规则列表配置, 始终存在 (保底)
        # - rules: 分类规则列表 (设置面板 template_list, 与主题预设列表同格式), 列表顺序即匹配优先级;
        #   条目 color 字段: 留空自动分配主题色槽 / slot_N 绑定主题色槽 (随主题) / #RRGGBB 固定色
        raw_category = raw_config.get("category", {})
        if not isinstance(raw_category, dict):
            raw_category = {}

        raw_fallback = str(raw_category.get("fallback", "") or "").strip()
        fallback = raw_fallback or DefaultCFG.DEFAULT_CATEGORY_FALLBACK

        # 兜底分类颜色: "" 灰蓝 / slot_N 主题色槽 (随主题) / #RRGGBB 固定色
        raw_fallback_color = str(raw_category.get("fallback_color", "") or "").strip()
        fallback_color = (
            raw_fallback_color or DefaultCFG.DEFAULT_CATEGORY_FALLBACK_COLOR
        )
        is_fallback_slot = bool(re.fullmatch(r"slot_\d+", fallback_color))
        if (
            fallback_color
            and not is_fallback_slot
            and not _is_valid_hex(fallback_color)
        ):
            logger.warning(
                f"[HelpTypst] 兜底分类颜色配置异常: '{fallback_color}' "
                f"不是有效的十六进制颜色或色槽编号 (slot_N), 已回退为灰蓝"
            )
            fallback_color = ""

        raw_rules_list = raw_category.get("rules", None)
        if not isinstance(raw_rules_list, list):
            # 配置缺失 (首次安装/旧版本升级) → 导入默认规则 (预绑定主题色槽) 作为可自由修改的预置
            rules = [
                CategoryRule(
                    name=name,
                    keywords=list(kws),
                    color=DefaultCFG.DEFAULT_CATEGORY_SLOT_BINDINGS.get(name, ""),
                )
                for name, kws in DefaultCFG.DEFAULT_CATEGORY_KEYWORDS.items()
            ]
        else:
            rules = []
            for item in raw_rules_list:
                if not isinstance(item, dict):
                    continue
                rule_name = str(item.get("category_name", "") or "").strip()

                raw_keywords = item.get("keywords", [])
                keywords: list[str] = []
                if isinstance(raw_keywords, list):
                    for kw in raw_keywords:
                        if isinstance(kw, str) and kw.strip():
                            kw_clean = kw.strip()
                            if kw_clean not in keywords:  # 去重, 保持顺序
                                keywords.append(kw_clean)

                if not rule_name or not keywords:
                    logger.warning(
                        f"[HelpTypst] 分类规则异常: 名称或关键词为空, 已跳过该规则: {item}"
                    )
                    continue

                # 规则自带主题色 (可选): 合法值为 固定 hex (#RRGGBB) 或 主题色槽绑定 (slot_N)
                # 非法值回退为空串 (走 主题 cat_<名称>/自动分配/灰蓝 兜底)
                rule_color = str(item.get("color", "") or "").strip()
                is_slot_binding = bool(re.fullmatch(r"slot_\d+", rule_color))
                if rule_color and not is_slot_binding and not _is_valid_hex(rule_color):
                    logger.warning(
                        f"[HelpTypst] 分类「{rule_name}」的颜色配置异常: '{rule_color}' "
                        f"不是有效的十六进制颜色或色槽编号 (slot_N), 已回退为主题色板/自动分配"
                    )
                    rule_color = ""

                # 「启用」开关: 缺省视为启用, 只有显式 false 才关闭
                rule_enabled = item.get("enabled", True) is True

                rules.append(
                    CategoryRule(
                        name=rule_name,
                        keywords=keywords,
                        enabled=rule_enabled,
                        color=rule_color,
                    )
                )

        category_cfg = CategoryConfig(
            rules=rules, fallback=fallback, fallback_color=fallback_color
        )

        # 路径项: 展开 ~ (否则 "~/fonts" 会被当成相对路径), 非字符串回落默认
        raw_custom_font_path = raw_config.get("custom_font_path", "")
        custom_font_path = (
            os.path.expanduser(raw_custom_font_path.strip())
            if isinstance(raw_custom_font_path, str)
            else ""
        )
        header_background = raw_config.get("header_background", "")
        background_dir = raw_config.get("background_dir", "")
        background_random = _as_bool(raw_config.get("background_random"), True)
        hero_header = _as_bool(raw_config.get("hero_header"), True)

        logger.debug(
            f"[HelpTypst] 配置加载完毕: PPI={render_cfg.ppi}, Concurrency={render_cfg.max_concurrent_tasks}, 外观预设: {active_preset_name}"
        )

        return cls(
            enable_waiting_message=enable_wait,
            ignored_plugins=ignored_set,
            ignored_plugins_custom=ignored_custom_set,
            custom_font_path=custom_font_path,
            header_background=header_background,
            background_dir=background_dir,
            background_random=background_random,
            hero_header=hero_header,
            rendering=render_cfg,
            appearance=appearance_cfg,
            category=category_cfg,
        )

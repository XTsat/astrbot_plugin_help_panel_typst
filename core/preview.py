"""网页实时预览（Plugin Pages）后端

把「样式 → 渲染配置 → Typst 编译 → 图片」这条链路抽出来，供 dashboard 的
pages/preview 页面调用。预览始终走临时文件，不读写正式发图的静态缓存。
"""

import asyncio
import base64
import copy
import hashlib
import io
import json
import re
import time
import uuid
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Star

from ..domain import DefaultCFG, InternalCFG, ThemePreset, TypstPluginConfig
from ..domain.config import HEX_COLOR_REGEX, CategoryConfig, CategoryRule
from ..utils import FontManager, TypstLayout, calculate_hash
from .renderer import TypstRenderer

DataProvider = Callable[[Path], int]
ProviderBuilder = Callable[
    [str, str | None, TypstLayout, list[str], str, TypstPluginConfig], DataProvider
]
PluginLister = Callable[[], list[dict[str, Any]]]
PersonaGetter = Callable[[], Awaitable[str]]


class PreviewError(Exception):
    """可直接展示给用户的预览错误"""


# ---- 展示文案（只服务预览页，不影响渲染） ----

_MODE_LABELS: tuple[tuple[str, str], ...] = (
    ("command", "指令菜单"),
    ("command_detail", "详细菜单"),
    ("event", "事件监听"),
    ("filter", "过滤器"),
)

_BRAND_COLOR_DEFS: tuple[tuple[str, str], ...] = (
    ("brand_sky", "主色"),
    ("brand_navy", "结构色"),
    ("brand_mint", "浅色高光"),
    ("brand_cream", "奶油强调"),
    ("brand_gold", "金色强调"),
    ("brand_blush", "柔和辅助"),
    ("brand_ink", "正文深色"),
    ("brand_gray", "次级文字"),
    ("brand_card", "卡片背景"),
    ("brand_border", "卡片边框"),
    ("brand_soft", "插件行边框"),
    ("brand_ghost", "禁用行背景"),
)

_CATEGORY_COLOR_DEFS: tuple[tuple[str, str], ...] = (
    ("cat_slot_0", "分类槽 0 · 兜底"),
    ("cat_slot_1", "分类槽 1"),
    ("cat_slot_2", "分类槽 2"),
    ("cat_slot_3", "分类槽 3"),
    ("cat_slot_4", "分类槽 4"),
    ("cat_slot_5", "分类槽 5"),
    ("cat_slot_6", "分类槽 6"),
    ("cat_slot_7", "分类槽 7"),
    ("cat_slot_8", "分类槽 8"),
    ("cat_slot_9", "分类槽 9"),
)

_GENERAL_COLOR_DEFS: tuple[tuple[str, str], ...] = (
    ("page_fill", "页面背景"),
    ("c_plugin_name", "插件名"),
    ("c_plugin_id", "插件 ID"),
    ("c_group_title", "分组标题"),
    ("c_bullet", "强调圆点"),
    ("c_event_icon", "事件图标"),
    ("c_leaf_text", "正文文字"),
    ("c_desc_text", "描述文字"),
    ("c_group_bg", "分组背景"),
    ("c_rich_bg", "富文本背景"),
    ("c_box_bg", "区块背景"),
    ("c_box_stroke", "区块描边"),
    ("c_text_primary", "主要文字"),
    ("c_regex_bg", "搜索高亮背景"),
    ("c_regex_text", "搜索高亮文字"),
    ("c_regex_icon", "搜索高亮图标"),
    ("c_tag_admin", "管理员标签"),
    ("c_tag_event", "事件标签"),
    ("c_tag_mcp", "MCP 标签"),
    ("c_tag_id", "ID 标签"),
    ("c_ver_bg", "版本标签背景"),
    ("c_ver_text", "版本标签文字"),
    ("c_prio_bg", "优先级标签背景"),
    ("c_prio_text", "优先级标签文字"),
    ("c_highlight_bg", "高亮背景"),
    ("c_highlight_text", "高亮文字"),
    ("c_on_light", "浅底强调文字"),
)

_KNOWN_COLOR_KEYS: set[str] = {
    key
    for defs in (
        _BRAND_COLOR_DEFS,
        _CATEGORY_COLOR_DEFS,
        _GENERAL_COLOR_DEFS,
    )
    for key, _ in defs
}


def _as_bool(value: Any, default: bool) -> bool:
    """布尔解析：兼容前端传 "true"/"false" 字符串"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    return default


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    """浮点收敛：类型异常回落默认值，越界截断"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _normalize_color(value: Any) -> str | None:
    """合法 hex 颜色返回去空白后的值，否则 None"""
    if not isinstance(value, str):
        return None
    color = value.strip()
    return color if HEX_COLOR_REGEX.match(color) else None


def _normalize_names(value: Any) -> list[str]:
    """插件名列表归一化: 去空白、去空项、去重并保留原顺序"""
    # 与配置读取的解析保持一致: 单个字符串按一个名字处理, 其它类型视为空
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _format_max_height(output_format: str) -> int:
    """所选格式能承载的最大单图高度（配置上限与格式硬限制取小）"""
    max_side = InternalCFG.FORMAT_MAX_SIDE.get(
        output_format, InternalCFG.FORMAT_MAX_SIDE[DefaultCFG.OUTPUT_FORMAT]
    )
    return min(DefaultCFG.MAX_LIMIT_SIDE, max_side)


def _color_map(colors: dict[str, str]) -> dict[str, str]:
    """配色归一成小写后比较：预设与前端输入可能大小写不同"""
    return {
        key: value.strip().lower()
        for key, value in colors.items()
        if isinstance(value, str)
    }


_SLOT_COLOR_RE = re.compile(r"slot_[0-9]")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD_RE = re.compile(r"[a-z][a-z0-9]{1,}")
# 片段位于中文串首尾时没有邻字，用空串占位，避免被当成「总是跟着某个字」
_HOT_WORD_EDGE = ""


def _normalize_slot_or_color(value: Any) -> str:
    """分类颜色只接受主题色槽 slot_0~slot_9 或 #RRGGBB，其它值退回「自动分配」"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if _SLOT_COLOR_RE.fullmatch(text):
        return text
    normalized = _normalize_color(text)
    return normalized.lower() if normalized is not None else ""


def _normalize_keywords(value: Any) -> list[str]:
    """关键词去空白/空项，按大小写不敏感去重并截断到配置长度上限"""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    keywords: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        keyword = item.strip()[: InternalCFG.PREVIEW_CATEGORY_KEYWORD_MAX]
        lowered = keyword.lower()
        if keyword and lowered not in seen:
            seen.add(lowered)
            keywords.append(keyword)
        if len(keywords) >= InternalCFG.PREVIEW_CATEGORY_KEYWORDS_MAX:
            break
    return keywords


def _plugin_match_text(plugin: dict[str, Any]) -> str:
    """与 CategoryConfig.match 的匹配文案保持一致：name + display_name + short_desc + desc"""
    parts = (
        plugin.get("name"),
        plugin.get("display_name"),
        plugin.get("short_desc"),
        plugin.get("desc"),
    )
    return " ".join(
        str(part).strip() for part in parts if isinstance(part, str) and part.strip()
    ).lower()


def _hot_word_sources(plugin: dict[str, Any]) -> list[tuple[int, str]]:
    """热词来源按权重分层：名称/显示名 > 简短描述 > 描述

    作者写在标题与简短描述里的词最能代表插件用途；描述正文常是「支持」「一键」
    这类营销套话，只做兜底，因此加权而不是「只取标题」——只取标题会让样本量
    太小的插件集凑不满热词。
    """
    title = " ".join(
        str(plugin.get(key) or "").strip() for key in ("name", "display_name")
    )
    sources = (
        (InternalCFG.PREVIEW_HOT_WORD_TITLE_WEIGHT, title),
        (InternalCFG.PREVIEW_HOT_WORD_SHORT_DESC_WEIGHT, plugin.get("short_desc")),
        (InternalCFG.PREVIEW_HOT_WORD_DESC_WEIGHT, plugin.get("desc")),
    )
    return [
        (weight, str(text).lower())
        for weight, text in sources
        if isinstance(text, str) and text.strip()
    ]


@dataclass
class _HotWordStat:
    """单个候选词的累计信息：命中插件数、来源权重、左右邻字与出现位置数"""

    plugins: int = 0
    weight: int = 0
    positions: int = 0
    left: Counter[str] = field(default_factory=Counter)
    right: Counter[str] = field(default_factory=Counter)


def _collect_hot_word_stats(
    plugins: list[dict[str, Any]],
) -> tuple[dict[str, _HotWordStat], dict[str, int]]:
    """统计 2~POOL_MAX_LEN 字片段，返回（候选词明细, 全部片段的命中插件数）

    统计池比候选池多留一个字：判断「器人」是否碎片时要知道它被更长的「机器人」
    包住，而「机器人」本身可能因停用词过滤或超过候选长度而不进最终列表。
    """
    stats: dict[str, _HotWordStat] = {}
    counts: dict[str, int] = {}
    for plugin in plugins:
        seen: set[str] = set()
        for weight, text in _hot_word_sources(plugin):
            for run in _CJK_RUN_RE.findall(text):
                length = len(run)
                for size in range(
                    InternalCFG.PREVIEW_HOT_WORD_MIN_LEN,
                    InternalCFG.PREVIEW_HOT_WORD_POOL_MAX_LEN + 1,
                ):
                    if size > length:
                        break
                    for index in range(length - size + 1):
                        token = run[index : index + size]
                        first_seen = token not in seen
                        if first_seen:
                            seen.add(token)
                            counts[token] = counts.get(token, 0) + 1
                        if size > InternalCFG.PREVIEW_HOT_WORD_MAX_LEN:
                            continue
                        stat = stats.get(token)
                        if stat is None:
                            stat = stats[token] = _HotWordStat()
                        if first_seen:
                            stat.plugins += 1
                            stat.weight += weight
                        stat.positions += 1
                        stat.left[run[index - 1] if index > 0 else _HOT_WORD_EDGE] += 1
                        stat.right[
                            run[index + size]
                            if index + size < length
                            else _HOT_WORD_EDGE
                        ] += 1
            for word in _LATIN_WORD_RE.findall(text):
                if word in seen:
                    continue
                seen.add(word)
                counts[word] = counts.get(word, 0) + 1
                stat = stats.get(word)
                if stat is None:
                    stat = stats[word] = _HotWordStat()
                stat.plugins += 1
                stat.weight += weight
    return stats, counts


def _is_hot_word_fragment(
    token: str, stat: _HotWordStat, counts: dict[str, int]
) -> bool:
    """片段是否几乎总是跟着同一个邻字出现：「器人」几乎都长在「机器人」里"""
    ratio = InternalCFG.PREVIEW_HOT_WORD_FRAGMENT_RATIO
    if stat.positions <= 0:
        return False
    for neighbors, attach_left in ((stat.right, False), (stat.left, True)):
        char, hits = neighbors.most_common(1)[0]
        if char == _HOT_WORD_EDGE or hits / stat.positions < ratio:
            continue
        extended = char + token if attach_left else token + char
        if counts.get(extended, 0) >= stat.plugins * ratio:
            return True
    return False


def _extract_hot_words(plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从插件元信息里提炼可点击的分类关键词

    候选词 = 中文 2~3 字片段 + 英文单词，过滤停用词、半个词与碎片；按来源权重
    （标题 > 简短描述 > 描述）排序，让作者自己写的用途词排在「一键」「支持」
    这类正文套话前面；同一批插件里互相包含的词只保留更常见的那个。
    """
    stats, counts = _collect_hot_word_stats(plugins)
    stopwords = InternalCFG.PREVIEW_HOT_WORD_STOPWORDS
    noise = InternalCFG.PREVIEW_HOT_WORD_LATIN_NOISE
    edge_chars = InternalCFG.PREVIEW_HOT_WORD_EDGE_CHARS
    candidates: list[dict[str, Any]] = []
    for word, stat in stats.items():
        if stat.plugins < InternalCFG.PREVIEW_HOT_WORD_MIN_COUNT:
            continue
        if word in stopwords or word in noise:
            continue
        if _CJK_RUN_RE.fullmatch(word):
            if _is_hot_word_fragment(word, stat, counts):
                continue
            if word[0] in edge_chars or word[-1] in edge_chars:
                continue
        candidates.append({"word": word, "count": stat.plugins, "weight": stat.weight})

    candidates.sort(
        key=lambda item: (
            -item["weight"],
            -item["count"],
            len(item["word"]),
            item["word"],
        )
    )
    picked: list[dict[str, Any]] = []
    for item in candidates:
        word = item["word"]
        # 更常见（出现插件数更多）的包含词已经入列时，同频或更低频的子串/超串都不再占位
        if any(
            (word in kept["word"] or kept["word"] in word)
            and kept["count"] >= item["count"]
            for kept in picked
        ):
            continue
        picked.append(item)
        if len(picked) >= InternalCFG.PREVIEW_HOT_WORD_LIMIT:
            break
    return [{"word": item["word"], "count": item["count"]} for item in picked]


def _category_signature(category: dict[str, Any]) -> str:
    """分类结构归一化后比较：颜色大小写、关键词顺序不构成真实改动"""
    rules = category.get("rules")
    return json.dumps(
        {
            "fallback": str(category.get("fallback") or ""),
            "fallback_color": str(category.get("fallback_color") or "").lower(),
            "rules": [
                {
                    "name": str(rule.get("name") or ""),
                    "keywords": sorted(
                        str(keyword).lower()
                        for keyword in rule.get("keywords") or []
                    ),
                    "enabled": bool(rule.get("enabled", True)),
                    "color": str(rule.get("color") or "").lower(),
                }
                for rule in (rules if isinstance(rules, list) else [])
                if isinstance(rule, dict)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


@dataclass
class PreviewCategoryRule:
    """预览态的单条分类规则，字段与配置面板 category.rules 一一对应"""

    name: str
    keywords: list[str]
    enabled: bool = True
    color: str = ""

    def to_plain(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "keywords": list(self.keywords),
            "enabled": self.enabled,
            "color": self.color,
        }


@dataclass
class PreviewCategory:
    """预览态的分类配置（规则 + 兜底分类）"""

    fallback: str
    fallback_color: str
    rules: list[PreviewCategoryRule]

    def to_plain(self) -> dict[str, Any]:
        return {
            "fallback": self.fallback,
            "fallback_color": self.fallback_color,
            "rules": [rule.to_plain() for rule in self.rules],
        }


def _preset_palette_colors(raw_colors: Any) -> dict[str, str]:
    """把条目里的部分颜色补全成完整色板: 旧配置常只存被微调过的键"""
    palette = dict(DefaultCFG.DEFAULT_COLORS)
    if isinstance(raw_colors, dict):
        for key, value in raw_colors.items():
            if key not in palette:
                continue
            normalized = _normalize_color(value)
            if normalized is not None:
                palette[key] = normalized
    return palette


def _unique_preset_name(raw: Any, used: set[str]) -> str:
    """收敛自定义模板名: 去空白、限长, 并避开内置预设名与已用名"""
    name = str(raw or "").strip()[: InternalCFG.PREVIEW_PRESET_NAME_MAX]
    reserved = set(DefaultCFG.PRESETS) | set(DefaultCFG.PRESET_LABELS.values())
    reserved.add(DefaultCFG.CUSTOM_PRESET_KEY)
    base = name or DefaultCFG.CUSTOM_PRESET_KEY
    candidate = base
    counter = 2
    while candidate in used or candidate in reserved:
        candidate = f"{base} {counter}"
        counter += 1
    return candidate


@dataclass
class PreviewStyle:
    """一次预览请求的样式快照"""

    preset: str
    colors: dict[str, str]
    fonts: list[str]
    page_width: float
    ppi: float
    test_ppi: float
    split_height: int
    single_column_threshold: float
    giant_threshold: int
    output_format: str
    timeout_analysis: float
    timeout_compile: float
    plugin_two_lines: bool
    hero_header: bool
    background: str
    # 生效屏蔽集拆成两路: 面板勾选的已安装插件 + 手填的自定义条目
    ignored_plugins: list[str]
    ignored_plugins_custom: list[str]
    # 分类规则与兜底分类: 只影响 /helps 的分类归属与卡片标题, 不参与模板配色
    category: PreviewCategory
    # 面板自定义模板列表(顺序即配置列表顺序, 首条固定「自定义」); 只在应用配置时使用,
    # 不进 to_plain(), 否则改名/增删模板会让预览缓存无故失效
    custom_presets: list[dict[str, Any]] = field(default_factory=list)

    def to_plain(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "colors": self.colors,
            "fonts": self.fonts,
            "page_width": self.page_width,
            "ppi": self.ppi,
            "test_ppi": self.test_ppi,
            "split_height": self.split_height,
            "single_column_threshold": self.single_column_threshold,
            "giant_threshold": self.giant_threshold,
            "output_format": self.output_format,
            "timeout_analysis": self.timeout_analysis,
            "timeout_compile": self.timeout_compile,
            "plugin_two_lines": self.plugin_two_lines,
            "hero_header": self.hero_header,
            "background": self.background,
            "ignored_plugins": self.ignored_plugins,
            "ignored_plugins_custom": self.ignored_plugins_custom,
            "category": self.category.to_plain(),
        }


@dataclass
class _PreviewImage:
    page: int
    mime: str
    width: int
    height: int
    data: bytes


@dataclass
class _CacheEntry:
    images: list[_PreviewImage]
    total_pages: int
    created_at: float
    size: int


class _PreviewCache:
    """预览图片的小型 LRU 缓存

    预览页会在同一套样式上反复微调（例如只拖动开关），重新编译一次要数秒，
    因此按「内容 + 配置 + 模板」指纹缓存已编码图片；超过 TTL/容量即淘汰。
    """

    def __init__(self) -> None:
        self._items: OrderedDict[str, _CacheEntry] = OrderedDict()

    def get(self, key: str) -> _CacheEntry | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > InternalCFG.PREVIEW_CACHE_TTL:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return entry

    def put(
        self, key: str, images: list[_PreviewImage], total_pages: int
    ) -> _CacheEntry:
        entry = _CacheEntry(
            images=images,
            total_pages=total_pages,
            created_at=time.monotonic(),
            size=sum(len(image.data) for image in images),
        )
        self._items[key] = entry
        self._items.move_to_end(key)
        while len(self._items) > InternalCFG.PREVIEW_CACHE_MAX_ENTRIES:
            self._items.popitem(last=False)
        while self._items:
            total = sum(item.size for item in self._items.values())
            if total <= InternalCFG.PREVIEW_CACHE_MAX_BYTES:
                break
            self._items.popitem(last=False)
        return entry


class PreviewService:
    """预览页的渲染服务

    只负责「样式 → 配置 → 渲染」；面板数据由 main 注入的 provider_builder 构造，
    避免 core 层反向依赖插件入口。
    """

    def __init__(
        self,
        *,
        star: Star,
        data_dir: Path,
        template_path: Path,
        font_dirs: list[Path],
        base_config: TypstPluginConfig,
        font_manager: FontManager,
        renderer: TypstRenderer,
        provider_builder: ProviderBuilder,
        persona_getter: PersonaGetter,
        plugin_lister: PluginLister,
    ) -> None:
        self.star = star
        self.data_dir = data_dir
        self.template_path = template_path
        self.font_dirs = list(font_dirs)
        self.base_config = base_config
        self.font_manager = font_manager
        self.renderer = renderer
        self.provider_builder = provider_builder
        self.persona_getter = persona_getter
        self.plugin_lister = plugin_lister
        self._cache = _PreviewCache()
        # 预览编译串行化：Typst 子进程本身不便宜，并发请求只会互相拖慢
        self._render_lock = asyncio.Lock()

    # ---- options ----

    def _conf_preset_entries(self) -> list[dict[str, Any]]:
        """按配置列表顺序读出自定义模板(含启用标记): 首条即面板上的「自定义」"""
        entries: list[dict[str, Any]] = []
        used: set[str] = {DefaultCFG.CUSTOM_PRESET_KEY}
        for index, preset in enumerate(self.base_config.appearance.preset_entries):
            if index == 0:
                name = DefaultCFG.CUSTOM_PRESET_KEY
            else:
                name = _unique_preset_name(preset.name, used)
                used.add(name)
            entries.append(
                {
                    "name": name,
                    "colors": _preset_palette_colors(preset.colors),
                    "enabled": preset.enabled,
                }
            )
        return entries

    def _resolve_active_preset(self, custom_presets: list[dict[str, Any]]) -> str:
        """把配置里的激活预设映射成面板卡片名(内置名或自定义模板名)"""
        enabled = next(
            (item["name"] for item in custom_presets if item.get("enabled")), None
        )
        if enabled is not None:
            return enabled
        active = self.base_config.appearance.active_preset or DefaultCFG.DEFAULT_PRESET
        if active in DefaultCFG.PRESETS:
            return active
        names = {item["name"] for item in custom_presets}
        # 「自定义」与旧配置里的自定义条目名都落到第一张自定义卡
        return active if active in names and active != DefaultCFG.CUSTOM_PRESET_KEY else (
            custom_presets[0]["name"]
        )

    def build_options(self) -> dict[str, Any]:
        """返回预览页初始化所需的全部选项"""
        appearance = self.base_config.appearance
        colors = dict(appearance.get_active_colors())
        fonts = sorted(
            (
                f
                for f in self.font_manager.available_families
                if f != DefaultCFG.EMOJI_FONT
            ),
            key=str.casefold,
        )

        preset_names = [DefaultCFG.DEFAULT_PRESET]
        preset_names.extend(
            name for name in DefaultCFG.PRESETS if name != DefaultCFG.DEFAULT_PRESET
        )
        presets = [
            {
                "name": name,
                "label": DefaultCFG.PRESET_LABELS.get(name, name),
                "colors": dict(DefaultCFG.PRESETS[name]),
            }
            for name in preset_names
            if name in DefaultCFG.PRESETS
        ]
        # 自定义模板交给独立列表管理: 首条固定「自定义」, 其余沿用配置里的名字;
        # 配置里没有条目时也补一张卡, 否则预设区没有任何可编辑项
        custom_presets = self._conf_preset_entries()
        if not custom_presets:
            custom_presets = [
                {"name": DefaultCFG.CUSTOM_PRESET_KEY, "colors": dict(colors)}
            ]
        active_preset = self._resolve_active_preset(custom_presets)

        backgrounds = [
            {"name": name} for name, _ in self.renderer.list_background_choices()
        ]
        active_background = self.renderer.resolve_background_image(deterministic=True)
        rendering = self.base_config.rendering
        output_format = (
            rendering.output_format
            if rendering.output_format in DefaultCFG.OUTPUT_FORMATS
            else DefaultCFG.OUTPUT_FORMAT
        )
        # 分页高度默认沿用正式配置：预览若自行改小分页尺度，会出现
        # 「预览被提前截断、正式图却完整」的错觉，也让分页位置无法对照
        split_height = int(
            _clamp_float(
                rendering.split_height,
                float(rendering.split_height),
                DefaultCFG.MIN_SPLIT_HEIGHT,
                _format_max_height(output_format),
            )
        )

        # 屏蔽项拆成「已安装插件勾选」与「自定义条目」两路：面板多选只列已安装的，
        # 未安装的旧名字放进自定义条目，保证每个值都可见、可删
        plugins = self.plugin_lister()
        installed = {str(item.get("name") or "") for item in plugins}
        ignored_selected = sorted(
            name for name in self.base_config.ignored_plugins if name in installed
        )
        ignored_custom = sorted(
            self.base_config.ignored_plugins_custom
            | {
                name
                for name in self.base_config.ignored_plugins
                if name not in installed
            }
        )
        category_options = self._build_category_options(plugins)

        return {
            "modes": [{"value": mode, "label": label} for mode, label in _MODE_LABELS],
            "presets": presets,
            "custom_presets": custom_presets,
            # 面板「自定义模板」区的文案与上限（名字长度、模板数量）
            "custom_preset": {
                "label": DefaultCFG.CUSTOM_PRESET_KEY,
                "max": InternalCFG.PREVIEW_CUSTOM_PRESET_MAX,
                "name_max": InternalCFG.PREVIEW_PRESET_NAME_MAX,
            },
            "active": {
                "mode": "command",
                "preset": active_preset,
                "colors": colors,
                "fonts": appearance.get_active_font_order(),
                "page_width": float(rendering.page_width),
                "ppi": float(rendering.ppi),
                "split_height": split_height,
                "single_column_threshold": float(rendering.single_column_threshold),
                "giant_threshold": int(rendering.giant_threshold),
                "output_format": output_format,
                "timeout_analysis": float(rendering.timeout_analysis),
                "timeout_compile": float(rendering.timeout_compile),
                "plugin_two_lines": bool(rendering.plugin_two_lines),
                "hero_header": bool(self.base_config.hero_header),
                "background": active_background.name if active_background else "",
                # 应用配置后前端靠这里比对「保存后的值」，缺了会让重载确认轮询永远不匹配
                "ignored": {
                    "selected": ignored_selected,
                    "custom": ignored_custom,
                },
                "category": category_options["active"],
            },
            "fonts": fonts,
            "backgrounds": backgrounds,
            "plugins": plugins,
            "ignored": {
                "selected": ignored_selected,
                "custom": ignored_custom,
            },
            "category": category_options,
            "color_groups": self._build_color_groups(colors),
            "limits": {
                "page_width": {
                    "min": InternalCFG.PREVIEW_MIN_PAGE_WIDTH,
                    "max": InternalCFG.PREVIEW_MAX_PAGE_WIDTH,
                    "step": 10,
                },
                "ppi": {
                    "min": InternalCFG.PREVIEW_MIN_PPI,
                    "max": InternalCFG.PREVIEW_MAX_PPI,
                    "step": 8,
                },
                "split_height": {
                    "min": DefaultCFG.MIN_SPLIT_HEIGHT,
                    "max": DefaultCFG.MAX_LIMIT_SIDE,
                    "step": 100,
                },
                "single_column_threshold": {
                    "min": DefaultCFG.MIN_PAGE_WIDTH,
                    "max": DefaultCFG.MAX_PAGE_WIDTH,
                    "step": 10,
                },
                "giant_threshold": {
                    "min": DefaultCFG.MIN_GIANT,
                    "max": DefaultCFG.MAX_GIANT,
                    "step": 100,
                },
                "timeout_analysis": {
                    "min": DefaultCFG.MIN_TIMEOUT_ANALYSIS,
                    "max": DefaultCFG.MAX_TIMEOUT,
                    "step": 1,
                },
                "timeout_compile": {
                    "min": DefaultCFG.MIN_TIMEOUT_COMPILE,
                    "max": DefaultCFG.MAX_TIMEOUT,
                    "step": 1,
                },
                "format_max_height": {
                    fmt: _format_max_height(fmt) for fmt in DefaultCFG.OUTPUT_FORMATS
                },
                "max_query_len": InternalCFG.PREVIEW_MAX_QUERY_LEN,
            },
            "preview": {
                "ppi": float(rendering.ppi),
                "test_ppi": InternalCFG.PREVIEW_TEST_PPI,
                "max_pages": InternalCFG.PREVIEW_MAX_PAGES,
                "debounce_ms": InternalCFG.PREVIEW_DEBOUNCE_MS,
            },
        }

    def _build_color_groups(self, colors: dict[str, str]) -> list[dict[str, Any]]:
        """按编辑友好度给颜色分组；未知键归入「通用颜色」尾部"""
        groups: list[dict[str, Any]] = []
        for group_id, label, defs in (
            ("brand", "品牌色", _BRAND_COLOR_DEFS),
            ("category", "分类色槽", _CATEGORY_COLOR_DEFS),
            ("general", "通用颜色", _GENERAL_COLOR_DEFS),
        ):
            items = [
                {"key": key, "label": text, "value": colors[key]}
                for key, text in defs
                if key in colors
            ]
            if group_id == "general":
                items.extend(
                    {"key": key, "label": key, "value": value}
                    for key, value in colors.items()
                    if key not in _KNOWN_COLOR_KEYS
                )
            if items:
                groups.append({"id": group_id, "label": label, "colors": items})
        return groups

    def _build_category_options(
        self, plugins: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """分类编辑器数据：当前规则、标准模板、主题色槽与高频热词"""
        category = self.base_config.category
        slots = self.base_config.appearance.get_category_slots()
        # 热词与命中数只统计真正会出现在面板里的插件，否则本插件与 AstrBot
        # 内置项的描述会把「帮助」「机器人」这类词拱到最前面
        ignored = self.base_config.effective_ignored_plugins
        visible = [
            plugin
            for plugin in plugins
            if str(plugin.get("name") or "") not in ignored
        ]
        texts = [_plugin_match_text(plugin) for plugin in visible]
        return {
            "active": category.to_plain(),
            "slots": [
                {"value": f"slot_{index}", "label": f"槽 {index}", "hex": color}
                for index, color in enumerate(slots)
            ],
            # 标准模板直接取默认分类关键词, 与首次安装时预置到面板的内容一致
            "standard": [
                {
                    "name": name,
                    "keywords": list(keywords),
                    "color": DefaultCFG.DEFAULT_CATEGORY_SLOT_BINDINGS.get(name, ""),
                }
                for name, keywords in DefaultCFG.DEFAULT_CATEGORY_KEYWORDS.items()
            ],
            "fallback_defaults": {
                "fallback": DefaultCFG.DEFAULT_CATEGORY_FALLBACK,
                "fallback_color": DefaultCFG.DEFAULT_CATEGORY_FALLBACK_COLOR,
            },
            "hot_words": _extract_hot_words(visible),
            # 前端用这些文案算「某分组命中多少个插件」, 不传插件名以外的原始元信息
            "match_texts": [
                {
                    "name": str(plugin.get("name") or ""),
                    "text": text[: InternalCFG.PREVIEW_MATCH_TEXT_LIMIT],
                }
                for plugin, text in zip(visible, texts)
            ],
            "limits": {
                "name": InternalCFG.PREVIEW_CATEGORY_NAME_MAX,
                "keyword": InternalCFG.PREVIEW_CATEGORY_KEYWORD_MAX,
                "rules": InternalCFG.PREVIEW_CATEGORY_RULES_MAX,
                "keywords": InternalCFG.PREVIEW_CATEGORY_KEYWORDS_MAX,
                "hot_words": InternalCFG.PREVIEW_HOT_WORD_LIMIT,
            },
        }

    # ---- render ----

    async def render(self, payload: Any) -> dict[str, Any]:
        """执行一次预览渲染，返回可直接 JSON 序列化的响应"""
        if not isinstance(payload, dict):
            raise PreviewError("请求内容格式不正确")

        mode = payload.get("mode")
        if mode not in InternalCFG.PREVIEW_SUPPORTED_MODES:
            raise PreviewError("不支持的面板类型")

        query_value = payload.get("query", "")
        if query_value is None:
            query = ""
        elif isinstance(query_value, str):
            query = query_value.strip()
        else:
            raise PreviewError("搜索关键词格式不正确")
        if len(query) > InternalCFG.PREVIEW_MAX_QUERY_LEN:
            raise PreviewError(
                f"搜索关键词最多 {InternalCFG.PREVIEW_MAX_QUERY_LEN} 个字符"
            )

        style = self._parse_style(payload.get("style"))
        started = time.perf_counter()
        cfg, warnings = self._compose_config(style)
        layout = TypstLayout(cfg)
        persona_name = await self.persona_getter()
        provider = self.provider_builder(
            mode,
            query or None,
            layout,
            cfg.appearance.get_active_font_order(),
            persona_name,
            cfg,
        )
        # 先把面板数据落成 JSON 并取内容 hash: 缓存必须随插件/指令变化失效，
        # 否则安装或禁用插件后预览会一直返回旧图。
        prepared_provider, content_hash, prepared_json = await self._prepare_provider(
            provider, cfg
        )
        try:
            renderer = TypstRenderer(
                star=self.star,
                data_dir=self.data_dir,
                template_path=self.template_path,
                font_dirs=self.font_dirs,
                config=cfg,
            )

            bg_image = renderer.resolve_background_image(deterministic=True)
            cache_key = self._cache_key(
                mode, query, style, renderer, bg_image, content_hash
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                return self._build_response(
                    cached,
                    cached=True,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    warnings=warnings,
                )

            async with self._render_lock:
                # 等锁期间可能有同款请求已经编译完成
                cached = self._cache.get(cache_key)
                if cached is not None:
                    return self._build_response(
                        cached,
                        cached=True,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        warnings=warnings,
                    )

                result, error = await renderer.render(
                    prepared_provider, mode, query or None, force_temp=True
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)

                if result is None:
                    raise PreviewError(self._friendly_error(error))

                try:
                    images = await asyncio.to_thread(
                        self._read_images, [Path(p) for p in result.images]
                    )
                finally:
                    # 预览图已读进内存，临时文件立即可删，避免数据目录堆积
                    await asyncio.to_thread(self._remove_files, result.temp_files)
        finally:
            await asyncio.to_thread(self._remove_files, [prepared_json])

        total_pages = len(images)
        if total_pages > InternalCFG.PREVIEW_MAX_PAGES:
            warnings.append(
                f"面板共 {total_pages} 页，预览只返回前 "
                f"{InternalCFG.PREVIEW_MAX_PAGES} 页"
            )
            images = images[: InternalCFG.PREVIEW_MAX_PAGES]

        entry = self._cache.put(cache_key, images, total_pages)
        return self._build_response(
            entry, cached=False, elapsed_ms=elapsed_ms, warnings=warnings
        )

    # ---- data preparation ----

    async def _prepare_provider(
        self, provider: DataProvider, cfg: TypstPluginConfig
    ) -> tuple[DataProvider, str, Path]:
        """先执行一次数据分析：得到内容 hash，同时避免 render 里重复分析。

        返回一个只复制 JSON 的包装 provider，让 Typst 编译仍然走原有渲染路径。
        """
        json_path = self.data_dir / f"temp_preview_{uuid.uuid4().hex}.json"
        # 下限由配置读取/预览样式统一夹紧, 这里不再另设 1s 兜底
        timeout = float(cfg.rendering.timeout_analysis)
        try:
            count = await asyncio.wait_for(
                asyncio.to_thread(provider, json_path), timeout=timeout
            )
        except asyncio.TimeoutError:
            await asyncio.to_thread(self._remove_files, [json_path])
            raise PreviewError("面板数据分析超时，请稍后重试") from None
        except PreviewError:
            await asyncio.to_thread(self._remove_files, [json_path])
            raise
        except Exception as exc:
            await asyncio.to_thread(self._remove_files, [json_path])
            logger.error(f"[HelpTypst] 预览数据分析失败: {exc}", exc_info=True)
            raise PreviewError("预览数据分析失败，请查看插件日志") from exc

        if count <= 0:
            await asyncio.to_thread(self._remove_files, [json_path])
            raise PreviewError(self._friendly_error("empty"))

        try:
            content = await asyncio.to_thread(json_path.read_text, encoding="utf-8")
        except OSError as exc:
            await asyncio.to_thread(self._remove_files, [json_path])
            logger.error(f"[HelpTypst] 读取预览数据失败: {exc}", exc_info=True)
            raise PreviewError("预览数据读取失败，请查看插件日志") from exc

        content_hash = await asyncio.to_thread(calculate_hash, content)

        def prepared(save_path: Path) -> int:
            save_path.write_text(content, encoding="utf-8")
            return count

        return prepared, content_hash, json_path

    # ---- style -> config ----

    def _parse_category(self, raw_category: Any) -> PreviewCategory:
        """分类规则收敛：键缺失沿用当前配置，传入值按配置面板的规则清洗"""
        base = self.base_config.category

        def base_rules() -> list[PreviewCategoryRule]:
            return [
                PreviewCategoryRule(
                    name=rule.name,
                    keywords=list(rule.keywords),
                    enabled=rule.enabled,
                    color=rule.color,
                )
                for rule in base.rules
            ]

        if not isinstance(raw_category, dict):
            return PreviewCategory(
                fallback=base.fallback,
                fallback_color=base.fallback_color,
                rules=base_rules(),
            )

        raw_fallback = raw_category.get("fallback")
        fallback = (
            raw_fallback.strip()[: InternalCFG.PREVIEW_CATEGORY_NAME_MAX]
            if isinstance(raw_fallback, str)
            else ""
        )
        if not fallback:
            fallback = DefaultCFG.DEFAULT_CATEGORY_FALLBACK

        raw_fallback_color = raw_category.get("fallback_color")
        fallback_color = (
            _normalize_slot_or_color(raw_fallback_color)
            if isinstance(raw_fallback_color, str)
            else DefaultCFG.DEFAULT_CATEGORY_FALLBACK_COLOR
        )
        # 与 config.load 一致：留空等价于默认色槽
        if not fallback_color:
            fallback_color = DefaultCFG.DEFAULT_CATEGORY_FALLBACK_COLOR

        raw_rules = raw_category.get("rules")
        if not isinstance(raw_rules, list):
            rules = base_rules()
        else:
            rules = []
            for item in raw_rules:
                if not isinstance(item, dict):
                    continue
                raw_name = item.get("name")
                name = (
                    raw_name.strip()[: InternalCFG.PREVIEW_CATEGORY_NAME_MAX]
                    if isinstance(raw_name, str)
                    else ""
                )
                if not name:
                    continue
                rules.append(
                    PreviewCategoryRule(
                        name=name,
                        keywords=_normalize_keywords(item.get("keywords")),
                        # 与 config.load 一致：只有显式 false 才关闭
                        enabled=_as_bool(item.get("enabled"), True),
                        color=_normalize_slot_or_color(item.get("color")),
                    )
                )
                if len(rules) >= InternalCFG.PREVIEW_CATEGORY_RULES_MAX:
                    break

        return PreviewCategory(
            fallback=fallback,
            fallback_color=fallback_color,
            rules=rules,
        )

    def _normalize_custom_presets(self, raw: Any) -> list[dict[str, Any]]:
        """收敛面板自定义模板: 保留顺序, 首条固定「自定义」, 其余名字去重限长

        不按面板的新增上限 (PREVIEW_CUSTOM_PRESET_MAX) 截断: 用户可能在设置面板
        直接写入更多条目, 按面板上限截断会在「应用」时静默丢掉第 9 条起。
        """
        entries: list[dict[str, Any]] = []
        if not isinstance(raw, list):
            return entries
        used: set[str] = {DefaultCFG.CUSTOM_PRESET_KEY}
        for index, item in enumerate(raw[: InternalCFG.PREVIEW_CUSTOM_PRESET_HARD_MAX]):
            if not isinstance(item, dict):
                continue
            if index == 0:
                name = DefaultCFG.CUSTOM_PRESET_KEY
            else:
                name = _unique_preset_name(item.get("name"), used)
                used.add(name)
            entries.append(
                {"name": name, "colors": _preset_palette_colors(item.get("colors"))}
            )
        return entries

    def _parse_style(self, raw_style: Any) -> PreviewStyle:
        """把前端传来的样式收敛成合法值；非法颜色/字体静默忽略"""
        base_colors = dict(self.base_config.appearance.get_active_colors())
        rendering = self.base_config.rendering
        appearance = self.base_config.appearance

        style = raw_style if isinstance(raw_style, dict) else {}
        colors = dict(base_colors)
        raw_colors = style.get("colors")
        if isinstance(raw_colors, dict):
            for key, value in raw_colors.items():
                if key not in base_colors:
                    continue
                normalized = _normalize_color(value)
                if normalized is not None:
                    colors[key] = normalized

        fonts: list[str] = []
        raw_fonts = style.get("fonts")
        if isinstance(raw_fonts, list):
            for family in raw_fonts:
                if not isinstance(family, str):
                    continue
                name = family.strip()
                if (
                    name
                    and name != DefaultCFG.EMOJI_FONT
                    and name in self.font_manager.available_families
                    and name not in fonts
                ):
                    fonts.append(name)

        raw_background = style.get("background", "")
        background = (
            raw_background.strip()[:255] if isinstance(raw_background, str) else ""
        )

        raw_format = style.get("output_format")
        output_format = (
            raw_format.strip()
            if isinstance(raw_format, str)
            and raw_format.strip() in DefaultCFG.OUTPUT_FORMATS
            else rendering.output_format
        )
        if output_format not in DefaultCFG.OUTPUT_FORMATS:
            output_format = DefaultCFG.OUTPUT_FORMAT

        # 屏蔽集：键缺失表示前端没带这项(沿用配置)，带了就按传入值(可能是空列表=全部取消)
        ignored_plugins = (
            _normalize_names(style.get("ignored_plugins"))
            if "ignored_plugins" in style
            else sorted(self.base_config.ignored_plugins)
        )
        ignored_custom = (
            _normalize_names(style.get("ignored_plugins_custom"))
            if "ignored_plugins_custom" in style
            else sorted(self.base_config.ignored_plugins_custom)
        )

        return PreviewStyle(
            preset=str(style.get("preset") or appearance.active_preset or ""),
            colors=colors,
            fonts=fonts,
            page_width=_clamp_float(
                style.get("page_width"),
                float(rendering.page_width),
                InternalCFG.PREVIEW_MIN_PAGE_WIDTH,
                InternalCFG.PREVIEW_MAX_PAGE_WIDTH,
            ),
            ppi=_clamp_float(
                style.get("ppi"),
                float(rendering.ppi),
                InternalCFG.PREVIEW_MIN_PPI,
                InternalCFG.PREVIEW_MAX_PPI,
            ),
            # 测试精度只作用于本次预览渲染，正式配置里的清晰度由 ppi 字段承载
            test_ppi=_clamp_float(
                style.get("test_ppi"),
                InternalCFG.PREVIEW_TEST_PPI,
                InternalCFG.PREVIEW_MIN_PPI,
                InternalCFG.PREVIEW_MAX_PPI,
            ),
            split_height=int(
                round(
                    _clamp_float(
                        style.get("split_height"),
                        float(rendering.split_height),
                        DefaultCFG.MIN_SPLIT_HEIGHT,
                        float(_format_max_height(output_format)),
                    )
                )
            ),
            single_column_threshold=_clamp_float(
                style.get("single_column_threshold"),
                float(rendering.single_column_threshold),
                DefaultCFG.MIN_PAGE_WIDTH,
                DefaultCFG.MAX_PAGE_WIDTH,
            ),
            giant_threshold=int(
                round(
                    _clamp_float(
                        style.get("giant_threshold"),
                        float(rendering.giant_threshold),
                        DefaultCFG.MIN_GIANT,
                        DefaultCFG.MAX_GIANT,
                    )
                )
            ),
            output_format=output_format,
            timeout_analysis=_clamp_float(
                style.get("timeout_analysis"),
                float(rendering.timeout_analysis),
                DefaultCFG.MIN_TIMEOUT_ANALYSIS,
                DefaultCFG.MAX_TIMEOUT,
            ),
            timeout_compile=_clamp_float(
                style.get("timeout_compile"),
                float(rendering.timeout_compile),
                DefaultCFG.MIN_TIMEOUT_COMPILE,
                DefaultCFG.MAX_TIMEOUT,
            ),
            plugin_two_lines=_as_bool(
                style.get("plugin_two_lines"), bool(rendering.plugin_two_lines)
            ),
            hero_header=_as_bool(
                style.get("hero_header"), bool(self.base_config.hero_header)
            ),
            background=background,
            ignored_plugins=ignored_plugins,
            ignored_plugins_custom=ignored_custom,
            category=self._parse_category(style.get("category")),
            custom_presets=self._normalize_custom_presets(style.get("custom_presets")),
        )

    def _compose_config(
        self, style: PreviewStyle
    ) -> tuple[TypstPluginConfig, list[str]]:
        """基于当前配置深拷贝一份预览专用配置"""
        cfg = copy.deepcopy(self.base_config)
        warnings: list[str] = []

        rendering = cfg.rendering
        format_max = _format_max_height(style.output_format)
        # 输出格式跟用户选择走：PNG/JPEG 能承载更高分页，WebP 体积最小
        rendering.output_format = style.output_format
        rendering.webp_limit = format_max
        rendering.ppi = style.test_ppi
        rendering.page_width = style.page_width
        rendering.single_column_threshold = style.single_column_threshold
        rendering.giant_threshold = style.giant_threshold
        rendering.plugin_two_lines = style.plugin_two_lines
        # 分页高度与正式配置保持一致：模板按该上限分页，预览才能反映真实分页位置
        rendering.split_height = min(style.split_height, format_max)
        rendering.timeout_analysis = style.timeout_analysis
        rendering.timeout_compile = style.timeout_compile
        rendering.max_concurrent_tasks = 1

        cfg.hero_header = style.hero_header
        cfg.background_random = False
        # 预览要反映面板里勾选的屏蔽集, 否则勾掉插件后预览图看不到变化
        cfg.ignored_plugins = set(style.ignored_plugins)
        cfg.ignored_plugins_custom = set(style.ignored_plugins_custom)

        # 分类规则决定 /helps 的分组归属与卡片标题，预览必须同步，否则改了规则图不变
        cfg.category = CategoryConfig(
            rules=[
                CategoryRule(
                    name=rule.name,
                    keywords=list(rule.keywords),
                    enabled=rule.enabled,
                    color=rule.color,
                )
                for rule in style.category.rules
            ],
            fallback=style.category.fallback,
            fallback_color=style.category.fallback_color,
        )

        if style.background:
            choices = dict(self.renderer.list_background_choices())
            path = choices.get(style.background)
            if path is None:
                warnings.append(f"背景图「{style.background}」不存在，已回落当前配置")
            else:
                cfg.header_background = str(path)
                cfg.background_dir = ""
        elif not style.hero_header:
            # 关闭 Hero 时模板不会使用背景图，无需保留无关的配置解析
            cfg.header_background = ""
            cfg.background_dir = ""

        # 用「启用中的预设」强制覆盖配色：get_active_colors 只接受预设里已存在的
        # 基础键，因此把当前生效色板与用户改动合并后整体注入
        appearance = cfg.appearance
        appearance.presets = {
            "__preview__": ThemePreset(
                name="__preview__",
                colors=dict(style.colors),
                enabled=True,
            )
        }
        appearance.active_preset = "__preview__"
        appearance.font_order = (
            list(style.fonts)
            if style.fonts
            else list(self.base_config.appearance.get_active_font_order())
        )
        # 配色缓存是按预设计算的，换预设后必须手动失效
        appearance._color_cache = None

        return cfg, warnings

    # ---- style -> plugin config ----

    def build_apply_plan(self, payload: Any) -> dict[str, Any]:
        """把面板样式整理成写入插件配置的补丁计划（只计算，不落盘）。

        配色改动落到「自定义模板」：面板把内置预设改出差别后会切到自定义卡，
        保存时写回预设列表（首条固定名「自定义」）；背景图仅在面板选了与当前
        生效背景不同的图片时才固定，未改动时保留配置里的随机背景。
        """
        style = self._parse_style(payload.get("style"))
        base = self.base_config
        appearance = base.appearance
        rendering = base.rendering
        warnings: list[str] = []
        changed: list[str] = []

        format_max = _format_max_height(style.output_format)
        split_height = min(int(style.split_height), format_max)
        new_rendering = {
            "page_width": style.page_width,
            "ppi": float(style.ppi),
            "split_height": split_height,
            "single_column_threshold": style.single_column_threshold,
            "giant_threshold": int(round(style.giant_threshold)),
            "output_format": style.output_format,
            "timeout_analysis": style.timeout_analysis,
            "timeout_compile": style.timeout_compile,
            "plugin_two_lines": style.plugin_two_lines,
        }
        for key, label in (
            ("page_width", "页面宽度"),
            ("ppi", "图片清晰度"),
            ("split_height", "分页高度"),
            ("single_column_threshold", "单列切换阈值"),
            ("giant_threshold", "独占行高度"),
            ("output_format", "输出格式"),
            ("timeout_analysis", "数据生成超时"),
            ("timeout_compile", "编译超时"),
            ("plugin_two_lines", "插件双行"),
        ):
            if new_rendering[key] != getattr(rendering, key):
                changed.append(label)

        # 配色：能对上内置预设色板就切预设名，否则把改动收进自定义模板列表，
        # 避免把内置预设「改脏」；具体条目与启用项由 _plan_preset_entries 统一决定
        preset_plan = self._plan_preset_entries(style)
        changed.extend(preset_plan["changed"])

        active_fonts = list(appearance.get_active_font_order())
        parsed_fonts = list(style.fonts)
        if not parsed_fonts or parsed_fonts == active_fonts:
            fonts = active_fonts
        elif parsed_fonts == [
            family
            for family in active_fonts
            if family in self.font_manager.available_families
        ]:
            # 只是过滤掉了当前不可用的字体（如字体目录暂时不可用），保留原顺序
            fonts = active_fonts
        else:
            fonts = parsed_fonts
            changed.append("字体顺序")

        if style.hero_header != bool(base.hero_header):
            changed.append("Hero 横幅")

        background_path: str | None = None
        current_bg = self.renderer.resolve_background_image(deterministic=True)
        current_bg_name = current_bg.name if current_bg is not None else ""
        if style.background and style.background != current_bg_name:
            choices = dict(self.renderer.list_background_choices())
            picked = choices.get(style.background)
            if picked is None:
                warnings.append(
                    f"背景图「{style.background}」不存在，已保留原背景设置"
                )
            else:
                background_path = str(picked)
                changed.append("背景图")

        # 屏蔽集：面板把「已安装插件」与「自定义条目」分开存，两个键各自整体替换。
        # 旧配置里未安装的名字会被前端归入自定义条目，应用时顺带完成迁移。
        ignored_selected = sorted(set(style.ignored_plugins))
        ignored_custom = sorted(set(style.ignored_plugins_custom))
        if (
            set(ignored_selected) != base.ignored_plugins
            or set(ignored_custom) != base.ignored_plugins_custom
        ):
            changed.append("屏蔽插件")

        # 分类规则：结构与配置面板的 category 对齐后整体比较；配置侧会丢弃
        # 「无关键词」与「同名」条目，这里先跳过并提示，避免保存后规则凭空消失
        category_patch: dict[str, Any] | None = None
        if _category_signature(base.category.to_plain()) != _category_signature(
            style.category.to_plain()
        ):
            changed.append("分类规则")
            rules_patch: list[dict[str, Any]] = []
            seen_names: set[str] = set()
            for rule in style.category.rules:
                keywords = [keyword for keyword in rule.keywords if keyword]
                if not keywords:
                    warnings.append(f"分类「{rule.name}」没有关键词，已跳过")
                    continue
                if rule.name in seen_names:
                    warnings.append(f"分类「{rule.name}」名称重复，已保留第一条")
                    continue
                seen_names.add(rule.name)
                rules_patch.append(
                    {
                        # 设置面板的 template_list 靠模板键渲染条目，缺了会被配置校验拒绝
                        "__template_key": "standard_category",
                        "category_name": rule.name,
                        "enabled": bool(rule.enabled),
                        "keywords": keywords,
                        "color": rule.color,
                    }
                )
            if not rules_patch:
                warnings.append("分组规则全部无效，应用后所有插件都会归入兜底分类")
            category_patch = {
                "fallback": style.category.fallback,
                "fallback_color": style.category.fallback_color,
                "rules": rules_patch,
            }

        appearance_patch: dict[str, Any] = {
            "active_preset": preset_plan["active_preset"],
            "font_order": fonts,
        }

        return {
            "rendering": new_rendering,
            "appearance": appearance_patch,
            "preset_entries": preset_plan["preset_entries"],
            "enabled_preset": preset_plan["enabled_preset"],
            "hero_header": bool(style.hero_header),
            "background_path": background_path,
            "ignored_plugins": ignored_selected,
            "ignored_plugins_custom": ignored_custom,
            "category": category_patch,
            "changed": changed,
            "warnings": warnings,
        }

    def _plan_preset_entries(self, style: PreviewStyle) -> dict[str, Any]:
        """决定这次应用要写回的预设列表、启用项与激活预设名

        面板带 custom_presets 时以它为准（可增删改名）；旧页面不带时只在现有
        条目上改颜色。内置预设永远不直接写入，配色改动一律落到自定义条目。
        """
        appearance = self.base_config.appearance
        base_colors = _color_map(appearance.get_active_colors())
        style_colors = _color_map(style.colors)
        current_entries = self._conf_preset_entries()
        current_enabled = next(
            (item["name"] for item in current_entries if item.get("enabled")), None
        )

        if style.custom_presets:
            entries = [
                {"name": item["name"], "colors": dict(item["colors"])}
                for item in style.custom_presets
            ]
        else:
            # 旧页面不带条目列表: 只能在现有条目上改色, 名字与数量保持不变
            entries = [
                {"name": item["name"], "colors": dict(item["colors"])}
                for item in current_entries
            ]
            if not entries:
                entries = [
                    {
                        "name": DefaultCFG.CUSTOM_PRESET_KEY,
                        "colors": dict(DefaultCFG.DEFAULT_COLORS),
                    }
                ]

        names = [item["name"] for item in entries]
        active_name = style.preset if style.preset in names else None
        if active_name is None and style.preset == DefaultCFG.CUSTOM_PRESET_KEY:
            # 旧页面把「自定义」当预设名传, 对应面板第一张自定义卡
            active_name = names[0]

        enabled_preset: str | None
        if style.preset in DefaultCFG.PRESETS and style_colors == _color_map(
            DefaultCFG.PRESETS[style.preset]
        ):
            active_preset = style.preset
            enabled_preset = None
        elif active_name is not None:
            entries[names.index(active_name)]["colors"] = dict(style.colors)
            enabled_preset = active_name
            active_preset = DefaultCFG.CUSTOM_PRESET_KEY
        elif style_colors != base_colors:
            # 旧页面只带改过的颜色: 按既定约定写进第一条自定义模板
            entries[0]["colors"] = dict(style.colors)
            enabled_preset = names[0]
            active_preset = DefaultCFG.CUSTOM_PRESET_KEY
        else:
            # 没选卡片也没改色: 保持配置里的激活项
            active_preset = appearance.active_preset or DefaultCFG.DEFAULT_PRESET
            enabled_preset = None

        structure_changed = names != [item["name"] for item in current_entries]
        colors_changed = len(entries) != len(current_entries) or any(
            _color_map(entry["colors"]) != _color_map(base_entry["colors"])
            for entry, base_entry in zip(entries, current_entries)
        )

        labels: list[str] = []
        if style.preset in DefaultCFG.PRESETS and active_preset == style.preset:
            if (
                style.preset != (appearance.active_preset or DefaultCFG.DEFAULT_PRESET)
                or current_enabled is not None
            ):
                labels.append(
                    f"主题预设（{DefaultCFG.PRESET_LABELS.get(style.preset, style.preset)}）"
                )
        elif style.custom_presets:
            if structure_changed:
                labels.append("自定义模板")
            elif colors_changed or enabled_preset != current_enabled:
                labels.append("自定义配色")
        elif style_colors != base_colors or (
            enabled_preset is not None and enabled_preset != current_enabled
        ):
            labels.append("自定义配色")

        return {
            "preset_entries": entries,
            "enabled_preset": enabled_preset,
            "active_preset": active_preset,
            "changed": labels,
        }

    # ---- cache ----

    def _cache_key(
        self,
        mode: str,
        query: str,
        style: PreviewStyle,
        renderer: TypstRenderer,
        bg_image: Path | None,
        content_hash: str,
    ) -> str:
        """缓存键 = 面板内容 + 样式 + 配置/资源快照"""
        snapshot = renderer.get_config_snapshot(bg_image)
        payload = {
            "mode": mode,
            "query": query,
            "style": style.to_plain(),
            "content": content_hash,
            "snapshot": snapshot,
        }
        encoded = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    # ---- io helpers ----

    def _read_images(self, paths: list[Path]) -> list[_PreviewImage]:
        """读取编译产物，并用 PIL 补齐宽高（Pillow 由 AstrBot 运行环境提供）"""
        images: list[_PreviewImage] = []
        for index, path in enumerate(paths):
            data = path.read_bytes()
            width, height = self._image_size(data, path)
            images.append(
                _PreviewImage(
                    page=index + 1,
                    mime=self._mime_for(path),
                    width=width,
                    height=height,
                    data=data,
                )
            )
        return images

    def _image_size(self, data: bytes, path: Path) -> tuple[int, int]:
        try:
            from PIL import Image
        except ImportError:
            # 运行环境缺 Pillow 时预览仍可用，只是前端拿不到像素尺寸
            return 0, 0
        try:
            with Image.open(io.BytesIO(data)) as image:
                return int(image.width), int(image.height)
        except OSError as exc:
            logger.warning(f"[HelpTypst] 读取预览图尺寸失败 {path}: {exc}")
            return 0, 0

    def _mime_for(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix in (".jpg", ".jpeg"):
            return "image/jpeg"
        return "image/webp"

    def _remove_files(self, files: list[Path]) -> None:
        for path in files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"[HelpTypst] 清理预览临时文件失败 {path}: {exc}")

    def _build_response(
        self,
        entry: _CacheEntry,
        *,
        cached: bool,
        elapsed_ms: int,
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "images": [
                {
                    "page": image.page,
                    "mime": image.mime,
                    "width": image.width,
                    "height": image.height,
                    "data": base64.b64encode(image.data).decode("ascii"),
                }
                for image in entry.images
            ],
            "elapsed_ms": elapsed_ms,
            "cached": cached,
            "total_pages": entry.total_pages,
            "truncated": entry.total_pages > len(entry.images),
            "warnings": list(warnings),
        }

    def _friendly_error(self, error: str) -> str:
        if not error or error == "empty":
            return "当前面板没有可展示的内容（可能还没有加载任何插件）"
        if "超时" in error:
            return "预览渲染超时，请降低精度或减少搜索范围后重试"
        return error

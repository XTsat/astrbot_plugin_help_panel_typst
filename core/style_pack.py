"""样式包的导出 / 导入（一个 JSON = 主题 + 分类规则 + 版式）

样式包只承载「用户调出来的外观」，不碰插件身份与运行期数据：
- 主题：激活预设名 + 自定义模板列表（配色落点）
- 分类规则：兜底分类与规则列表
- 版式：页宽、清晰度、分页高度、单列阈值、插件双行、Hero、字体顺序等

导入走与「应用配置」相同的收敛链路（`PreviewService._parse_style` 与
`build_apply_plan`），因此非法颜色、越界数值、失效字体、不存在的背景图都按
同一套规则被丢弃或回落，不会因为手改 JSON 写出坏配置。
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..domain import DefaultCFG, InternalCFG
from .preview import (
    PreviewService,
    PreviewStyle,
    _as_bool,
    _normalize_keywords,
    _normalize_slot_or_color,
    _preset_palette_colors,
)

# 样式包版本：与 InternalCFG.STYLE_EXPORT_SCHEMA_VERSION 同步，导入时按此判断兼容性
_SCHEMA_VERSION = InternalCFG.STYLE_EXPORT_SCHEMA_VERSION
_KIND = InternalCFG.STYLE_EXPORT_KIND
# 样式段名 → 中文名，报错时直接说人话
_SECTION_LABELS: dict[str, str] = {
    "theme": "主题",
    "category": "分类规则",
    "layout": "版式",
}

_HEX_SHORT_RE = re.compile(r"^#([0-9a-fA-F]{3})$")
_HEX_LONG_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


class StylePackError(Exception):
    """可直接展示给用户的样式包错误"""


@dataclass
class StylePack:
    """解析后的样式包内容

    `style` 交给 PreviewService 的同一套收敛逻辑；`name`/`note` 只是文件元信息，
    不参与渲染，导入后也不写进插件配置。
    """

    style: PreviewStyle
    name: str = ""
    note: str = ""
    exported_at: str = ""
    source_version: str = ""
    warnings: list[str] = field(default_factory=list)


def _now_iso() -> str:
    """导出时间戳：带时区的本地时间，跨时区分享时也能看懂"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _coerce_text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _normalize_hex(value: Any) -> str | None:
    """颜色统一成小写 6 位 hex：`#abc` 与 `#AABBCC` 都归一，非法值返回 None

    Typst 只认 6 位写法，样式包里允许的短写必须在这里补齐，否则导进来的颜色
    会让整页编译失败。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    short = _HEX_SHORT_RE.match(text)
    if short:
        chars = short.group(1).lower()
        return f"#{chars[0]}{chars[0]}{chars[1]}{chars[1]}{chars[2]}{chars[2]}"
    long = _HEX_LONG_RE.match(text)
    return f"#{long.group(1).lower()}" if long else None


# ---- 导出 ----


def _export_colors(colors: dict[str, str]) -> dict[str, str]:
    """导出前把颜色统一成小写 6 位：同一套样式每次导出的文件必须逐字节相同，
    否则用户 diff 两份包会看到一堆只有大小写差异的行"""
    return {
        key: (normalized or value)
        for key, value in colors.items()
        if (normalized := _normalize_hex(value)) is not None or value
    }


def _style_sections(style: PreviewStyle) -> dict[str, Any]:
    """把样式拆成「主题 / 分类规则 / 版式」三段，与导出文件结构一致"""
    return {
        "theme": {
            "preset": style.preset,
            "colors": _export_colors(style.colors),
            "presets": [
                {"name": item["name"], "colors": _export_colors(item["colors"])}
                for item in style.custom_presets
            ],
        },
        "category": {
            "fallback": style.category.fallback,
            "fallback_color": style.category.fallback_color,
            "rules": [
                {
                    "name": rule.name,
                    "keywords": list(rule.keywords),
                    "enabled": rule.enabled,
                    "color": rule.color,
                }
                for rule in style.category.rules
            ],
        },
        "layout": {
            "page_width": style.page_width,
            "ppi": style.ppi,
            "split_height": style.split_height,
            "single_column_threshold": style.single_column_threshold,
            "giant_threshold": style.giant_threshold,
            "output_format": style.output_format,
            "timeout_analysis": style.timeout_analysis,
            "timeout_compile": style.timeout_compile,
            "plugin_two_lines": style.plugin_two_lines,
            "hero_header": style.hero_header,
            "background": style.background,
            "fonts": list(style.fonts),
        },
    }


def build_style_pack(
    service: PreviewService,
    payload: Any,
    *,
    name: str = "",
    note: str = "",
    source_version: str = "",
) -> dict[str, Any]:
    """把面板当前样式导出成样式包 dict（不落盘）

    导出的是「点下导出时面板里那套样式」，而不是服务端配置，因此用户可以在
    应用之前先备份/分享调好的效果。
    """
    style = service.parse_style_for_export(payload.get("style"))
    pack: dict[str, Any] = {
        "kind": _KIND,
        "schema_version": _SCHEMA_VERSION,
        "exported_at": _now_iso(),
    }
    # 名字与备注只有用户填了才写: 空串留在文件里只会让 JSON 多两行噪音
    pack_name = _coerce_text(name, InternalCFG.STYLE_EXPORT_NAME_MAX)
    if pack_name:
        pack["name"] = pack_name
    pack_note = _coerce_text(note, 500)
    if pack_note:
        pack["note"] = pack_note
    version = _coerce_text(source_version, 32)
    if version:
        pack["source_version"] = version
    pack.update(_style_sections(style))
    return pack


def dump_style_pack(pack: dict[str, Any]) -> str:
    """序列化成 UTF-8 JSON 文本：缩进 + 不转义中文，方便用户直接看和改"""
    return json.dumps(pack, ensure_ascii=False, indent=2) + "\n"


# ---- 导入 ----


def _read_section(pack: dict[str, Any], key: str) -> dict[str, Any] | None:
    """取出一段；整段缺失返回 None（表示「这一块沿用当前配置」）"""
    section = pack.get(key)
    if section is None:
        return None
    if not isinstance(section, dict):
        raise StylePackError(f"样式包的「{_SECTION_LABELS[key]}」部分格式不正确")
    return section


def _parse_pack_presets(raw: Any) -> list[dict[str, Any]]:
    """解析自定义模板列表：只保留名字与配色，名字缺失时按序补位"""
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(raw[: InternalCFG.STYLE_EXPORT_MAX_PRESETS]):
        if not isinstance(item, dict):
            continue
        if index == 0:
            name = DefaultCFG.CUSTOM_PRESET_KEY
        else:
            name = _coerce_text(item.get("name"), InternalCFG.PREVIEW_PRESET_NAME_MAX)
            if not name:
                name = f"{DefaultCFG.CUSTOM_PRESET_KEY} {index + 1}"
        # 重名条目会让配色列表无法定位，按顺序补后缀而不是静默丢数据
        base = name
        counter = 2
        while name in used:
            suffix = f" {counter}"
            name = (
                f"{base[: InternalCFG.PREVIEW_PRESET_NAME_MAX - len(suffix)]}{suffix}"
            )
            counter += 1
        used.add(name)
        entries.append(
            {"name": name, "colors": _preset_palette_colors(item.get("colors"))}
        )
    return entries


def _parse_pack_theme(
    raw: dict[str, Any] | None, warnings: list[str]
) -> dict[str, Any]:
    """解析主题段：预设名 + 配色 + 自定义模板列表"""
    if raw is None:
        return {}
    theme: dict[str, Any] = {}

    preset = raw.get("preset")
    if isinstance(preset, str) and preset.strip():
        theme["preset"] = preset.strip()

    raw_colors = raw.get("colors")
    colors: dict[str, str] = {}
    if isinstance(raw_colors, dict):
        colors = {
            key: normalized
            for key, value in raw_colors.items()
            if (normalized := _normalize_hex(value)) is not None
        }
        dropped = len(raw_colors) - len(colors)
        if dropped > 0:
            warnings.append(f"{dropped} 个颜色值格式不正确，已忽略")
    if not colors and theme.get("preset") in DefaultCFG.PRESETS:
        # 手写/精简的样式包常只写预设名: 补齐该预设自己的色板,
        # 否则收敛会拿「当前生效色」当底色, 导入后看起来像没换主题
        colors = dict(DefaultCFG.PRESETS[theme["preset"]])
    if colors:
        theme["colors"] = colors

    presets = _parse_pack_presets(raw.get("presets"))
    if presets:
        theme["custom_presets"] = presets
    return theme


def _parse_pack_category(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """解析分类规则；整段缺失时返回 None（沿用当前配置）"""
    if raw is None:
        return None
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        name = _coerce_text(item.get("name"), InternalCFG.PREVIEW_CATEGORY_NAME_MAX)
        if not name or name in seen:
            continue
        seen.add(name)
        rules.append(
            {
                "name": name,
                "keywords": _normalize_keywords(item.get("keywords")),
                "enabled": _as_bool(item.get("enabled"), True),
                "color": _normalize_slot_or_color(item.get("color")),
            }
        )
        if len(rules) >= InternalCFG.PREVIEW_CATEGORY_RULES_MAX:
            break

    fallback = _coerce_text(raw.get("fallback"), InternalCFG.PREVIEW_CATEGORY_NAME_MAX)
    fallback_color = _normalize_slot_or_color(raw.get("fallback_color"))
    return {
        "fallback": fallback or DefaultCFG.DEFAULT_CATEGORY_FALLBACK,
        "fallback_color": fallback_color or DefaultCFG.DEFAULT_CATEGORY_FALLBACK_COLOR,
        "rules": rules,
    }


def _parse_pack_layout(raw: dict[str, Any] | None) -> dict[str, Any]:
    """解析版式段：只透传已知键，数值交给 PreviewService 夹紧"""
    if raw is None:
        return {}
    keys = (
        "page_width",
        "ppi",
        "split_height",
        "single_column_threshold",
        "giant_threshold",
        "output_format",
        "timeout_analysis",
        "timeout_compile",
        "plugin_two_lines",
        "hero_header",
        "background",
        "fonts",
    )
    return {key: raw[key] for key in keys if key in raw}


def _drop_missing_background(
    service: PreviewService, raw_style: dict[str, Any], warnings: list[str]
) -> None:
    """导入时剔除本机不存在的背景图

    背景图按文件名引用，样式包换一台机器后大概率对不上；沿用渲染侧「回落当前
    配置」的语义，但这里提前提示，免得用户以为导入后背景没生效是插件坏了。
    """
    name = raw_style.get("background")
    if not isinstance(name, str) or not name.strip():
        return
    choices = dict(service.renderer.list_background_choices())
    if name.strip() in choices:
        raw_style["background"] = name.strip()
        return
    warnings.append(f"背景图「{name.strip()}」在本机不存在，已沿用当前背景")
    raw_style["background"] = ""


def parse_style_pack(
    service: PreviewService, text: str, *, source_version: str = ""
) -> StylePack:
    """把样式包 JSON 文本解析成可交给应用链路收敛的样式

    宽松优先：缺段、缺键、未知键都按「沿用当前配置」处理，只有整体结构不对
    （不是对象、版本不支持、三段全缺）才拒绝，避免一点小改动就整包不可用。
    """
    if not isinstance(text, str) or not text.strip():
        raise StylePackError("样式包内容为空")
    if len(text.encode("utf-8")) > InternalCFG.STYLE_EXPORT_MAX_BYTES:
        raise StylePackError(
            f"样式包超过 {InternalCFG.STYLE_EXPORT_MAX_BYTES // 1024} KiB，请确认选对了文件"
        )

    try:
        pack = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StylePackError(f"不是合法的 JSON 文件（第 {exc.lineno} 行）") from exc
    if not isinstance(pack, dict):
        raise StylePackError("样式包最外层必须是一个 JSON 对象")

    kind = pack.get("kind")
    if kind is not None and kind != _KIND:
        raise StylePackError("这不是本插件的样式包")

    version = pack.get("schema_version")
    if version is not None:
        try:
            version_int = int(version)
        except (TypeError, ValueError):
            raise StylePackError("样式包的版本号格式不正确") from None
        if version_int > _SCHEMA_VERSION:
            raise StylePackError(
                f"样式包版本 v{version_int} 高于当前插件支持的 v{_SCHEMA_VERSION}，请升级插件"
            )

    warnings: list[str] = []
    theme = _parse_pack_theme(_read_section(pack, "theme"), warnings)
    category = _parse_pack_category(_read_section(pack, "category"))
    layout = _parse_pack_layout(_read_section(pack, "layout"))

    if not theme and category is None and not layout:
        raise StylePackError("样式包里没有任何可导入的主题、分类规则或版式")

    raw_style: dict[str, Any] = {**layout, **theme}
    if category is not None:
        raw_style["category"] = category
    _drop_missing_background(service, raw_style, warnings)

    style = service.parse_style_for_export(raw_style)
    return StylePack(
        style=style,
        name=_coerce_text(pack.get("name"), InternalCFG.STYLE_EXPORT_NAME_MAX),
        note=_coerce_text(pack.get("note"), 500),
        exported_at=_coerce_text(pack.get("exported_at"), 64),
        source_version=_coerce_text(pack.get("source_version"), 32) or source_version,
        warnings=warnings,
    )


# ---- 收敛后的样式 → 前端可用形状 ----


def style_payload(style: PreviewStyle) -> dict[str, Any]:
    """样式形状：键名与面板提交的 `style` 完全一致，可直接喂给 build_apply_plan"""
    return {
        "preset": style.preset,
        "colors": dict(style.colors),
        "fonts": list(style.fonts),
        "page_width": style.page_width,
        "ppi": style.ppi,
        "split_height": style.split_height,
        "single_column_threshold": style.single_column_threshold,
        "giant_threshold": style.giant_threshold,
        "output_format": style.output_format,
        "timeout_analysis": style.timeout_analysis,
        "timeout_compile": style.timeout_compile,
        "plugin_two_lines": style.plugin_two_lines,
        "hero_header": style.hero_header,
        "background": style.background,
        "category": style.category.to_plain(),
        "custom_presets": [
            {"name": item["name"], "colors": dict(item["colors"])}
            for item in style.custom_presets
        ],
    }


def style_active_payload(style: PreviewStyle) -> dict[str, Any]:
    """表单形状：键名与 `build_options()["active"]` 一致，前端据此回填控件"""
    return {
        "preset": style.preset,
        "colors": dict(style.colors),
        "fonts": list(style.fonts),
        "page_width": style.page_width,
        "ppi": style.ppi,
        "split_height": style.split_height,
        "single_column_threshold": style.single_column_threshold,
        "giant_threshold": style.giant_threshold,
        "output_format": style.output_format,
        "timeout_analysis": style.timeout_analysis,
        "timeout_compile": style.timeout_compile,
        "plugin_two_lines": style.plugin_two_lines,
        "hero_header": style.hero_header,
        "background": style.background,
        "ignored": {
            "selected": list(style.ignored_plugins),
            "custom": list(style.ignored_plugins_custom),
        },
        "category": style.category.to_plain(),
    }

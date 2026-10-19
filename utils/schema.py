"""配置 Schema 的运行时改写

插件屏蔽项要做成「已安装插件多选」, 但已安装插件集合随环境变化,
只能像字体下拉那样在运行时改写 `_conf_schema.json` 的 options。
"""

import json
import os
from pathlib import Path
from typing import Any

from astrbot.api import logger

# 与 _conf_schema.json 里的配置键保持一致
PLUGIN_IGNORE_KEY = "ignored_plugins"


def write_schema_atomic(schema_path: Path, schema: dict[str, Any]) -> bool:
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
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"[HelpTypst] Schema 写入失败，已保留原文件: {e}")
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _build_options(
    plugins: list[dict[str, Any]], extra_names: list[str]
) -> tuple[list[str], list[str]]:
    """构造 options 与 labels: 已安装插件在前, 未安装的旧条目追加在后

    未安装的名字也要留在 options 里: 面板的多选框只显示 options 内的值,
    缺失的旧条目会变成「看不见也删不掉」的幽灵屏蔽。
    """
    options: list[str] = []
    labels: list[str] = []
    seen: set[str] = set()

    for plugin in plugins:
        name = str(plugin.get("name") or "").strip()
        if not name or name in seen:
            continue
        display = str(plugin.get("display_name") or "").strip() or name
        if plugin.get("disabled"):
            display = f"{display}（已禁用）"
        seen.add(name)
        options.append(name)
        labels.append(display)

    for name in extra_names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        options.append(name)
        labels.append(f"{name}（未安装）")

    return options, labels


def sync_plugin_options(
    schema_path: Path,
    live_schema: dict[str, Any] | None,
    plugins: list[dict[str, Any]],
    extra_names: list[str],
) -> None:
    """把屏蔽插件的多选选项同步到 Schema (磁盘 + 内存)

    Args:
        schema_path: `_conf_schema.json` 的磁盘路径。
        live_schema: 内存中的 `config.schema`, 同步后无需重载即可生效。
        plugins: 已安装插件列表, 每项含 name / display_name / disabled。
        extra_names: 当前配置里未安装的插件名 (保留为可见的旧条目)。
    """
    # 插件列表为空说明读取失败(本插件自己也在注册表里), 此时保留原选项,
    # 否则用户会丢失现有的勾选项
    if not plugins:
        return

    options, labels = _build_options(plugins, extra_names)
    if not options:
        return

    if schema_path.exists():
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            target = schema.get(PLUGIN_IGNORE_KEY)
            if isinstance(target, dict) and (
                target.get("options") != options or target.get("labels") != labels
            ):
                target["options"] = options
                target["labels"] = labels
                if write_schema_atomic(schema_path, schema):
                    logger.info("[HelpTypst] 已更新屏蔽插件选项")
        except (OSError, ValueError) as e:
            logger.warning(f"[HelpTypst] 屏蔽插件 Schema 更新失败: {e}")

    if isinstance(live_schema, dict):
        try:
            target = live_schema[PLUGIN_IGNORE_KEY]
            if isinstance(target, dict):
                target["options"] = options
                target["labels"] = labels
        except (KeyError, TypeError):
            pass

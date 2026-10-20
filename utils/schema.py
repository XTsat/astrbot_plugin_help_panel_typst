"""配置 Schema 的运行时同步

插件屏蔽项要做成「已安装插件多选」, 但已安装插件集合随环境变化, 只能像字体下拉
那样在运行时改内存里的 schema (`config.schema`)。

仓库内的 `_conf_schema.json` 保持静态: 把本机字体与插件列表写回磁盘会让插件目录
在运行时被悄悄改动, 升级或提交时容易把环境相关的选项混进变更。
"""

from typing import Any

from astrbot.api import logger

# 与 _conf_schema.json 里的配置键保持一致
PLUGIN_IGNORE_KEY = "ignored_plugins"


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
    live_schema: dict[str, Any] | None,
    plugins: list[dict[str, Any]],
    extra_names: list[str],
) -> None:
    """把屏蔽插件的多选选项同步到内存 Schema (不改写磁盘文件)

    Args:
        live_schema: 内存中的 `config.schema`, 面板实时读取它, 同步后无需重载。
        plugins: 已安装插件列表, 每项含 name / display_name / disabled。
        extra_names: 当前配置里未安装的插件名 (保留为可见的旧条目)。
    """
    if not isinstance(live_schema, dict):
        return
    # 插件列表为空说明读取失败(本插件自己也在注册表里), 此时保留原选项,
    # 否则用户会丢失现有的勾选项
    if not plugins:
        return

    options, labels = _build_options(plugins, extra_names)
    if not options:
        return

    try:
        target = live_schema[PLUGIN_IGNORE_KEY]
    except (KeyError, TypeError):
        return
    if isinstance(target, dict) and (
        target.get("options") != options or target.get("labels") != labels
    ):
        target["options"] = options
        target["labels"] = labels
        logger.info("[HelpTypst] 已更新屏蔽插件选项（内存，不改写 Schema 文件）")

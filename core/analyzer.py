import re
from collections import defaultdict
from enum import Enum
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.core.star.star_handler import (
    star_handlers_registry,
    StarHandlerMetadata,
    EventType,
)
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter, PermissionType
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.filter.platform_adapter_type import (
    PlatformAdapterTypeFilter,
    PlatformAdapterType,
)
from astrbot.core.star.filter.event_message_type import (
    EventMessageTypeFilter,
    EventMessageType,
)
from astrbot.core.agent.mcp_client import MCPTool

from ..domain import PluginMetadata, RenderNode, InternalCFG, TypstPluginConfig


# 命令监听描述识别: 头部含「命令/指令」, 冒号后为顿号/逗号分隔的关键词列表
_LIST_SEP_RE = re.compile(r"[、，,;；|/]")


def _extract_command_keywords(desc: str) -> list[str]:
    """从事件监听器 desc 中启发式提取命令关键词列表。

    仅当 desc 形如「监听…命令：a、b、c」时返回关键词, 否则返回空列表
    (调用方据此决定是否回退为原始 desc 展示)。
    """
    if not desc:
        return []
    head, sep, tail = desc.partition("：")
    if not sep:
        head, sep, tail = desc.partition(":")
    if not sep:
        return []
    # 头部须暗示「命令/指令」
    if "命令" not in head and "指令" not in head:
        return []
    # 尾部须为列表形式 (含顿号/逗号等分隔符)
    if not _LIST_SEP_RE.search(tail):
        return []
    keywords = [t.strip() for t in _LIST_SEP_RE.split(tail) if t.strip()]
    # 过滤: 关键词应为短词, 剔除误切的长句/纯标点
    return [k for k in keywords if 1 <= len(k) <= 16]


def get_safe_plugin_info(star_meta: Any) -> dict[str, str | None]:
    """针对不规范的插件元信息进行防御性编程"""
    if not star_meta:
        return {
            "name": "Unknown",
            "display_name": None,
            "version": "",
            "desc": "",
            "author": "",
            "raw_module": None,  # handler 查找, 与正常分支保持同键
        }

    # 智能名称
    raw_name = getattr(
        star_meta, "name", None
    )  # 标准插件名 (metadata.yaml 或 @register)
    raw_root_dir = getattr(star_meta, "root_dir_name", None)  # 目录名
    raw_module = getattr(star_meta, "module_path", None)  # 模块路径

    # 决策树
    if raw_name:
        safe_name = str(raw_name)
    elif raw_root_dir:
        safe_name = str(raw_root_dir)
    elif raw_module:
        parts = str(raw_module).split(".")
        safe_name = parts[-2] if len(parts) > 2 and parts[-1] == "main" else parts[-1]
    else:
        safe_name = f"Unknown_{id(star_meta)}"  # 正常不应走到这，因为无标识符插件根本加载不了

    # 其他字段
    display = getattr(star_meta, "display_name", None)
    if not display:
        display = None

    version = str(getattr(star_meta, "version", "")) or ""
    desc = str(getattr(star_meta, "desc", "")) or ""
    author = str(getattr(star_meta, "author", "")) or ""

    return {
        "name": safe_name,
        "display_name": display,
        "version": version,
        "desc": desc,
        "author": author,
        "raw_module": raw_module,  # handler 查找
    }


def list_installed_plugins(context: Context) -> list[dict[str, Any]]:
    """列出已安装插件, 供配置面板/预览页把屏蔽项做成多选

    取 context.get_all_stars() 而非 handler 注册表: 后者只包含已加载成功的插件,
    被禁用的插件仍应出现在屏蔽列表里 (禁用了也可能想屏蔽)。加载失败的插件
    根本不在列表里, 由自定义条目兜底。
    """
    try:
        stars = context.get_all_stars()
    except Exception as exc:
        logger.warning(f"[HelpTypst] 读取已安装插件列表失败, 屏蔽项回退为手动填写: {exc}")
        return []

    plugins: dict[str, dict[str, Any]] = {}
    for star in stars or []:
        info = get_safe_plugin_info(star)
        name = info["name"]
        if not name or name.startswith("Unknown_"):
            continue
        # 同名去重: 同一插件可能因多次加载出现在列表里
        if name in plugins:
            continue
        plugins[name] = {
            "name": name,
            "display_name": info["display_name"] or name,
            # 激活状态为 False 的插件仍可被屏蔽, 前端只做标记
            "disabled": getattr(star, "activated", True) is False,
        }
    return sorted(plugins.values(), key=lambda item: str(item["name"]))


class BaseAnalyzer:
    def __init__(self, context: Context, config: TypstPluginConfig):
        self.context = context
        self.cfg = config

    def get_plugins(self, query: str | None = None) -> list[PluginMetadata]:
        """获取（经过搜索过滤的）插件列表"""
        if not query:
            query = None

        try:
            # 1. 获取全量数据
            structured_plugins = self.analyze_hierarchy()

            # 2. 非搜索 → 返回
            if not query:
                return structured_plugins

            # 3. 搜索 → 过滤
            q_lower = query.lower()
            filtered_plugins = []

            for p in structured_plugins:
                p_copy = p.model_copy(deep=True)
                # 检查插件(容器)本身是否匹配: 在Command模式下，p是插件；在Event/Filter模式下，p是分类组(如 OnMessage)
                is_container_match = self._is_container_match(p_copy, q_lower)

                if is_container_match:
                    # 容器匹配 -> 保留整个容器及其所有内容
                    filtered_plugins.append(p_copy)
                else:
                    # 容器不匹配 -> 深入内部进行剪枝(过滤 nodes 列表，只保留匹配的子节点)
                    matched_nodes = self._filter_nodes_recursively(
                        p_copy.nodes, q_lower
                    )

                    if matched_nodes:
                        # 保留有剩余节点的容器
                        p_copy.nodes = matched_nodes
                        filtered_plugins.append(p_copy)

            return filtered_plugins

        except Exception as e:
            logger.error(f"[HelpTypst] 分析失败: {e}", exc_info=True)
            return []

    def get_plugin_by_order(self, order: int) -> list[PluginMetadata]:
        """按全局编号精确定位单个插件 (编号语义仅指令模式存在)

        编号由 CommandAnalyzer._assign_global_order 在过滤前统一分配,
        因此与全量列表展示的编号一致。未命中返回空列表。
        """
        try:
            for p in self.analyze_hierarchy():
                if p.order == order:
                    return [p]
            return []
        except Exception as e:
            logger.error(f"[HelpTypst] 按编号 {order} 分析失败: {e}", exc_info=True)
            return []

    def _is_container_match(self, plugin: PluginMetadata, query: str) -> bool:
        """容器匹配: 可见标题 (display_name, 无则回落 name) + 描述

        事件分组 / 过滤器卡片过去把内部标识 (event_group / filter_regex) 写进 name 并参与
        搜索, 命中后会把整棵树带出来; 现在这些容器的 name 已改为可读标题, 只有「真实插件」
        (category 非空) 与工具卡才额外允许按插件 ID / MCP 服务名 搜索。
        """
        title = plugin.display_name or plugin.name
        if self._is_match(title, None, plugin.desc, query):
            return True
        is_tool_card = bool(plugin.nodes) and plugin.nodes[0].tag in ("tool", "mcp")
        if plugin.category or is_tool_card:
            return self._is_match(plugin.name, None, "", query)
        return False

    @staticmethod
    def _node_search_extras(node: RenderNode) -> list[str]:
        """节点可搜索的附加可见文本: 别名 / 参数占位 / 事件监听器提取的命令关键词"""
        extras = list(node.aliases or [])
        if node.params:
            extras.append(node.params)
        extras.extend(node.commands or [])
        return extras

    def _is_match(
        self,
        name: str,
        display: str | None,
        desc: str,
        query: str,
        extras: list[str] | None = None,
    ) -> bool:
        """基础匹配检查 (大小写不敏感子串, 不做正则拼接)"""
        if query in name.lower():
            return True
        if display and query in display.lower():
            return True
        if desc and query in desc.lower():
            return True
        if extras:
            for extra in extras:
                if extra and query in extra.lower():
                    return True
        return False

    def _filter_nodes_recursively(
        self, nodes: list[RenderNode], query: str
    ) -> list[RenderNode]:
        """递归过滤节点树，返回一个新的包含匹配的节点的节点列表"""
        result = []
        for node in nodes:
            # 1. 检查自身匹配
            self_match = self._is_match(
                node.name, None, node.desc, query, self._node_search_extras(node)
            )

            # 2. 递归检查子节点
            if self_match:
                # 若节点本身匹配，保留上下文
                result.append(node)
            else:
                # 节点本身不匹配，检查子节点
                if node.children:
                    filtered_children = self._filter_nodes_recursively(
                        node.children, query
                    )
                    if filtered_children:
                        # 有子节点存活时，保留过滤后的当前节点
                        node.children = filtered_children
                        result.append(node)
        return result

    def analyze_hierarchy(self) -> list[PluginMetadata]:
        raise NotImplementedError

    def _derive_category(self, info: dict[str, str | None]) -> str:
        """根据插件元信息推断分类: 关键词命中 (desc/name/display_name) → 兜底

        分类规则与兜底分类名来自设置面板 category 配置 (默认预置
        DefaultCFG.DEFAULT_CATEGORY_KEYWORDS, 用户可自由增删改)。
        """
        text_parts = []
        for key in ("desc", "name", "display_name"):
            val = info.get(key)
            if val:
                text_parts.append(str(val))
        text = " ".join(text_parts).lower()

        return self.cfg.category.match(text)

    def _group_handlers_by_module(self) -> dict[str, list[StarHandlerMetadata]]:
        mapping = defaultdict(list)
        for handler in star_handlers_registry:
            if isinstance(handler, StarHandlerMetadata) and handler.handler_module_path:
                mapping[handler.handler_module_path].append(handler)
        return mapping

    def _module_to_plugin_map(self) -> dict[str, Any]:
        """插件模块路径 → 插件对象 (只做精确索引, 模糊归属交给 _resolve_plugin)"""
        mapping: dict[str, Any] = {}
        for star in self.context.get_all_stars():
            module_path = getattr(star, "module_path", None)
            if module_path:
                mapping[str(module_path)] = star
        return mapping

    @staticmethod
    def _module_relation(target: str, candidate: str) -> int:
        """target 相对 candidate 的归属强度: 3 相等 / 2 同插件包 / 1 candidate 是祖先 / 0 无关

        以 `.` 为边界判断, 避免 `astrbot_plugin_help` 误匹配 `astrbot_plugin_help_panel_typst`。
        插件的 handler 常定义在与 main 同级的子模块 (handlers.py 等), 单靠前缀判断会漏;
        而按「共同父包」判断同插件, 又不会把相邻插件的模块算进来。
        """
        if target == candidate:
            return 3
        if target.rsplit(".", 1)[0] == candidate.rsplit(".", 1)[0]:
            return 2
        if candidate.startswith(target + "."):
            return 2
        if target.startswith(candidate + "."):
            return 1
        return 0

    def _resolve_handlers(
        self, raw_module: str | None, handlers_map: dict[str, list[StarHandlerMetadata]]
    ) -> list[StarHandlerMetadata]:
        """按插件模块路径取 handler 列表: 精确优先, 否则在全部候选里选归属最强的

        不能「首个前缀命中即 break」: 那样结果取决于 handlers_map 的插入顺序, 会把前缀
        相近的其它插件的 handler 整包挂过来。多候选时比较 归属强度 → handler 数 → 路径长度。
        """
        if not raw_module:
            return []
        exact = handlers_map.get(raw_module)
        if exact:
            return exact

        best_handlers: list[StarHandlerMetadata] = []
        best_score = (0, 0, 0)
        for key, handlers in handlers_map.items():
            relation = self._module_relation(raw_module, key)
            if relation == 0:
                continue
            score = (relation, len(handlers), len(key))
            if score > best_score:
                best_score = score
                best_handlers = handlers
        return best_handlers

    def _resolve_plugin(
        self, handler_module: str, module_to_plugin: dict[str, Any]
    ) -> Any | None:
        """按 handler 模块路径反查插件对象: 精确优先, 否则取归属最强的插件模块

        与 _resolve_handlers 共用 _module_relation, 保证指令 / 事件 / 过滤器三种面板口径一致。
        """
        plugin = module_to_plugin.get(handler_module)
        if plugin is not None:
            return plugin

        best_plugin: Any | None = None
        best_score = (0, 0)
        for key, star in module_to_plugin.items():
            relation = self._module_relation(handler_module, key)
            if relation == 0:
                continue
            score = (relation, len(key))
            if score > best_score:
                best_score = score
                best_plugin = star
        return best_plugin

    def _get_safe_plugin_info(self, star_meta: Any) -> dict[str, str | None]:
        return get_safe_plugin_info(star_meta)


class CommandAnalyzer(BaseAnalyzer):
    """指令分析器：处理 CommandFilter / CommandGroupFilter"""

    def analyze_hierarchy(self) -> list[PluginMetadata]:
        handlers_map = self._group_handlers_by_module()
        results = []
        all_stars = self.context.get_all_stars()

        logger.debug(
            f"[HelpTypst] 开始分析指令。共扫描到 {len(all_stars)} 个已加载插件。"
        )

        for star_meta in all_stars:
            # 禁用插件不再跳过: 标记 disabled=True 供模板灰化展示 (仅指令模式)
            disabled = not star_meta.activated

            info = self._get_safe_plugin_info(star_meta)
            safe_name = info["name"]
            raw_module = info["raw_module"]
            plugin_name = safe_name
            category = self._derive_category(info)

            # 黑名单
            if safe_name in self.cfg.effective_ignored_plugins:
                continue

            # --- 构建指令树 (即使无指令也展示插件卡片) ---
            try:
                nodes: list[RenderNode] = []
                handlers = self._resolve_handlers(raw_module, handlers_map)
                if handlers:
                    nodes = self._build_plugin_command_tree(handlers)

                results.append(
                    PluginMetadata(
                        name=plugin_name,
                        display_name=info["display_name"],
                        version=info["version"],
                        desc=info["desc"],
                        author=info["author"],
                        category=category,
                        disabled=disabled,
                        nodes=nodes,
                    )
                )
                if not nodes:
                    logger.debug(f"[HelpTypst] 插件 {safe_name} 无注册指令，仅展示基本信息。")
            except Exception as e:
                logger.warning(f"[HelpTypst] 处理插件 {safe_name} 时发生异常: {e}")
                continue

        # 按分类分组排序, 并分配全局连续编号 (跨分类)
        results = self._assign_global_order(results)

        logger.debug(f"[HelpTypst] 指令分析完成。共展示 {len(results)} 个插件。")
        return results

    def _assign_global_order(
        self, plugins: list[PluginMetadata]
    ) -> list[PluginMetadata]:
        """按分类分组排序, 为每个插件分配跨分类连续的全局编号 order"""
        fallback = self.cfg.category.fallback

        # 按分类聚合
        grouped: dict[str, list[PluginMetadata]] = {}
        for p in plugins:
            cat = (p.category or "").strip() or fallback
            grouped.setdefault(cat, []).append(p)

        # 分类名升序, 兜底分类置底
        names = sorted(grouped.keys())
        if fallback in names:
            names.remove(fallback)
            names.append(fallback)

        # 分类内插件排序, 展平为全局序列
        ordered: list[PluginMetadata] = []
        for name in names:
            plist = sorted(
                grouped[name], key=lambda x: (x.display_name is None, x.name)
            )
            ordered.extend(plist)

        # 分配全局连续编号
        for idx, p in enumerate(ordered, start=1):
            p.order = idx
        return ordered

    def _build_plugin_command_tree(
        self, handlers: list[StarHandlerMetadata]
    ) -> list[RenderNode]:
        nodes = []
        # 黑名单扫描：防止子组重复出现在顶层
        child_handlers_blacklist = self._scan_all_children(handlers)

        # 1. 顶级组
        for handler in handlers:
            if handler.handler_name in child_handlers_blacklist:
                continue
            group_filter = self._get_filter(handler, CommandGroupFilter)
            if group_filter:
                try:
                    node = self._parse_group(handler, group_filter)
                    if node:
                        nodes.append(node)
                except Exception as e:
                    logger.warning(
                        f"[HelpTypst] 解析指令组 {handler.handler_name} 失败: {e}"
                    )

        # 2. 独立指令
        for handler in handlers:
            if handler.handler_name in child_handlers_blacklist:
                continue
            if self._get_filter(handler, CommandGroupFilter):
                continue
            cmd_filter = self._get_filter(handler, CommandFilter)
            if cmd_filter:
                try:
                    node = self._parse_command_node(handler, cmd_filter)
                    if node:
                        nodes.append(node)
                except Exception as e:
                    logger.warning(
                        f"[HelpTypst] 解析指令 {handler.handler_name} 失败: {e}"
                    )

        self._sort_nodes(nodes)
        return nodes

    def _scan_all_children(self, handlers: list[StarHandlerMetadata]) -> set[str]:
        blacklist = set()
        groups_map = {}
        for h in handlers:
            gf = self._get_filter(h, CommandGroupFilter)
            if gf:
                groups_map[gf.group_name] = h.handler_name

        def _scan_recursive(filter_obj):
            h_md = getattr(filter_obj, "handler_md", None)
            if h_md and hasattr(h_md, "handler_name"):
                blacklist.add(h_md.handler_name)

            if isinstance(filter_obj, CommandGroupFilter):
                if filter_obj.group_name in groups_map:
                    blacklist.add(groups_map[filter_obj.group_name])

            if hasattr(filter_obj, "sub_command_filters"):
                for sub in filter_obj.sub_command_filters:
                    _scan_recursive(sub)

        for h in handlers:
            gf = self._get_filter(h, CommandGroupFilter)
            if gf:
                for sub in gf.sub_command_filters:
                    _scan_recursive(sub)
        return blacklist

    def _parse_group(
        self, handler: StarHandlerMetadata, group_filter: CommandGroupFilter
    ) -> RenderNode:
        desc = (handler.desc or "").split("\n")[0].strip()
        children = []
        for sub_filter in group_filter.sub_command_filters:
            child = self._process_sub_filter(sub_filter)
            if child:
                children.append(child)

        self._sort_nodes(children)
        return RenderNode(
            name=group_filter.group_name,
            desc=desc or "指令组",
            is_group=True,
            tag=self._check_permission(handler),
            children=children,
        )

    def _process_sub_filter(self, filter_obj: Any) -> RenderNode | None:
        handler = getattr(filter_obj, "handler_md", None)
        desc = self._get_desc_safely(handler)
        tag = self._check_permission(handler) if handler else "normal"

        if isinstance(filter_obj, CommandFilter):
            return RenderNode(
                name=filter_obj.command_name,
                desc=desc,
                is_group=False,
                tag=tag,
                aliases=self._get_command_aliases(filter_obj),
                params=self._get_command_params(handler),
            )

        elif isinstance(filter_obj, CommandGroupFilter):
            children = []
            if hasattr(filter_obj, "sub_command_filters"):
                for sf in filter_obj.sub_command_filters:
                    child = self._process_sub_filter(sf)
                    if child:
                        children.append(child)
            self._sort_nodes(children)
            return RenderNode(
                name=filter_obj.group_name,
                desc=desc or "子指令组",
                is_group=True,
                tag=tag,
                children=children,
            )
        return None

    def _parse_command_node(
        self, handler: StarHandlerMetadata, cmd_filter: CommandFilter
    ) -> RenderNode:
        desc = (handler.desc or "").split("\n")[0].strip()
        return RenderNode(
            name=cmd_filter.command_name,
            desc=desc,
            is_group=False,
            tag=self._check_permission(handler),
            aliases=self._get_command_aliases(cmd_filter),
            params=self._get_command_params(handler),
        )

    def _sort_nodes(self, nodes: list[RenderNode]):
        nodes.sort(key=lambda x: (x.is_group, x.name))

    def _check_permission(self, handler: Any) -> str:
        if not handler or not hasattr(handler, "event_filters"):
            return "normal"
        for f in handler.event_filters:
            if isinstance(f, PermissionTypeFilter):
                # 仅当权限类型为 ADMIN 时才需要管理员权限;
                # MEMBER 仅需普通成员 (任何人均可), 应归类为普通指令
                if getattr(f, "permission_type", None) == PermissionType.ADMIN:
                    return "admin"
                return "normal"
        return "normal"

    def _get_filter(self, handler: StarHandlerMetadata, filter_type):
        if not hasattr(handler, "event_filters"):
            return None
        for f in handler.event_filters:
            if isinstance(f, filter_type):
                return f
        return None

    def _get_desc_safely(self, handler: Any) -> str:
        if not handler:
            return ""
        raw = getattr(handler, "desc", "") or ""
        return raw.split("\n")[0].strip()

    def _get_command_aliases(self, cmd_filter: CommandFilter) -> list[str]:
        """安全地从 CommandFilter 中提取别名列表。

        AstrBot 的 @filter.command("name", alias={...}) 将别名集存储在
        CommandFilter.alias 属性中。使用 getattr 兜底兼容旧版本。
        """
        raw = getattr(cmd_filter, "alias", None)
        if raw is None:
            return []
        if isinstance(raw, (set, tuple, list)):
            return [str(a) for a in raw if a]
        if isinstance(raw, str):
            return [raw]
        return []

    def _get_command_params(self, handler: Any) -> str:
        """从 handler 签名中提取指令参数占位符。

        支持 AstrBot 常见参数类型注解:
          GreedyStr / Str → "?" (可跟任意参数)
        其余类型或无注解 → "" (无参数占位提示)

        参数顺序: 方法签名一般为 (self, event, *args), 从第 3 个参数开始检查。
        """
        func = getattr(handler, "handler", None)
        if func is None:
            return ""
        try:
            import inspect

            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            for p in params[2:]:
                ann = p.annotation
                ann_name = getattr(ann, "__name__", None)
                if ann_name in ("GreedyStr", "Str"):
                    return "?"
            return ""
        except (ValueError, TypeError):
            # 某些内置 handler 无法解析签名, 忽略参数提取
            return ""


class EventAnalyzer(BaseAnalyzer):
    """事件分析器：处理所有 EventType，获取完整工具列表（含 MCP）"""

    @staticmethod
    def _event_type_sort_key(evt_type: Any) -> tuple[int, str]:
        """事件分组排序键: 先按 EVENT_TYPE_MAP 登记顺序, 未登记类型排后并按名排序"""
        try:
            return (list(InternalCFG.EVENT_TYPE_MAP).index(evt_type), "")
        except ValueError:
            return (
                len(InternalCFG.EVENT_TYPE_MAP),
                str(getattr(evt_type, "name", evt_type)),
            )

    def analyze_hierarchy(self) -> list[PluginMetadata]:
        results = []

        # 1. 映射模块路径到插件对象 (模糊归属由 _resolve_plugin 统一处理, 与指令/过滤器口径一致)
        module_to_plugin = self._module_to_plugin_map()

        # --- A.处理函数工具 (Plugin Tools + MCP Tools) ---
        # 获取工具列表
        tool_manager = None
        if hasattr(self.context, "get_llm_tool_manager"):
            tool_manager = self.context.get_llm_tool_manager()

        tool_cards: list[PluginMetadata] = []
        if tool_manager:
            for tool in tool_manager.func_list:
                if not tool.active:
                    continue

                source_name = "Unknown"
                source_display = None
                source_version = ""  # 默认为空，MCP 无版本号
                tag = "tool"

                # >>> 来源: MCP <<<
                if MCPTool and isinstance(tool, MCPTool):
                    source_name = f"MCP/{tool.mcp_server_name}"
                    source_display = f"🔌 {tool.mcp_server_name}"
                    tag = "mcp"
                elif tool.handler_module_path:
                    # >>> 来源: 插件 <<<
                    plugin = self._resolve_plugin(
                        tool.handler_module_path, module_to_plugin
                    )
                    if plugin:
                        if plugin.name in self.cfg.effective_ignored_plugins:
                            continue
                        source_name = plugin.name
                        source_display = getattr(plugin, "display_name", None)
                        source_version = getattr(plugin, "version", "")
                    else:
                        source_name = "Core/Unknown"

                desc = (tool.description or "").split("\n")[0].strip()

                node = RenderNode(name=tool.name, desc=desc, is_group=False, tag=tag)

                # 包装为 PluginMetadata
                pm = PluginMetadata(
                    name=source_name,
                    display_name=source_display,
                    version=source_version,
                    desc="",
                    nodes=[node],
                )
                tool_cards.append(pm)

        # 工具卡按 来源 + 工具名 排序, 渲染顺序不随注册顺序漂移
        tool_cards.sort(key=lambda p: (p.name, p.nodes[0].name if p.nodes else ""))
        results.extend(tool_cards)

        # --- B.处理普通事件 (排除 OnCallingFuncToolEvent)  ---
        event_groups = defaultdict(list)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue

            if self._is_command_handler(handler):
                continue
            if handler.event_type == EventType.OnCallingFuncToolEvent:
                continue

            plugin = self._resolve_plugin(handler.handler_module_path, module_to_plugin)
            if plugin is None:
                continue
            info = self._get_safe_plugin_info(plugin)
            if info["name"] in self.cfg.effective_ignored_plugins:
                continue  # 黑名单
            if not plugin.activated:
                continue

            event_groups[handler.event_type].append(handler)

        for evt_type, handlers in sorted(
            event_groups.items(), key=lambda kv: self._event_type_sort_key(kv[0])
        ):
            card_title = InternalCFG.EVENT_TYPE_MAP.get(evt_type)

            nodes = []
            for h in handlers:
                plugin = self._resolve_plugin(h.handler_module_path, module_to_plugin)
                p_info = self._get_safe_plugin_info(plugin)

                # 构造节点
                p_name = p_info["name"]
                p_display = p_info["display_name"]
                main_name = p_display if p_display else p_name

                raw_desc = (h.desc or "").split("\n")[0].strip()
                if not raw_desc and h.handler.__doc__:
                    raw_desc = h.handler.__doc__.split("\n")[0].strip()

                full_desc = ""
                if p_display:
                    full_desc = f"@{p_name}"

                if raw_desc:
                    if full_desc:
                        full_desc += f" · {raw_desc}"
                    else:
                        full_desc = raw_desc

                prio = h.extras_configs.get("priority", 0)
                nodes.append(
                    RenderNode(
                        name=main_name,
                        desc=full_desc,
                        is_group=False,
                        tag="event_listener",
                        priority=prio,
                    )
                )

            nodes.sort(key=lambda x: (-(x.priority or 0), x.name))

            pm = PluginMetadata(
                name=card_title,
                display_name=None,
                version="",
                desc=f"共 {len(nodes)} 个挂载点",
                nodes=nodes,
            )
            results.append(pm)

        return results

    def get_plugin_event_listeners(self, plugin_name: str) -> list[RenderNode]:
        """获取指定插件的所有事件监听器节点 (用于插件详情页)。

        通过 _get_safe_plugin_info 派生插件名进行匹配, 与 CommandAnalyzer 产出
        的 PluginMetadata.name 保持一致。
        """
        results: list[RenderNode] = []

        # 1. 定位目标插件对象 (模块归属交给 _resolve_plugin, 与其余分析器口径一致)
        module_to_plugin = self._module_to_plugin_map()
        target_star: Any | None = None
        for star in module_to_plugin.values():
            if self._get_safe_plugin_info(star)["name"] == plugin_name:
                target_star = star
                break

        if target_star is None:
            return results

        # 2. 收集该插件的非指令事件监听器
        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue
            if (
                self._resolve_plugin(handler.handler_module_path, module_to_plugin)
                is not target_star
            ):
                continue
            if self._is_command_handler(handler):
                continue  # 纯 @command 已在指令区展示
            if handler.event_type == EventType.OnCallingFuncToolEvent:
                continue  # 函数工具已在工具区展示

            raw_desc = (handler.desc or "").split("\n")[0].strip()
            if not raw_desc and handler.handler.__doc__:
                raw_desc = handler.handler.__doc__.split("\n")[0].strip()

            prio = handler.extras_configs.get("priority", 0)
            results.append(
                RenderNode(
                    name=handler.handler_name,
                    desc=raw_desc,
                    is_group=False,
                    tag="event_listener",
                    priority=prio,
                    commands=_extract_command_keywords(raw_desc),
                )
            )

        results.sort(key=lambda x: (-(x.priority or 0), x.name))
        return results

    def _is_command_handler(self, handler: StarHandlerMetadata) -> bool:
        if not handler.event_filters:
            return False
        for f in handler.event_filters:
            if isinstance(f, (CommandFilter, CommandGroupFilter)):
                return True
        return False


class FilterAnalyzer(BaseAnalyzer):
    """过滤器分析器"""

    def analyze_hierarchy(self) -> list[PluginMetadata]:
        results = []
        module_to_plugin = self._module_to_plugin_map()

        # 数据容器
        regex_data = defaultdict(list)
        platform_data = defaultdict(list)
        msgtype_data = defaultdict(list)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue

            # 关联插件对象
            plugin = self._resolve_plugin(handler.handler_module_path, module_to_plugin)
            if plugin is None:
                continue
            p_info = self._get_safe_plugin_info(plugin)
            if p_info["name"] in self.cfg.effective_ignored_plugins:
                continue  # 黑名单
            if not plugin.activated:
                continue

            if not handler.event_filters:
                continue

            # 分类收集 Filter
            for f in handler.event_filters:
                if isinstance(f, RegexFilter):
                    regex_data[handler.handler_module_path].append(
                        (f.regex_str, handler)
                    )
                elif isinstance(f, PlatformAdapterTypeFilter):
                    names = self._format_flags(f.platform_type, PlatformAdapterType)
                    key = f"🌍 {names}"
                    platform_data[key].append(handler)
                elif isinstance(f, EventMessageTypeFilter):
                    names = self._format_flags(f.event_message_type, EventMessageType)
                    key = f"📨 {names}"
                    msgtype_data[key].append(handler)

        # --- 1. Regex 卡片 按插件分组 ---
        if regex_data:
            nodes = []
            for mod_path, items in regex_data.items():
                plugin = self._resolve_plugin(mod_path, module_to_plugin)
                p_info = (
                    self._get_safe_plugin_info(plugin)
                    if plugin
                    else self._get_safe_plugin_info(None)
                )
                p_name = p_info["name"]
                p_display = p_info["display_name"]

                sorted_items = sorted(items, key=lambda x: x[0])

                children = []
                for r_str, h in sorted_items:
                    raw_desc = (h.desc or "").split("\n")[0].strip()
                    if not raw_desc and h.handler.__doc__:
                        raw_desc = h.handler.__doc__.split("\n")[0].strip()

                    # 正则的子项描述：#{函数名} · {描述}
                    full_desc = f"#{h.handler_name}"
                    if raw_desc:
                        full_desc += f" · {raw_desc}"

                    children.append(
                        RenderNode(
                            name=r_str,
                            desc=full_desc,
                            is_group=False,
                            tag="regex_pattern",
                        )
                    )

                container_desc = f"@{p_name}" if p_display else ""  # 父节点描述 @ID
                container_name = p_display if p_display else p_name

                nodes.append(
                    RenderNode(
                        name=container_name,
                        desc=container_desc,
                        is_group=True,
                        tag="plugin_container",
                        children=children,
                    )
                )

            nodes.sort(key=lambda x: x.name)

            results.append(
                PluginMetadata(
                    name="正则触发器 (Regex)",
                    display_name=None,
                    version="",
                    desc=f"共 {len(nodes)} 个插件使用了正则",
                    nodes=nodes,
                )
            )

        # --- 2. Platform 卡片  ---
        if platform_data:
            results.append(
                self._build_criteria_card(
                    "平台限制 (Platform)", platform_data, module_to_plugin
                )
            )

        # --- 3. MsgType 卡片 ---
        if msgtype_data:
            results.append(
                self._build_criteria_card(
                    "消息类型限制 (MsgType)", msgtype_data, module_to_plugin
                )
            )

        return results

    def _build_criteria_card(
        self,
        title: str,
        data: dict[str, list[StarHandlerMetadata]],
        module_to_plugin: dict[str, Any],
    ) -> PluginMetadata:
        nodes = []
        sorted_keys = sorted(data.keys())

        for filter_str in sorted_keys:
            handlers = data[filter_str]
            children = []

            for h in handlers:
                plugin = self._resolve_plugin(h.handler_module_path, module_to_plugin)
                p_info = self._get_safe_plugin_info(plugin)
                p_name = p_info["name"]
                p_display = p_info["display_name"]

                main_name = p_display if p_display else p_name

                raw_desc = (h.desc or "").split("\n")[0].strip()
                if not raw_desc and h.handler.__doc__:
                    raw_desc = h.handler.__doc__.split("\n")[0].strip()

                parts = []

                # 1. 来源插件
                if p_display:
                    parts.append(f"@{p_name}")

                # 2. 函数名
                parts.append(f"#{h.handler_name}")

                # 3. 原始描述
                if raw_desc:
                    parts.append(raw_desc)

                full_desc = " · ".join(parts)
                prio = h.extras_configs.get("priority", 0)

                children.append(
                    RenderNode(
                        name=main_name,
                        desc=full_desc,
                        is_group=False,
                        tag="event_listener",
                        priority=prio,
                    )
                )

            children.sort(key=lambda x: (-(x.priority or 0), x.name))

            nodes.append(
                RenderNode(
                    name=filter_str,
                    desc=f"{len(children)} 个监听点",
                    is_group=True,
                    tag="filter_criteria",
                    children=children,
                )
            )

        return PluginMetadata(
            name=title,
            display_name=None,
            version="",
            desc=f"共 {len(data)} 种过滤条件",
            nodes=nodes,
        )

    def _format_flags(self, value: Any, enum_cls: type[Enum]) -> str:
        """把位标志枚举格式化为 `A | B` 字符串 (ALL → "ALL", 空 → "None")

        `member in value` 依赖 3.11+ 的 Flag 包含语义, 这里按位判定;
        非整型值 (旧版/自定义过滤器可能存集合) 回退到成员判断。
        """
        if value is None:
            return "None"
        all_flag = getattr(enum_cls, "ALL", None)
        if all_flag is not None and value == all_flag:
            return "ALL"

        raw_mask = getattr(value, "value", value)
        members: list[str] = []
        for member in enum_cls:
            if member.name == "ALL":
                continue
            member_value = getattr(member, "value", None)
            if isinstance(raw_mask, int) and isinstance(member_value, int):
                if member_value & raw_mask:
                    members.append(member.name)
            elif isinstance(value, (set, frozenset)) and member in value:
                # 仅集合型兜底: 其它非整型值不做 in 判断 (会 TypeError), 宁可显示 None
                members.append(member.name)

        if not members:
            return "None"
        return " | ".join(members)

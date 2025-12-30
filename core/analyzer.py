import json
import time
import math
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Optional, Set, Any

from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata, EventType
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterTypeFilter, PlatformAdapterType
from astrbot.core.star.filter.event_message_type import EventMessageTypeFilter, EventMessageType
from astrbot.core.agent.mcp_client import MCPTool

from ..domain import PluginMetadata, RenderNode

class BaseAnalyzer:
    """分析器基类：处理通用的数据排版、分流与 JSON 生成"""
    IGNORED_PLUGINS = {
        "astrbot", 
        "astrbot-web-searcher", 
        "astrbot-python-interpreter",
        "session_controller",
        "builtin_commands",
        "astrbot-reminder", 
        "astrbot_plugin_help_typst"
    }

    # event巨型块阈值 (单位: pt)
    GIANT_THRESHOLD = 1500 # 已知悉魔术数字问题，日后会把此类提取到专门的 constants.py

    def __init__(self, context: Context):
        self.context = context

    def generate_render_data(self, save_path: Path, title: str = "AstrBot 功能菜单", mode: str = "command", query: str = None) -> int:
        """
        主入口
        :param mode: "command" | "event"
        :param query: 搜索关键词
        :return: 匹配到的插件数量
        """
        try:
            logger.info(f"[HelpTypst] 开始分析: {title} (Mode: {mode}, Query: {query})")
            structured_plugins = self.analyze_hierarchy()

            # === 搜索过滤逻辑 ===
            if query:
                q_lower = query.lower()
                filtered_plugins = []

                for p in structured_plugins:
                    # 检查插件(容器)本身是否匹配: 在Command模式下，p是插件；在Event/Filter模式下，p是分类组(如 OnMessage)
                    is_container_match = self._is_match(p.name, p.display_name, p.desc, q_lower)

                    if is_container_match:
                        # 容器匹配 -> 保留整个容器及其所有内容
                        filtered_plugins.append(p)
                    else:
                        # 容器不匹配 -> 深入内部进行剪枝(过滤 nodes 列表，只保留匹配的子节点)
                        matched_nodes = self._filter_nodes_recursively(p.nodes, q_lower)

                        if matched_nodes:
                            # 保留有剩余节点的容器
                            p.nodes = matched_nodes
                            filtered_plugins.append(p)

                structured_plugins = filtered_plugins
                title = f"搜索结果: \"{query}\""

            # 列表为空
            if not structured_plugins:
                return 0

            # 将 mode 传递给排版函数，决定分流策略
            self._generate_balanced_render_json(structured_plugins, save_path, title, mode)
            return len(structured_plugins)

        except Exception as e:
            logger.error(f"[HelpTypst] 分析失败: {e}", exc_info=True)
            return 0

    def _is_match(self, name: str, display: Optional[str], desc: str, query: str) -> bool:
        """基础匹配检查"""
        if query in name.lower(): return True
        if display and query in display.lower(): return True
        if desc and query in desc.lower(): return True
        return False

    def _filter_nodes_recursively(self, nodes: List[RenderNode], query: str) -> List[RenderNode]:
        """递归过滤节点树，返回一个新的包含匹配的节点的节点列表"""
        result = []
        for node in nodes:
            # 1. 检查自身匹配
            self_match = self._is_match(node.name, None, node.desc, query)

            # 2. 递归检查子节点
            if self_match:
                # 若节点本身匹配，保留上下文
                result.append(node)
            else:
                # 节点本身不匹配，检查子节点
                if node.children:
                    filtered_children = self._filter_nodes_recursively(node.children, query)
                    if filtered_children:
                        # 有子节点存活时，保留过滤后的当前节点
                        node.children = filtered_children
                        result.append(node)
                else:
                    # 没匹配 -> 丢弃
                    pass
                    
        return result

    def analyze_hierarchy(self) -> List[PluginMetadata]:
        raise NotImplementedError

    def _generate_balanced_render_json(self, structured_plugins: List[PluginMetadata], save_path: Path, title: str, mode: str):
        # 1. 辅助：获取节点列表
        def get_nodes(plugin: PluginMetadata) -> List[RenderNode]:
            if hasattr(plugin, "nodes") and plugin.nodes: return plugin.nodes
            if hasattr(plugin, "command_nodes") and plugin.command_nodes: return plugin.command_nodes
            return []

        # 2. 辅助：标准视图下的高度估算
        def estimate_height(nodes: List[RenderNode]) -> int:
            total_h = 0
            # 模拟 Typst 的分类逻辑
            complex_nodes = [n for n in nodes if n.is_group or n.desc != ""]
            simple_nodes = [n for n in nodes if not n.is_group and n.desc == ""]

            # 复杂节点：垂直堆叠
            for node in complex_nodes:
                if node.is_group:
                    total_h += 60 + estimate_height(node.children)
                else:
                    total_h += 60 

            # 简单节点：3列网格
            if simple_nodes:
                rows = math.ceil(len(simple_nodes) / 3)
                total_h += rows * 30 + 10

            return total_h

        # 3. 数据分流
        giants = []
        complex_plugins = []
        single_node_plugins = []

        extract_singles = (mode == "command")

        for p in structured_plugins:
            nodes = get_nodes(p)

            # --- A: 工具调用 (Tool) 总是进入 Singles ---
            is_tool = len(nodes) > 0 and (nodes[0].tag == "tool" or nodes[0].tag == "mcp")
            if is_tool:
                single_node_plugins.append(p.model_dump())
                continue

            # --- B: 单指令插件 (仅 Command 模式) ---
            if extract_singles and len(nodes) == 1 and not nodes[0].is_group:
                single_node_plugins.append(p.model_dump())
                continue

            # --- C: 巨型块判定 (仅 Event、Filter 模式) ---
            h_val = estimate_height(nodes)
            if mode in ("event", "filter") and h_val > self.GIANT_THRESHOLD:
                giants.append(p.model_dump())
                continue

            # --- D: 默认瀑布流 ---
            complex_plugins.append(p)

        # 4. 瀑布流排版
        plugins_with_height = [
            (p, estimate_height(get_nodes(p)) + 80)
            for p in complex_plugins
        ]
        sorted_plugins = sorted(plugins_with_height, key=lambda x: x[1], reverse=True)

        cols_data = [[] for _ in range(3)]
        col_heights = [0] * 3

        for plugin, height in sorted_plugins:
            idx = col_heights.index(min(col_heights))
            cols_data[idx].append(plugin.model_dump())
            col_heights[idx] += height

        # 5. 生成 JSON
        final_render_data = {
            "title": title,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "plugin_count": len(structured_plugins),
            "giants": giants,
            "columns": cols_data, 
            "singles": single_node_plugins 
        }

        save_path.write_text(
            json.dumps(final_render_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"[HelpTypst] 数据生成完毕. Mode: {mode}, Giants: {len(giants)}, Singles: {len(single_node_plugins)}")

    def _group_handlers_by_module(self) -> Dict[str, List[StarHandlerMetadata]]:
        mapping = defaultdict(list)
        for handler in star_handlers_registry:
            if isinstance(handler, StarHandlerMetadata) and handler.handler_module_path:
                mapping[handler.handler_module_path].append(handler)
        return mapping


class CommandAnalyzer(BaseAnalyzer):
    """指令分析器：处理 CommandFilter / CommandGroupFilter"""
    def analyze_hierarchy(self) -> List[PluginMetadata]:
        handlers_map = self._group_handlers_by_module()
        results = []
        all_stars = self.context.get_all_stars()

        for star_meta in all_stars:
            if not star_meta.activated: continue
            plugin_name = getattr(star_meta, "name", "unknown")
            if plugin_name in self.IGNORED_PLUGINS: continue
            module_path = getattr(star_meta, "module_path", None)
            if not module_path: continue

            handlers = handlers_map.get(module_path, [])
            if not handlers: continue

            nodes = self._build_plugin_command_tree(handlers)
            if nodes:
                results.append(PluginMetadata(
                    name=plugin_name,
                    display_name=getattr(star_meta, "display_name", None),
                    version=getattr(star_meta, "version", None),
                    desc=getattr(star_meta, "desc", "") or "",
                    nodes=nodes
                ))

        results.sort(key=lambda x: (x.display_name is None, x.name))
        return results

    def _build_plugin_command_tree(self, handlers: List[StarHandlerMetadata]) -> List[RenderNode]:
        nodes = []
        # 黑名单扫描：防止子组重复出现在顶层
        child_handlers_blacklist = self._scan_all_children(handlers)

        # 1. 顶级组
        for handler in handlers:
            if handler.handler_name in child_handlers_blacklist: continue
            group_filter = self._get_filter(handler, CommandGroupFilter)
            if group_filter:
                nodes.append(self._parse_group(handler, group_filter))

        # 2. 独立指令
        for handler in handlers:
            if handler.handler_name in child_handlers_blacklist: continue
            if self._get_filter(handler, CommandGroupFilter): continue
            cmd_filter = self._get_filter(handler, CommandFilter)
            if cmd_filter:
                nodes.append(self._parse_command_node(handler, cmd_filter))

        self._sort_nodes(nodes)
        return nodes

    def _scan_all_children(self, handlers: List[StarHandlerMetadata]) -> Set[str]:
        blacklist = set()
        groups_map = {}
        for h in handlers:
            gf = self._get_filter(h, CommandGroupFilter)
            if gf: groups_map[gf.group_name] = h.handler_name

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

    def _parse_group(self, handler: StarHandlerMetadata, group_filter: CommandGroupFilter) -> RenderNode:
        desc = (handler.desc or "").split('\n')[0].strip()
        children = []
        for sub_filter in group_filter.sub_command_filters:
            child = self._process_sub_filter(sub_filter)
            if child: children.append(child)

        self._sort_nodes(children)
        return RenderNode(
            name=group_filter.group_name,
            desc=desc or "指令组",
            is_group=True,
            tag=self._check_permission(handler),
            children=children
        )

    def _process_sub_filter(self, filter_obj: Any) -> Optional[RenderNode]:
        handler = getattr(filter_obj, "handler_md", None)
        desc = self._get_desc_safely(handler)
        tag = self._check_permission(handler) if handler else "normal"

        if isinstance(filter_obj, CommandFilter):
            return RenderNode(name=filter_obj.command_name, desc=desc, is_group=False, tag=tag)

        elif isinstance(filter_obj, CommandGroupFilter):
            children = []
            if hasattr(filter_obj, "sub_command_filters"):
                for sf in filter_obj.sub_command_filters:
                    child = self._process_sub_filter(sf)
                    if child: children.append(child)
            self._sort_nodes(children)
            return RenderNode(name=filter_obj.group_name, desc=desc or "子指令组", is_group=True, tag=tag, children=children)
        return None

    def _parse_command_node(self, handler: StarHandlerMetadata, cmd_filter: CommandFilter) -> RenderNode:
        desc = (handler.desc or "").split('\n')[0].strip()
        return RenderNode(
            name=cmd_filter.command_name,
            desc=desc,
            is_group=False,
            tag=self._check_permission(handler)
        )

    def _sort_nodes(self, nodes: List[RenderNode]):
        nodes.sort(key=lambda x: (x.is_group, x.name))

    def _check_permission(self, handler: Any) -> str:
        if not handler or not hasattr(handler, "event_filters"): return "normal"
        for f in handler.event_filters:
            if isinstance(f, PermissionTypeFilter): return "admin"
        return "normal"

    def _get_filter(self, handler: StarHandlerMetadata, filter_type):
        if not hasattr(handler, "event_filters"): return None
        for f in handler.event_filters:
            if isinstance(f, filter_type): return f
        return None

    def _get_desc_safely(self, handler: Any) -> str:
        if not handler: return ""
        raw = getattr(handler, "desc", "") or ""
        return raw.split('\n')[0].strip()


class EventAnalyzer(BaseAnalyzer):
    """事件分析器：处理所有 EventType，获取完整工具列表（含 MCP）"""
    EVENT_TYPE_MAP = {
        EventType.OnAstrBotLoadedEvent: "系统启动 (Loaded)",
        EventType.OnPlatformLoadedEvent: "平台就绪 (Platform)",
        EventType.AdapterMessageEvent: "消息监听 (Message)",
        EventType.OnLLMRequestEvent: "LLM 请求前 (Pre-LLM)",
        EventType.OnLLMResponseEvent: "LLM 响应后 (Post-LLM)",
        EventType.OnDecoratingResultEvent: "消息修饰 (Decorate)",
        EventType.OnAfterMessageSentEvent: "发送回执 (Sent)",
    }

    def analyze_hierarchy(self) -> List[PluginMetadata]:
        results = []

        # 1. 映射模块路径到插件对象
        module_to_plugin = {}
        all_stars = self.context.get_all_stars()
        for star in all_stars:
            if star.module_path:
                module_to_plugin[star.module_path] = star


        # --- A.处理函数工具 (Plugin Tools + MCP Tools) --- 
        # 获取工具列表
        tool_manager = None
        if hasattr(self.context, "get_llm_tool_manager"):
            tool_manager = self.context.get_llm_tool_manager()
        
        if tool_manager:
            for tool in tool_manager.func_list:
                if not tool.active:
                    continue

                source_name = "Unknown"
                source_display = None
                source_version = "" # 默认为空，MCP 无版本号
                tag = "tool"

                # >>> 来源: MCP <<<
                if MCPTool and isinstance(tool, MCPTool):
                    source_name = f"MCP/{tool.mcp_server_name}"
                    source_display = f"🔌 {tool.mcp_server_name}" 
                    tag = "mcp"
                elif tool.handler_module_path:
                    # >>> 来源: 插件 <<<
                    plugin = module_to_plugin.get(tool.handler_module_path)
                    if plugin:
                        if plugin.name in self.IGNORED_PLUGINS: continue
                        source_name = plugin.name
                        source_display = getattr(plugin, "display_name", None)
                        source_version = getattr(plugin, "version", "") 
                    else:
                        source_name = "Core/Unknown"

                desc = (tool.description or "").split('\n')[0].strip()

                node = RenderNode(
                    name=tool.name,
                    desc=desc,
                    is_group=False,
                    tag=tag 
                )

                # 包装为 PluginMetadata
                pm = PluginMetadata(
                    name=source_name, 
                    display_name=source_display,
                    version=source_version, 
                    desc="",
                    nodes=[node]
                )
                results.append(pm)

        # --- B.处理普通事件 (排除 OnCallingFuncToolEvent)  --- 
        event_groups = defaultdict(list)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata): continue

            if self._is_command_handler(handler): continue
            if handler.event_type == EventType.OnCallingFuncToolEvent: continue

            if handler.handler_module_path in module_to_plugin:
                plugin = module_to_plugin[handler.handler_module_path]
                if plugin.name in self.IGNORED_PLUGINS: continue
                if not plugin.activated: continue
            else:
                continue

            event_groups[handler.event_type].append(handler)

        for evt_type, handlers in event_groups.items():
            card_title = self.EVENT_TYPE_MAP.get(evt_type, str(evt_type.name))

            nodes = []
            for h in handlers:
                plugin = module_to_plugin.get(h.handler_module_path)
                p_name = plugin.name if plugin else "System"
                p_display = getattr(plugin, "display_name", None) if plugin else None

                main_name = p_display if p_display else p_name
                raw_desc = (h.desc or "").split('\n')[0].strip()
                if not raw_desc and h.handler.__doc__:
                    raw_desc = h.handler.__doc__.split('\n')[0].strip()

                full_desc = ""
                if p_display:
                    full_desc = f"@{p_name}"

                if raw_desc:
                    if full_desc:
                        full_desc += f" · {raw_desc}"
                    else:
                        full_desc = raw_desc

                prio = h.extras_configs.get("priority", 0)
                nodes.append(RenderNode(
                    name=main_name,
                    desc=full_desc,
                    is_group=False,
                    tag="event_listener",
                    priority=prio
                ))

            nodes.sort(key=lambda x: x.name)
            nodes.sort(key=lambda x: x.priority if x.priority is not None else 0, reverse=True)

            pm = PluginMetadata(
                name="event_group", 
                display_name=card_title, 
                version="", 
                desc=f"共 {len(nodes)} 个挂载点",
                nodes=nodes
            )
            results.append(pm)

        return results

    def _is_command_handler(self, handler: StarHandlerMetadata) -> bool:
        if not handler.event_filters: return False
        for f in handler.event_filters:
            if isinstance(f, (CommandFilter, CommandGroupFilter)): return True
        return False


class FilterAnalyzer(BaseAnalyzer):
    """过滤器分析器"""
    def analyze_hierarchy(self) -> List[PluginMetadata]:
        results = []
        module_to_plugin = {}
        all_stars = self.context.get_all_stars()
        for star in all_stars:
            if star.module_path:
                module_to_plugin[star.module_path] = star

        # 数据容器
        regex_data = defaultdict(list)
        platform_data = defaultdict(list)
        msgtype_data = defaultdict(list)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata): continue

            if handler.handler_module_path in module_to_plugin:
                plugin = module_to_plugin[handler.handler_module_path]
                if plugin.name in self.IGNORED_PLUGINS: continue
                if not plugin.activated: continue
            else:
                continue

            if not handler.event_filters: continue

            for f in handler.event_filters:
                if isinstance(f, RegexFilter):
                    regex_data[handler.handler_module_path].append((f.regex_str, handler))
                elif isinstance(f, PlatformAdapterTypeFilter):
                    names = self._format_flags(f.platform_type, PlatformAdapterType)
                    key = f"🌍 {names}"
                    platform_data[key].append(handler)
                elif isinstance(f, EventMessageTypeFilter):
                    names = self._format_flags(f.event_message_type, EventMessageType)
                    key = f"📨 {names}"
                    msgtype_data[key].append(handler)

        # --- 1. 构建 Regex 卡片 --- 
        if regex_data:
            nodes = []
            for mod_path, items in regex_data.items():
                plugin = module_to_plugin.get(mod_path)
                p_name = plugin.name if plugin else "Unknown"
                p_display = getattr(plugin, "display_name", None)
                
                sorted_items = sorted(items, key=lambda x: x[0])
                
                children = []
                for r_str, h in sorted_items:
                    raw_desc = (h.desc or "").split('\n')[0].strip()
                    if not raw_desc and h.handler.__doc__:
                        raw_desc = h.handler.__doc__.split('\n')[0].strip()
                    
                    # 正则的子项描述：#{函数名} · {描述}
                    full_desc = f"#{h.handler_name}"
                    if raw_desc:
                        full_desc += f" · {raw_desc}"

                    children.append(RenderNode(
                        name=r_str, 
                        desc=full_desc, 
                        is_group=False, 
                        tag="regex_pattern"
                    ))
                
                # [Fix] 父节点描述逻辑
                # 如果有中文名，描述显示 @英文ID
                # 如果没中文名，描述置空（因为标题已经是英文ID了）
                container_desc = f"@{p_name}" if p_display else ""
                
                nodes.append(RenderNode(
                    name=p_display if p_display else p_name,
                    desc=container_desc,
                    is_group=True,
                    tag="plugin_container",
                    children=children
                ))
            
            nodes.sort(key=lambda x: x.name)
            
            results.append(PluginMetadata(
                name="filter_regex", display_name="正则触发器 (Regex)",
                version="", desc=f"共 {len(nodes)} 个插件使用了正则", nodes=nodes
            ))

        # --- 2. 构建 Platform 卡片  --- 
        if platform_data:
            results.append(self._build_criteria_card(
                "平台限制 (Platform)", "platform", platform_data, module_to_plugin
            ))

        # --- 3. 构建 MsgType 卡片 --- 
        if msgtype_data:
            results.append(self._build_criteria_card(
                "消息类型限制 (MsgType)", "msg_type", msgtype_data, module_to_plugin
            ))

        return results

    def _build_criteria_card(self, title: str, tag_prefix: str, data: Dict[str, List[StarHandlerMetadata]], module_to_plugin: dict) -> PluginMetadata:
        nodes = []
        sorted_keys = sorted(data.keys())

        for filter_str in sorted_keys:
            handlers = data[filter_str]
            children = []

            for h in handlers:
                plugin = module_to_plugin.get(h.handler_module_path)
                p_name = plugin.name if plugin else "Unknown"
                p_display = getattr(plugin, "display_name", None)

                main_name = p_display if p_display else p_name

                raw_desc = (h.desc or "").split('\n')[0].strip()
                if not raw_desc and h.handler.__doc__:
                    raw_desc = h.handler.__doc__.split('\n')[0].strip()

                parts = []

                # 1. 当 display_name 作为标题时，才在描述里补充 @name
                if p_display:
                    parts.append(f"@{p_name}")

                # 2. 函数名
                parts.append(f"#{h.handler_name}")

                # 3. 原始描述
                if raw_desc:
                    parts.append(raw_desc)

                full_desc = " · ".join(parts)
                prio = h.extras_configs.get("priority", 0)
                children.append(RenderNode(
                    name=main_name, 
                    desc=full_desc, 
                    is_group=False, 
                    tag="event_listener",
                    priority=prio
                ))

            children.sort(key=lambda x: x.name)
            children.sort(key=lambda x: x.priority if x.priority is not None else 0, reverse=True)

            nodes.append(RenderNode(
                name=filter_str, 
                desc=f"{len(children)} 个监听点",
                is_group=True, 
                tag="filter_criteria", 
                children=children
            ))

        return PluginMetadata(
            name=f"filter_{tag_prefix}", display_name=title,
            version="", desc=f"共 {len(data)} 种过滤条件", nodes=nodes
        )

    def _format_flags(self, value, enum_cls):
        if value is None: return "None"
        if hasattr(enum_cls, "ALL") and value == enum_cls.ALL: return "ALL"

        members = []
        for member in enum_cls:
            if member.name == "ALL": continue
            if member in value:
                formatted_name = member.name
                members.append(formatted_name)

        if not members: return "None"
        return " | ".join(members)
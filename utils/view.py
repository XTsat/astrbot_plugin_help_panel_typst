import asyncio
import json
import math
import os
import unicodedata
from pathlib import Path
from typing import Any, TypedDict

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

from ..domain import (
    InternalCFG,
    PluginMetadata,
    RenderNode,
    TypstPluginConfig,
    is_dark_hex,
)


class HelpHint:
    """提供用户提示文本"""

    def msg_searching(self, query: str) -> str:
        return f"正在搜索 '{query}'..."

    def msg_rendering(self, mode: str) -> str:
        return "正在渲染..." if mode == "command" else "正在获取列表..."

    def msg_empty_result(self, mode: str, query: str | None) -> str:
        target = "事件监听器" if mode == "event" else "插件或指令"
        if query:
            return f"未找到包含 '{query}' 的{target}。"
        return f"当前没有可显示的{target}。"


class MsgRecall:
    """负责发送提示消息, 并在完成后撤回"""

    async def send_wait(self, event: AstrMessageEvent, text: str) -> int | str | None:
        """发送提示并返回消息ID"""
        bot = getattr(event, "bot", None)
        payload = event.plain_result(text)

        # OneBot API
        if bot and hasattr(event, "_parse_onebot_json") and hasattr(bot, "call_action"):
            try:
                chain = payload.chain if hasattr(payload, "chain") else payload
                if not isinstance(chain, list):
                    chain = [chain]

                # 构建 OneBot 消息体
                msg_chain = MessageChain(chain=chain)
                obmsg = await event._parse_onebot_json(msg_chain)

                params = {"message": obmsg}
                # 确定发送目标
                if gid := event.get_group_id():
                    params["group_id"] = int(gid)
                    action = "send_group_msg"
                elif uid := event.get_sender_id():
                    params["user_id"] = int(uid)
                    action = "send_private_msg"
                else:
                    raise ValueError("无法确定发送目标")

                resp = await bot.call_action(action, **params)
                return self._extract_message_id(resp)

            except Exception as e:
                logger.debug(f"[HelpTypst] OneBot 发送尝试失败，回退通用接口: {e}")

        # 兜底: 通用接口
        try:
            resp = await event.send(payload)
            return self._extract_message_id(resp)
        except Exception as e:
            logger.error(f"[HelpTypst] 发送等待消息失败: {e}")
            return None

    async def recall(self, event: AstrMessageEvent, message_id: int | str | None):
        """撤回指定消息"""
        if not message_id:
            return
        bot = getattr(event, "bot", None)
        if not bot:
            logger.debug("[HelpTypst] 无法获取 Bot 实例，撤回可能失效")
            return

        # 稍等避免闪撤
        await asyncio.sleep(InternalCFG.DELAY_SEND)

        try:
            # delete_msg
            if hasattr(bot, "delete_msg"):
                await bot.delete_msg(message_id=message_id)
            # recall_message
            elif hasattr(bot, "recall_message"):
                try:
                    await bot.recall_message(int(message_id))
                except (ValueError, TypeError):
                    logger.debug(f"[HelpTypst] recall_message 不支持 ID: {message_id}")
            else:
                logger.debug("[HelpTypst] 未找到撤回方法")
        except Exception as e:
            logger.warning(f"[HelpTypst] 撤回消息 {message_id} 失败: {e}")

    def _extract_message_id(self, resp: Any) -> int | str | None:
        """提取 Message ID"""
        if not resp:
            return None

        # 直接是 ID
        if isinstance(resp, (int, str)):
            return resp

        # 字典结构
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, dict):
                if "message_id" in data:
                    return data["message_id"]
                if "res_id" in data:
                    return data["res_id"]
                if "forward_id" in data:
                    return data["forward_id"]

            # 外层字段
            if "message_id" in resp:
                return resp["message_id"]
            if "id" in resp:
                return resp["id"]
            return None

        # 对象属性(Telegram)
        if val := getattr(resp, "message_id", None):
            return val

        # 兜底
        if val := getattr(resp, "id", None):
            return val

        return None


class TypstLayout:
    """负责将结构化数据转换为 Typst 渲染所需的布局 JSON"""

    def __init__(self, config: TypstPluginConfig):
        self.cfg = config

    def dump_layout_json(
        self,
        plugins: list[PluginMetadata],
        save_path: Path,
        title: str,
        mode: str,
        prefixes: list[str],
        font_list: list[str],
        system_name: str = "",
    ) -> None:
        """生成布局数据并写入文件"""
        payload = self._generate_balanced_payload(
            plugins, title, mode, prefixes, font_list
        )
        # 注入颜色配置 (激活预设配色 + 禁用灰化色板: 深色主题需要另一套, 否则禁用行是白块)
        colors = dict(self.cfg.appearance.get_active_colors())
        colors.update(
            InternalCFG.DISABLED_COLORS_DARK
            if is_dark_hex(colors.get("brand_card", "#FFFFFF"))
            else InternalCFG.DISABLED_COLORS
        )
        payload["colors"] = colors
        # 注入 Hero 统计卡片第三列显示名 (人格名称, 空串则不渲染该列)
        payload["system_name"] = system_name
        # 页面总宽度 (pt): 模板据此设置 page 宽度, 越窄同 PPI 下出图越窄、文字相对越大
        payload["page_width"] = self.cfg.rendering.page_width
        # 卡片内部小块的列数: 页宽变窄时从三列降为两列, 否则文字会被压成竖条
        payload["content_columns"] = self._resolve_content_columns()
        # 插件行双行模式: 英文 ID 换到中文名下方, 单行更窄, 窄列宽下不易挤掉名称
        payload["plugin_two_lines"] = self.cfg.rendering.plugin_two_lines

        content = json.dumps(payload, ensure_ascii=False, indent=2)
        # 先写同目录临时文件再原子替换: 渲染子进程会并发读取该 JSON,
        # 直接覆盖可能让它读到半截内容
        tmp_path = save_path.with_name(f"{save_path.name}.tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, save_path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            logger.warning(f"[HelpTypst] 布局 JSON 写入失败: {exc}")
            raise

    def _resolve_column_count(self, mode: str) -> int:
        """按页面总宽度决定分栏数 (列宽随页宽等比收缩)

        - 页宽低于单列阈值: 一律单列, 否则每列会被压到放不下插件名/标签;
        - 事件/过滤器视图: 三列需要默认页宽 (830pt), 页宽变窄时先退回两列;
        - 指令类视图: 恒为两列 (单列已在上面处理)。
        """
        width = self.cfg.rendering.page_width
        if width < self.cfg.rendering.single_column_threshold:
            return 1
        if mode in ("event", "filter"):
            return 3 if width >= InternalCFG.DESIGN_PAGE_WIDTH else 2
        return 2

    def _resolve_content_columns(self) -> int:
        """卡片内部小块 (功能块/指令标签/独立工具) 的并排数

        三列是按默认设计页宽定的; 页宽变窄后卡片本身也变窄, 继续三列会把文字压成竖条。
        """
        width = self.cfg.rendering.page_width
        return 3 if width >= InternalCFG.DESIGN_PAGE_WIDTH else 2

    def _generate_balanced_payload(
        self,
        plugins: list[PluginMetadata],
        title: str,
        mode: str,
        prefixes: list[str],
        font_list: list[str],
    ) -> dict[str, Any]:
        """瀑布流分发逻辑"""
        # 插件详情页 (数字定位单个插件)
        if mode == "plugin_detail":
            return self._generate_plugin_detail_payload(
                plugins, title, prefixes, font_list
            )
        # 指令模式: 按分类分组, 渲染为分类卡片 (Zhenxun 风格)
        if mode == "command":
            return self._generate_command_payload(plugins, title, prefixes, font_list)
        # 详细指令模式: 分类卡片 + 每个插件下方展示指令标签组
        if mode == "command_detail":
            return self._generate_command_detail_payload(
                plugins, title, prefixes, font_list
            )

        giants = []
        complex_plugins = []
        single_node_plugins = []

        # 辅助函数：获取节点列表
        def get_nodes(p: PluginMetadata) -> list[RenderNode]:
            if hasattr(p, "nodes") and p.nodes:
                return p.nodes
            if hasattr(p, "command_nodes") and p.command_nodes:
                return p.command_nodes
            return []

        # 1. 预分类
        for p in plugins:
            nodes = get_nodes(p)

            # A: 工具调用 -> Singles
            is_tool = len(nodes) > 0 and (
                nodes[0].tag == "tool" or nodes[0].tag == "mcp"
            )
            if is_tool:
                single_node_plugins.append(p.model_dump())
                continue

            # C: 巨型块 -> Giants (Event/Filter 模式)
            h_val = self._estimate_height(nodes)
            if (
                mode in ("event", "filter")
                and h_val > self.cfg.rendering.giant_threshold
            ):
                giants.append(p.model_dump())
                continue

            # D: 其余 -> 瀑布流
            complex_plugins.append(p)

        # 2. 瀑布流平衡算法
        # 计算高度权重 (+80 是对卡片头部和Padding的估算)
        plugins_with_height = [
            (p, self._estimate_height(get_nodes(p)) + 80) for p in complex_plugins
        ]
        # 降序排列 (贪心算法基础)
        sorted_plugins = sorted(plugins_with_height, key=lambda x: x[1], reverse=True)

        n_cols = self._resolve_column_count(mode)
        cols_data: list[list[dict[str, Any]]] = [[] for _ in range(n_cols)]
        col_heights = [0] * n_cols

        for plugin, height in sorted_plugins:
            # 放入当前高度最小的列
            idx = col_heights.index(min(col_heights))
            cols_data[idx].append(plugin.model_dump())
            col_heights[idx] += height

        return {
            "title": title,
            "mode": mode,
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "giants": giants,
            "columns": cols_data,
            "singles": single_node_plugins,
        }

    def _generate_command_payload(
        self,
        plugins: list[PluginMetadata],
        title: str,
        prefixes: list[str],
        font_list: list[str],
    ) -> dict[str, Any]:
        """指令模式: 按分类分组为卡片, 并均衡分配到多列 (窄页宽时单列)"""
        categories = self._group_by_category(plugins)
        cols = self._balance_categories(
            categories, columns=self._resolve_column_count("command")
        )

        return {
            "title": title,
            "mode": "command",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "enabled_count": sum(1 for p in plugins if not p.disabled),
            "category_columns": cols,
        }

    def _generate_command_detail_payload(
        self,
        plugins: list[PluginMetadata],
        title: str,
        prefixes: list[str],
        font_list: list[str],
    ) -> dict[str, Any]:
        """详细指令模式: 分类卡片 + 每个插件展示能力树 (指令/指令组/监听器)"""
        categories = self._group_by_category_detail(plugins)
        cols = self._balance_categories(
            categories,
            detail=True,
            columns=self._resolve_column_count("command_detail"),
        )

        return {
            "title": title,
            "mode": "command_detail",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "enabled_count": sum(1 for p in plugins if not p.disabled),
            "category_columns": cols,
        }

    def _build_plugin_capabilities(
        self, plugin: PluginMetadata
    ) -> dict[str, Any]:
        """构建插件能力树。

        参数占位已并入 chip 显示名, 模板只消费指令名/别名与分组名, 因此不再单独输出。
        返回:
          {
            "commands": [{"name", "aliases"}],          # 顶层独立指令
            "groups": [{"name", "commands": [...]}],    # 指令组
            "listeners": [str, ...]                     # 监听器提取的指令关键词
          }
        """
        commands: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        for node in plugin.nodes:
            if node.is_group:
                # 指令组: 递归收集所有子指令
                group_cmds = self._collect_group_commands(
                    node.children, prefix=""
                )
                if group_cmds:
                    groups.append(
                        {
                            "name": node.name,
                            "commands": group_cmds,
                        }
                    )
            else:
                # 顶层独立指令
                params = node.params or ""
                chip_name = f"{node.name} {params}".strip() if params else node.name
                commands.append(
                    {
                        "name": chip_name,
                        "aliases": list(node.aliases or []),
                    }
                )

        # 监听器: 只提取指令关键词 (来自事件监听器 desc 中的命令列表)
        listeners: list[str] = []
        for en in plugin.event_nodes:
            for cmd in list(en.commands or []):
                if cmd not in listeners:
                    listeners.append(cmd)

        # 排除空字段
        result: dict[str, Any] = {}
        if commands:
            result["commands"] = commands
        if groups:
            result["groups"] = groups
        if listeners:
            result["listeners"] = listeners
        return result

    def _collect_group_commands(
        self, nodes: list[RenderNode], prefix: str = ""
    ) -> list[dict[str, Any]]:
        """递归收集指令组内的所有子指令 (扁平列表, 不含嵌套组)。"""
        cmds: list[dict[str, Any]] = []
        for node in nodes:
            if node.is_group:
                # 嵌套组: 递归, 用组名作为前缀
                child_prefix = f"{prefix} {node.name}".strip() if prefix else node.name
                cmds.extend(self._collect_group_commands(node.children, child_prefix))
            else:
                full_name = f"{prefix} {node.name}".strip() if prefix else node.name
                params = node.params or ""
                chip_name = f"{full_name} {params}".strip() if params else full_name
                cmds.append(
                    {
                        "name": chip_name,
                        "aliases": list(node.aliases or []),
                    }
                )
        return cmds

    def _category_color(self, name: str) -> str:
        """解析分类卡片主题色 (统一走主题色槽, 降级链):

        1. 规则内固定色 (#RRGGBB, 不随主题变化)
        2. 规则内主题色槽绑定 (slot_N → 主题 cat_slot_N, 随主题切换自动变化)
        3. 兜底分类 (名称等于 category.fallback): 使用兜底分类颜色 (fallback_color)
        4. 自动分配: 未配置颜色的规则按列表顺序循环取主题色槽 (随主题切换)
        5. 灰蓝 #808E9D
        """
        rule = self.cfg.category.get_rule(name)

        # 1. 固定色覆盖
        if rule and rule.color.startswith("#"):
            return rule.color

        # 2. 主题色槽绑定 (无效/越界 → 继续降级, 最终灰蓝)
        if rule and rule.color.startswith("slot_"):
            idx_str = rule.color[5:]
            if idx_str.isdigit():
                slots = self.cfg.appearance.get_category_slots()
                n = int(idx_str)
                if 0 <= n < len(slots):
                    return slots[n]

        # 3. 兜底分类: 使用兜底分类颜色
        if name in (self.cfg.category.fallback, InternalCFG.CATEGORY_FALLBACK):
            return self._fallback_color()

        # 4. 自动分配主题色槽 (仅未配置颜色的规则)
        auto = self._auto_category_slot(name)
        if auto:
            return auto

        # 5. 灰蓝兜底
        return "#808E9D"

    def _fallback_color(self) -> str:
        """兜底分类卡片颜色: 优先 category.fallback_color (hex 固定 / slot_N 随主题), 空串灰蓝"""
        fc = self.cfg.category.fallback_color
        if fc.startswith("#"):
            return fc
        if fc.startswith("slot_"):
            idx_str = fc[5:]
            if idx_str.isdigit():
                slots = self.cfg.appearance.get_category_slots()
                n = int(idx_str)
                if 0 <= n < len(slots):
                    return slots[n]
        return "#808E9D"

    def _auto_category_slot(self, name: str) -> str:
        """自动分配主题色槽: 按规则列表顺序, 仅计「未配置颜色且非兜底分类」的启用规则

        主题色槽随激活预设切换变化, 分类因此能自动跟随主题换色。
        """
        slots = self.cfg.appearance.get_category_slots()
        if not slots:
            return ""
        fallback = self.cfg.category.fallback

        order_idx = 0
        for rule in self.cfg.category.rules:
            if not rule.enabled:
                continue  # 停用规则不参与
            if rule.color:
                continue  # 固定色/槽位绑定不占自动序号
            if rule.name in (fallback, InternalCFG.CATEGORY_FALLBACK):
                continue  # 兜底分类不占自动序号 (使用兜底分类颜色)
            if rule.name == name:
                return slots[order_idx % len(slots)]
            order_idx += 1
        return ""

    def _group_by_category_detail(
        self, plugins: list[PluginMetadata]
    ) -> list[dict[str, Any]]:
        """将插件按分类聚合, 输出分类卡片数据, 每个插件附带能力树信息。"""
        fallback = self.cfg.category.fallback

        grouped: dict[str, list[PluginMetadata]] = {}
        for p in plugins:
            cat = (p.category or "").strip() or fallback
            grouped.setdefault(cat, []).append(p)

        # 分类排序: 名称升序, 兜底分类置底
        names = sorted(grouped.keys())
        if fallback in names:
            names.remove(fallback)
            names.append(fallback)

        categories = []
        for name in names:
            plist = sorted(grouped[name], key=lambda x: x.order)
            theme_color = self._category_color(name)
            categories.append(
                {
                    "name": name,
                    "count": len(plist),
                    "color": theme_color,
                    "plugins": [
                        {
                            "id": p.order,
                            "name": p.name,
                            "display_name": p.display_name,
                            "version": p.version,
                            "disabled": p.disabled,
                            "desc": p.desc,
                            "capabilities": self._build_plugin_capabilities(p),
                        }
                        for p in plist
                    ],
                }
            )
        return categories

    def _generate_plugin_detail_payload(
        self,
        plugins: list[PluginMetadata],
        title: str,
        prefixes: list[str],
        font_list: list[str],
    ) -> dict[str, Any]:
        """插件详情页: 单插件完整信息 (标题/作者/版本/简介/指令)"""
        p = plugins[0] if plugins else None
        if not p:
            return {
                "title": title,
                "mode": "plugin_detail",
                "prefixes": prefixes,
                "fonts": font_list,
            }

        # 扁平化指令树 → 管理员指令 / 普通指令
        admin_commands, normal_commands = self._flatten_commands(p.nodes)

        # 插件分类主题色 (与 /helps 分类卡片一致, 供详情页标题着色)
        cat = (p.category or "").strip() or self.cfg.category.fallback
        category_color = self._category_color(cat)

        return {
            "title": title,
            "mode": "plugin_detail",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin": {
                "name": p.name,
                "display_name": p.display_name or p.name,
                "version": p.version,
                "desc": p.desc,
                "author": p.author,
                "order": p.order,
                "category_color": category_color,
            },
            "admin_commands": admin_commands,
            "normal_commands": normal_commands,
            "event_listeners": self._build_event_listener_payload(p.event_nodes),
        }

    def _build_event_listener_payload(
        self, event_nodes: list[RenderNode]
    ) -> list[dict[str, Any]]:
        """构建插件详情页的事件监听器列表"""
        return [
            {
                "name": node.name,
                "desc": node.desc or "",
                "priority": node.priority,
                "commands": list(node.commands or []),
            }
            for node in event_nodes
        ]

    def _flatten_commands(
        self, nodes: list[RenderNode], prefix: str = "", parent_admin: bool = False
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """递归展平指令树, 按权限拆分为管理员/普通指令列表"""
        admin: list[dict[str, str]] = []
        normal: list[dict[str, str]] = []

        for node in nodes:
            full_name = f"{prefix} {node.name}".strip() if prefix else node.name
            is_admin = parent_admin or node.tag == "admin"

            if node.is_group:
                # 分组容器: 递归子节点, 权限继承
                sub_admin, sub_normal = self._flatten_commands(
                    node.children, full_name, is_admin
                )
                admin.extend(sub_admin)
                normal.extend(sub_normal)
            else:
                item = {"name": full_name, "desc": node.desc or ""}
                if is_admin:
                    admin.append(item)
                else:
                    normal.append(item)

        return admin, normal

    def _group_by_category(self, plugins: list[PluginMetadata]) -> list[dict[str, Any]]:
        """将插件按分类聚合, 输出分类卡片数据 (含主题色与全局序号徽章)"""
        fallback = self.cfg.category.fallback

        grouped: dict[str, list[PluginMetadata]] = {}
        for p in plugins:
            cat = (p.category or "").strip() or fallback
            grouped.setdefault(cat, []).append(p)

        # 分类排序: 名称升序, 兜底分类置底
        names = sorted(grouped.keys())
        if fallback in names:
            names.remove(fallback)
            names.append(fallback)

        categories = []
        for name in names:
            # 插件按全局编号排序, 保持与全量列表一致的展示顺序
            plist = sorted(grouped[name], key=lambda x: x.order)
            # 分类色解析: 规则自带颜色 → 激活预设 cat_* 色板 → 灰蓝兜底
            theme_color = self._category_color(name)
            categories.append(
                {
                    "name": name,
                    "count": len(plist),
                    "color": theme_color,
                    "plugins": [
                        {
                            "id": p.order,
                            "name": p.name,
                            "display_name": p.display_name,
                            "version": p.version,
                            "disabled": p.disabled,
                        }
                        for p in plist
                    ],
                }
            )
        return categories

    def _balance_categories(
        self,
        categories: list[dict[str, Any]],
        detail: bool = False,
        columns: int = 2,
    ) -> list[list[dict[str, Any]]]:
        """将分类卡片按全局编号顺序切分到各列

        指令模式最多两列, 两列时必须连续切分: 左列取前 k 个分类、右列接续剩余分类,
        这样从上到下、从左到右读到的编号始终递增; 若按高度自由组合, 左栏读完十几号会
        突然跳回右栏的中间号。k 取估算高度最接近对半的位置, 尽量让两列等高。
        单列原样返回, 三列及以上退化为按高度贪心装填 (事件/过滤器模式无全局编号)。
        估算高度按模板的实际排版参数折算, 见 _estimate_category_height。
        """
        if not categories:
            return []
        if columns <= 1 or len(categories) == 1:
            return [list(categories)]
        if columns > 2:
            return self._balance_categories_greedy(categories, detail, columns)

        heights = [self._estimate_category_height(c, detail) for c in categories]
        total = sum(heights)
        best_k = 1
        best_gap = total
        left_height = 0
        for k in range(1, len(categories)):
            left_height += heights[k - 1]
            gap = abs(total - 2 * left_height)
            if gap < best_gap:
                best_gap = gap
                best_k = k
        return [list(categories[:best_k]), list(categories[best_k:])]

    def _balance_categories_greedy(
        self,
        categories: list[dict[str, Any]],
        detail: bool,
        columns: int,
    ) -> list[list[dict[str, Any]]]:
        """三列及以上的兜底分列: 按估算高度从高到低装进当前最矮的一列"""
        heights = [self._estimate_category_height(c, detail) for c in categories]
        buckets: list[list[dict[str, Any]]] = [[] for _ in range(columns)]
        bucket_heights = [0] * columns
        order = sorted(range(len(categories)), key=lambda i: heights[i], reverse=True)
        for idx in order:
            target_col = bucket_heights.index(min(bucket_heights))
            buckets[target_col].append(categories[idx])
            bucket_heights[target_col] += heights[idx]
        return buckets

    def _estimate_category_height(self, cat: dict[str, Any], detail: bool = False) -> int:
        """估算单个分类卡片在列内占用的高度 (pt)

        按模板 category_card 的真实排版折算: 固定头部/内边距 + 每个插件条目的实际高度。
        detail=True 时按能力区 chip 的折行数累加指令/指令组/监听器的高度。
        估算以默认 830pt 页宽为基准: 页宽更窄时文字折行更多, 只求两列大致均衡。
        """
        plugins = cat.get("plugins") or []
        if detail:
            height = InternalCFG.EST_DETAIL_CATEGORY_BASE + sum(
                _estimate_plugin_detail_height(p) for p in plugins
            )
        else:
            height = InternalCFG.EST_CATEGORY_BASE + sum(
                _estimate_plugin_row_height(p) for p in plugins
            )
        # 分类卡片之间的 stack spacing: 两列卡片数不同时, 列高差主要差在这里
        return int(round(height + InternalCFG.EST_CATEGORY_STACK_GAP))

    def _estimate_height(self, nodes: list[RenderNode]) -> int:
        """高度估算器(暂硬编码，等待完善模板逻辑)"""
        total_h = 0
        complex_nodes = [n for n in nodes if n.is_group or n.desc != ""]
        simple_nodes = [n for n in nodes if not n.is_group and n.desc == ""]

        # 复杂节点：垂直堆叠
        for node in complex_nodes:
            if node.is_group:
                total_h += 60 + self._estimate_height(node.children)
            else:
                total_h += 60

        # 简单节点：3列网格
        if simple_nodes:
            rows = math.ceil(len(simple_nodes) / 3)
            total_h += rows * 30 + 10

        return total_h


# ---- 两列高度估算 ----
# 系数统一维护在 InternalCFG.EST_* (domain/constants.py 的「两列高度估算系数」),
# 它们只影响左右分列的平衡, 不参与渲染; 校准说明见那边注释。


class _CommandPayload(TypedDict, total=False):
    """能力区指令 chip 的数据形状 (模板只读 name/aliases)"""

    name: str
    aliases: list[str]


class _GroupPayload(TypedDict, total=False):
    """能力区指令组的数据形状"""

    name: str
    commands: list[_CommandPayload]


class _CapabilitiesPayload(TypedDict, total=False):
    """插件能力树的数据形状"""

    commands: list[_CommandPayload]
    groups: list[_GroupPayload]
    listeners: list[str]


def _estimate_text_width(text: str, size: float) -> float:
    """按全宽/半宽比例估算一段文本的排版宽度 (pt)"""
    width = 0.0
    for char in text:
        wide = unicodedata.east_asian_width(char) in ("W", "F")
        width += size if wide else size * 0.52
    return width


def _estimate_chip_rows(widths: list[float], line_width: float) -> int:
    """按模板 par 的折行行为估算 chip 占用的行数"""
    rows = 1
    used = 0.0
    for width in widths:
        chunk = width + InternalCFG.EST_CHIP_GAP
        if used and used + chunk > line_width:
            rows += 1
            used = chunk
        else:
            used += chunk
    return rows


def _estimate_command_chip_widths(commands: list[_CommandPayload]) -> list[float]:
    """指令 chip 及其别名 chip 的宽度序列 (字号与字距取自模板)"""
    widths: list[float] = []
    for command in commands:
        name = command.get("name") or ""
        # 主指令 chip: 8.5pt 粗体 + 0.5pt 字距; 别名 chip: 8pt 带 ↳ 前缀
        widths.append(
            _estimate_text_width(name, 8.5) * 1.02
            + 0.5 * max(0, len(name) - 1)
            + InternalCFG.EST_CHIP_PADDING
        )
        for alias in command.get("aliases") or []:
            widths.append(_estimate_text_width(f"↳ {alias}", 8.0) + InternalCFG.EST_CHIP_PADDING)
    return widths


def _estimate_listener_chip_widths(listeners: list[str]) -> list[float]:
    """监听器 chip 的宽度序列 (8pt 常规字重)"""
    return [
        _estimate_text_width(name, 8.0) + InternalCFG.EST_CHIP_PADDING for name in listeners
    ]


def _estimate_plugin_row_height(plugin: dict[str, Any]) -> float:
    """估算指令模式下一个插件行的高度 (pt)"""
    name = plugin.get("display_name") or plugin.get("name") or ""
    lines = max(1, math.ceil(_estimate_text_width(name, 10.0) / InternalCFG.EST_PLUGIN_NAME_WIDTH))
    return InternalCFG.EST_PLUGIN_ROW + (lines - 1) * InternalCFG.EST_PLUGIN_NAME_LINE


def _estimate_plugin_detail_height(plugin: dict[str, Any]) -> float:
    """估算详细模式下一个插件条目 (含能力区) 的高度 (pt)"""
    capabilities: _CapabilitiesPayload = plugin.get("capabilities") or {}
    commands = capabilities.get("commands") or []
    groups = capabilities.get("groups") or []
    listeners = capabilities.get("listeners") or []
    if not (commands or groups or listeners):
        return InternalCFG.EST_DETAIL_PLUGIN_ROW

    height = InternalCFG.EST_DETAIL_PLUGIN_ROW + InternalCFG.EST_DETAIL_CAPABILITY_BLOCK
    if commands:
        height += InternalCFG.EST_DETAIL_SECTION_LABEL
        height += InternalCFG.EST_DETAIL_CHIP_ROW * _estimate_chip_rows(
            _estimate_command_chip_widths(commands), InternalCFG.EST_DETAIL_CHIP_WIDTH
        )
    for group in groups:
        group_commands = group.get("commands") or []
        # 空指令组模板不渲染, 不占高度
        if not group_commands:
            continue
        height += InternalCFG.EST_DETAIL_GROUP_OVERHEAD
        height += InternalCFG.EST_DETAIL_CHIP_ROW * _estimate_chip_rows(
            _estimate_command_chip_widths(group_commands),
            InternalCFG.EST_DETAIL_GROUP_CHIP_WIDTH,
        )
    if listeners:
        height += InternalCFG.EST_DETAIL_SECTION_LABEL
        height += InternalCFG.EST_DETAIL_CHIP_ROW * _estimate_chip_rows(
            _estimate_listener_chip_widths(listeners), InternalCFG.EST_DETAIL_CHIP_WIDTH
        )
    return height

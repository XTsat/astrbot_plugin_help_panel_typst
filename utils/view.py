import asyncio
import json
import math
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

from ..domain import PluginMetadata, RenderNode, InternalCFG, TypstPluginConfig


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
    ):
        """生成布局数据并写入文件"""
        payload = self._generate_balanced_payload(
            plugins, title, mode, prefixes, font_list
        )
        # 注入颜色配置
        payload["colors"] = self.cfg.appearance.get_active_colors()

        save_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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

        extract_singles = mode == "command"

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

            # B: 单指令 -> Singles (Command 模式)
            if extract_singles and len(nodes) == 1 and not nodes[0].is_group:
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

        cols_data = [[] for _ in range(3)]
        col_heights = [0] * 3

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
        """指令模式: 按分类分组为卡片, 并均衡分配到 2 列"""
        categories = self._group_by_category(plugins)
        cols = self._balance_categories(categories)

        return {
            "title": title,
            "mode": "command",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "category_count": len(categories),
            "category_columns": cols,
        }

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
        grouped: dict[str, list[PluginMetadata]] = {}
        for p in plugins:
            cat = (p.category or "").strip() or InternalCFG.CATEGORY_FALLBACK
            grouped.setdefault(cat, []).append(p)

        # 分类排序: 名称升序, 兜底分类置底
        names = sorted(grouped.keys())
        if InternalCFG.CATEGORY_FALLBACK in names:
            names.remove(InternalCFG.CATEGORY_FALLBACK)
            names.append(InternalCFG.CATEGORY_FALLBACK)

        palette = InternalCFG.CATEGORY_PALETTE
        categories = []
        for idx, name in enumerate(names):
            # 插件按全局编号排序, 保持与全量列表一致的展示顺序
            plist = sorted(grouped[name], key=lambda x: x.order)
            categories.append(
                {
                    "name": name,
                    "count": len(plist),
                    "color": palette[idx % len(palette)],
                    "plugins": [
                        {
                            "id": p.order,
                            "name": p.name,
                            "display_name": p.display_name,
                            "version": p.version,
                        }
                        for p in plist
                    ],
                }
            )
        return categories

    def _balance_categories(
        self, categories: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """将分类卡片按估算高度贪心分配到 2 列, 使两列高度接近"""
        weighted = [(c, self._estimate_category_height(c)) for c in categories]
        sorted_cats = sorted(weighted, key=lambda x: x[1], reverse=True)

        cols: list[list[dict[str, Any]]] = [[], []]
        heights = [0, 0]

        for cat, h in sorted_cats:
            idx = heights.index(min(heights))
            cols[idx].append(cat)
            heights[idx] += h

        return cols

    def _estimate_category_height(self, cat: dict[str, Any]) -> int:
        """估算单个分类卡片高度 (pt): 头部 + 每个插件一行"""
        count = int(cat.get("count", 0))
        return (
            InternalCFG.CATEGORY_HEADER_HEIGHT + count * InternalCFG.CATEGORY_ROW_HEIGHT
        )

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

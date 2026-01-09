import math
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

from ..domain import PluginMetadata, RenderNode
from . import TypstPluginConfig


class HelpHint:
    """提供用户提示文本"""
    def msg_searching(self, query: str) -> str:
        return f"正在搜索 '{query}'..."

    def msg_rendering(self, mode: str) -> str:
        return "正在渲染..." if mode == "command" else "正在获取列表..."

    def msg_empty_result(self, mode: str, query: Optional[str]) -> str:
        target = "事件监听器" if mode == "event" else "插件或指令"
        if query:
            return f"未找到包含 '{query}' 的{target}。"
        return f"当前没有可显示的{target}。"


class MsgRecall:
    """负责发送提示消息, 并在完成后撤回"""
    async def send_wait(self, event: AstrMessageEvent, text: str) -> Optional[Union[int, str]]:
        """发送提示并返回消息ID"""
        bot = event.bot
        payload = event.plain_result(text)

        # OneBot API
        if hasattr(event, "_parse_onebot_json") and hasattr(bot, "call_action"):
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

    async def recall(self, event: AstrMessageEvent, message_id: Union[int, str, None]):
        """撤回指定消息"""
        if not message_id: return
        bot = event.bot

        # 稍等避免闪撤
        await asyncio.sleep(1) 

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
                logger.debug(f"[HelpTypst] 未找到撤回方法")
        except Exception as e:
            logger.warning(f"[HelpTypst] 撤回消息 {message_id} 失败: {e}")

    def _extract_message_id(self, resp: Any) -> Optional[Union[int, str]]:
        """提取 Message ID"""
        if not resp: return None

        # 直接是 ID
        if isinstance(resp, (int, str)): return resp

        # 字典结构解析
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, dict):
                if "message_id" in data: return data["message_id"]
                if "res_id" in data: return data["res_id"]
                if "forward_id" in data: return data["forward_id"]

            if "message_id" in resp: return resp["message_id"]
        if hasattr(resp, "message_id"): return resp.message_id

        return None


class TypstLayout:
    """负责将结构化数据转换为 Typst 渲染所需的布局 JSON"""
    def __init__(self, config: TypstPluginConfig):
        self.cfg = config

    def dump_layout_json(self, plugins: List[PluginMetadata], save_path: Path, title: str, mode: str):
        """生成布局数据并写入文件"""
        payload = self._generate_balanced_payload(plugins, title, mode)

        save_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _generate_balanced_payload(self, plugins: List[PluginMetadata], title: str, mode: str) -> Dict[str, Any]:
        """瀑布流分发逻辑"""
        giants = []
        complex_plugins = []
        single_node_plugins = []

        # 辅助函数：获取节点列表
        def get_nodes(p: PluginMetadata) -> List[RenderNode]:
            if hasattr(p, "nodes") and p.nodes: return p.nodes
            if hasattr(p, "command_nodes") and p.command_nodes: return p.command_nodes
            return []

        extract_singles = (mode == "command")

        # 1. 预分类
        for p in plugins:
            nodes = get_nodes(p)

            # A: 工具调用 -> Singles
            is_tool = len(nodes) > 0 and (nodes[0].tag == "tool" or nodes[0].tag == "mcp")
            if is_tool:
                single_node_plugins.append(p.model_dump())
                continue

            # B: 单指令 -> Singles (Command 模式)
            if extract_singles and len(nodes) == 1 and not nodes[0].is_group:
                single_node_plugins.append(p.model_dump())
                continue

            # C: 巨型块 -> Giants (Event/Filter 模式)
            h_val = self._estimate_height(nodes)
            if mode in ("event", "filter") and h_val > self.cfg.rendering.giant_threshold:
                giants.append(p.model_dump())
                continue

            # D: 其余 -> 瀑布流
            complex_plugins.append(p)

        # 2. 瀑布流平衡算法
        # 计算高度权重 (+80 是对卡片头部和Padding的估算)
        plugins_with_height = [
            (p, self._estimate_height(get_nodes(p)) + 80)
            for p in complex_plugins
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
            "plugin_count": len(plugins),
            "giants": giants,
            "columns": cols_data, 
            "singles": single_node_plugins 
        }

    def _estimate_height(self, nodes: List[RenderNode]) -> int:
        """高度估算器(暂时硬编码)"""
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
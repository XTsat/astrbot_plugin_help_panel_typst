import asyncio
import json
import math
import os
import unicodedata
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

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


class _EstimateGeometry(NamedTuple):
    """随页宽/列数变化的排版尺寸 (pt)"""

    plugin_chip_width: float
    group_chip_width: float


def _estimate_geometry(page_width: float, columns: int) -> _EstimateGeometry:
    """按页宽与分类列数换算 chip 可用行宽

    分类卡内部宽度随页面宽度线性变化, 固定行宽会让窄页面下的 chip 折行数被系统性低估。
    """
    column_count = max(1, columns)
    region = page_width - 2 * InternalCFG.EST_PAGE_MARGIN_X
    card_width = (
        region - (column_count - 1) * InternalCFG.EST_COLUMN_GUTTER
    ) / column_count
    plugin_chip = card_width - InternalCFG.EST_DETAIL_CARD_PADDING_X
    return _EstimateGeometry(
        # 极端窄页时行宽不能压到 0, 否则折行数无穷大
        plugin_chip_width=max(60.0, plugin_chip),
        group_chip_width=max(
            48.0, plugin_chip - InternalCFG.EST_DETAIL_GROUP_PADDING_X
        ),
    )


def _category_card_head(cat: dict[str, Any], detail: bool) -> float:
    """分类卡片的固定开销: 卡片头部与内边距, 加上与下一张卡的间距"""
    base = (
        InternalCFG.EST_DETAIL_CATEGORY_BASE
        if detail
        else InternalCFG.EST_CATEGORY_BASE
    )
    return base + InternalCFG.EST_CATEGORY_STACK_GAP


def _category_plugin_rows(
    cat: dict[str, Any], detail: bool, geometry: _EstimateGeometry
) -> list[float]:
    """分类内每个插件条目的估算高度序列 (累加后即分类卡内容高度)"""
    plugins = cat.get("plugins") or []
    if detail:
        return [_estimate_plugin_detail_height(p, geometry) for p in plugins]
    return [_estimate_plugin_row_height(p) for p in plugins]


def _partition_gap(
    heights_variants: list[list[float]], left: list[int], right: list[int]
) -> tuple[float, float]:
    """返回 (两列最大落差, 两列落差之和), 多套排版取其中最大的一套"""
    worst = 0.0
    total = 0.0
    for heights in heights_variants:
        left_sum = sum(heights[i] for i in left)
        right_sum = sum(heights[i] for i in right)
        gap = abs(left_sum - right_sum)
        worst = max(worst, gap)
        total += gap
    return worst, total


def _column_runs(mask: int, count: int) -> int:
    """统计分类在编号顺序上被分到两列的次数, 用来在同样齐平时优先选少交错的排法"""
    runs = 1
    for i in range(1, count):
        if (mask >> i & 1) != (mask >> (i - 1) & 1):
            runs += 1
    return runs


def _partition_two_columns(
    heights_variants: list[list[float]], count: int
) -> list[list[int]]:
    """两列: 直接枚举所有划分取最优

    分类卡只有个位数, 2^count 枚举的成本可以忽略; 贪心+局部搜索会卡在「先走一步不改善、
    再走一步才改善」的台阶上, 实测真实面板会被卡住, 所以这里用穷举。
    评分顺序: 最差那套排版的落差 → 两套落差之和 → 交错次数 (尽量少拆散分类顺序)。
    """
    all_mask = (1 << count) - 1
    best: tuple[float, float, int] | None = None
    best_mask = 1
    # 固定第一个分类在左列, 只枚举另一半, 省掉左右镜像的重复
    for mask in range(1, all_mask + 1, 2):
        if mask == all_mask:
            continue
        left = [i for i in range(count) if mask >> i & 1]
        right = [i for i in range(count) if not mask >> i & 1]
        worst, total = _partition_gap(heights_variants, left, right)
        cost = (round(worst, 1), round(total, 1), _column_runs(mask, count))
        if best is None or cost < best:
            best, best_mask = cost, mask
    return [
        [i for i in range(count) if best_mask >> i & 1],
        [i for i in range(count) if not best_mask >> i & 1],
    ]


def _partition_greedy(
    heights_variants: list[list[float]], columns: int
) -> list[list[int]]:
    """三列及以上的兜底: 按高度占比从高到低装进当前最矮的一列, 再做单块/两块微调"""
    count = len(heights_variants[0])
    # 各套排版绝对高度差着量级, 装填权重按占比平均, 避免被长的那套吃掉
    shares = [
        [h / (sum(heights) or 1.0) for h in heights] for heights in heights_variants
    ]
    weight = [sum(s[i] for s in shares) / len(shares) for i in range(count)]

    assign = [0] * count
    placed = [False] * count
    for idx in sorted(range(count), key=lambda i: weight[i], reverse=True):
        sums = [0.0] * columns
        for i in range(count):
            if placed[i]:
                sums[assign[i]] += weight[i]
        assign[idx] = sums.index(min(sums))
        placed[idx] = True

    def buckets_of(state: list[int]) -> list[list[int]]:
        buckets: list[list[int]] = [[] for _ in range(columns)]
        for i, col in enumerate(state):
            buckets[col].append(i)
        return [sorted(bucket) for bucket in buckets]

    def worst_gap(state: list[int]) -> float:
        buckets = buckets_of(state)
        return max(
            _partition_gap(heights_variants, buckets[a], buckets[b])[0]
            for a in range(columns)
            for b in range(a + 1, columns)
        )

    best = worst_gap(assign)
    for _ in range(6):
        improved = False
        for i in range(count):
            origin = assign[i]
            for other in range(columns):
                if other == origin:
                    continue
                assign[i] = other
                gap = worst_gap(assign)
                if gap < best - 0.5:
                    best, improved = gap, True
                    break
                assign[i] = origin
        for i in range(count):
            for j in range(i + 1, count):
                if assign[i] == assign[j]:
                    continue
                assign[i], assign[j] = assign[j], assign[i]
                gap = worst_gap(assign)
                if gap < best - 0.5:
                    best, improved = gap, True
                else:
                    assign[i], assign[j] = assign[j], assign[i]
        if not improved:
            break
    return buckets_of(assign)


def _partition_indices(
    heights_variants: list[list[float]], columns: int
) -> list[list[int]]:
    """把整块内容装进各列 (返回每列的下标, 列内按下标升序)

    内容块不能像文字那样在行间断开, 所以只能在列之间整块搬动; 传入多套高度 (指令模式 /
    详细模式) 时按各套落差的较大者评分: 两个面板共用一份列分配, 编号才能跟着走。
    """
    count = len(heights_variants[0]) if heights_variants else 0
    if count == 0:
        return [[] for _ in range(columns)]
    if count < columns:
        return [[i] for i in range(count)] + [[] for _ in range(columns - count)]
    # 穷举只在分类数不多时划算 (2^n 增长), 分类特别多的面板退化成贪心 + 微调
    if columns == 2 and count <= InternalCFG.EST_BALANCE_EXHAUSTIVE_LIMIT:
        return _partition_two_columns(heights_variants, count)
    return _partition_greedy(heights_variants, columns)


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
            widths.append(
                _estimate_text_width(f"↳ {alias}", 8.0) + InternalCFG.EST_CHIP_PADDING
            )
    return widths


def _estimate_listener_chip_widths(listeners: list[str]) -> list[float]:
    """监听器 chip 的宽度序列 (8pt 常规字重)"""
    return [
        _estimate_text_width(name, 8.0) + InternalCFG.EST_CHIP_PADDING
        for name in listeners
    ]


def _estimate_plugin_row_height(plugin: dict[str, Any]) -> float:
    """估算指令模式下一个插件行的高度 (pt)"""
    name = plugin.get("display_name") or plugin.get("name") or ""
    lines = max(
        1,
        math.ceil(_estimate_text_width(name, 10.0) / InternalCFG.EST_PLUGIN_NAME_WIDTH),
    )
    return InternalCFG.EST_PLUGIN_ROW + (lines - 1) * InternalCFG.EST_PLUGIN_NAME_LINE


def _estimate_plugin_detail_height(
    plugin: dict[str, Any], geometry: _EstimateGeometry
) -> float:
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
            _estimate_command_chip_widths(commands), geometry.plugin_chip_width
        )
    for group in groups:
        group_commands = group.get("commands") or []
        # 空指令组模板不渲染, 不占高度
        if not group_commands:
            continue
        height += InternalCFG.EST_DETAIL_GROUP_OVERHEAD
        height += InternalCFG.EST_DETAIL_CHIP_ROW * _estimate_chip_rows(
            _estimate_command_chip_widths(group_commands), geometry.group_chip_width
        )
    if listeners:
        height += InternalCFG.EST_DETAIL_SECTION_LABEL
        height += InternalCFG.EST_DETAIL_CHIP_ROW * _estimate_chip_rows(
            _estimate_listener_chip_widths(listeners), geometry.plugin_chip_width
        )
    return height


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

    @staticmethod
    def _order_digits(plugins: list[PluginMetadata]) -> int:
        """编号徽章的位数: 取最大编号的位数

        插件数 ≠ 最大编号: 屏蔽/搜索后子集的最大编号可能远大于条目数,
        徽章位宽不够时, 两位编号会把右侧插件名顶歪。
        """
        return max(1, len(str(max((p.order for p in plugins), default=0))))

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
        cols = self._arrange_columns(
            categories, plugins, self._resolve_column_count("command")
        )

        return {
            "title": title,
            "mode": "command",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "order_digits": self._order_digits(plugins),
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
        cols = self._arrange_columns(
            categories, plugins, self._resolve_column_count("command_detail")
        )

        return {
            "title": title,
            "mode": "command_detail",
            "prefixes": prefixes,
            "fonts": font_list,
            "plugin_count": len(plugins),
            "order_digits": self._order_digits(plugins),
            "enabled_count": sum(1 for p in plugins if not p.disabled),
            "category_columns": cols,
        }

    def _build_plugin_capabilities(self, plugin: PluginMetadata) -> dict[str, Any]:
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
                group_cmds = self._collect_group_commands(node.children, prefix="")
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

    def resolve_menu_order(
        self, plugins: list[PluginMetadata], detail: bool = False
    ) -> list[PluginMetadata]:
        """按面板阅读顺序 (左列自上而下, 再右列自上而下) 返回插件序列

        分类卡会被整张搬进较矮的一列, 所以面板里的编号必须按搬完后的顺序重排: 否则左列
        读到十几号会突然跳回右列中间号。渲染与「按编号查详情」共用这一份顺序, 不能各算各的,
        因此 detail 不参与列分配 (签名保留给调用方显式说明意图)。
        """
        if not plugins:
            return []
        groups = self._group_plugins(plugins)
        if len(groups) <= 1:
            return [p for _, plist in groups for p in plist]
        layout = self._balance_groups(groups, self._resolve_column_count("command"))
        by_name = {name: plist for name, plist in groups}
        return [
            plugin for names in layout for name in names for plugin in by_name[name]
        ]

    def _arrange_columns(
        self,
        categories: list[dict[str, Any]],
        plugins: list[PluginMetadata],
        columns: int,
    ) -> list[list[dict[str, Any]]]:
        """把分类卡摆进各列 (列内顺序仍按编号, 跨列允许交错)

        列分配必须与 resolve_menu_order 完全一致, 否则卡片位置和卡里的编号会对不上,
        所以这里也走 _balance_groups, 只是把分类名换回卡片数据。
        """
        if not categories:
            return []
        by_name = {c["name"]: c for c in categories}
        index_of = {c["name"]: i for i, c in enumerate(categories)}
        layout = self._balance_groups(self._group_plugins(plugins), columns)
        return [
            [by_name[name] for name in sorted(names, key=lambda n: index_of[n])]
            for names in layout
            if names
        ]

    def _estimate_payload(self, plugin: PluginMetadata) -> dict[str, Any]:
        """高度估算用的插件字典: 只保留 _estimate_plugin_* 会读到的字段"""
        return {
            "id": plugin.order,
            "name": plugin.name,
            "display_name": plugin.display_name,
            "capabilities": self._build_plugin_capabilities(plugin),
        }

    def _balance_groups(
        self, groups: list[tuple[str, list[PluginMetadata]]], columns: int
    ) -> list[list[str]]:
        """返回每列的分类名序列 (指令面板与详细面板共用同一份列分配)

        两个面板的分类卡高度差着量级, 各自求最优会得到不同的列分配, 编号就会跟着打架。
        这里同时用两套排版估算, 挑「两个面板里较难对齐的那一侧也尽量齐平」的分配。
        """
        names = [name for name, _ in groups]
        if len(groups) <= 1 or columns <= 1:
            return [names]
        geometry = _estimate_geometry(self.cfg.rendering.page_width, columns)
        heights_simple: list[float] = []
        heights_detail: list[float] = []
        for _, plist in groups:
            card = {"name": "", "plugins": [self._estimate_payload(p) for p in plist]}
            heights_simple.append(
                float(_category_card_head(card, False))
                + sum(_category_plugin_rows(card, False, geometry))
            )
            heights_detail.append(
                float(_category_card_head(card, True))
                + sum(_category_plugin_rows(card, True, geometry))
            )
        buckets = _partition_indices([heights_simple, heights_detail], columns)
        return [[names[i] for i in bucket] for bucket in buckets]

    def _group_plugins(
        self, plugins: list[PluginMetadata]
    ) -> list[tuple[str, list[PluginMetadata]]]:
        """按分类聚合插件并排出分类顺序 (名称升序, 兜底分类置底)

        分类内先按名称排序: 分配编号时插件还没有 order, 必须有一个不依赖编号的确定性顺序。
        """
        fallback = self.cfg.category.fallback
        grouped: dict[str, list[PluginMetadata]] = {}
        for plugin in plugins:
            cat = (plugin.category or "").strip() or fallback
            grouped.setdefault(cat, []).append(plugin)
        names = sorted(grouped.keys())
        if fallback in names:
            names.remove(fallback)
            names.append(fallback)
        return [
            (
                name,
                sorted(grouped[name], key=lambda x: (x.display_name is None, x.name)),
            )
            for name in names
        ]

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

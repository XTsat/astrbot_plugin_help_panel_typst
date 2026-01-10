import asyncio
from pathlib import Path

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
import astrbot.api.message_components as Comp

from .domain import InternalCFG
from .utils import TypstPluginConfig, HelpHint, MsgRecall, TypstLayout
from .core import CommandAnalyzer, EventAnalyzer, FilterAnalyzer, TypstRenderer

class HelpTypst(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 1. 配置 (字典 → 强类型的 Dataclass)
        self.plugin_config = TypstPluginConfig.load(config)

        # 2. 路径
        self.plugin_dir = Path(__file__).parent
        self.data_dir = StarTools.get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        template_path = self.plugin_dir / "templates" / InternalCFG.NAME_TEMPLATE
        font_dir = self.plugin_dir / "resources" / InternalCFG.NAME_FONT_DIR

        # 3. 视图层
        self.layout = TypstLayout(self.plugin_config)
        self.hint = HelpHint()
        self.msg = MsgRecall() 

        # 4. 渲染引擎配置注入
        self.renderer = TypstRenderer(
            data_dir=self.data_dir,
            template_path=template_path,
            font_dir=font_dir,
            config=self.plugin_config.rendering
        )

        # 5. 分析器
        self.cmd_analyzer = CommandAnalyzer(context, self.plugin_config)
        self.evt_analyzer = EventAnalyzer(context, self.plugin_config)
        self.flt_analyzer = FilterAnalyzer(context, self.plugin_config)

    async def _handle_request(self, event: AstrMessageEvent, analyzer, title: str, mode: str, query: str | None):
        """通用请求处理逻辑"""
        # 1. 发送提示
        hint_text = self.hint.msg_searching(query) if query else self.hint.msg_rendering(mode)
        wait_msg_id = await self.msg.send_wait(event, hint_text)

        def data_pipeline(save_path: Path) -> int:
            """数据流转"""
            # 数据层：获取对象
            plugins = analyzer.get_plugins(query)
            if not plugins: return 0

            # 视图层：决定标题 & 计算布局 & 写入JSON
            display_title = f"搜索结果: \"{query}\"" if query else title
            self.layout.dump_layout_json(plugins, save_path, display_title, mode)

            return len(plugins)

        # 2. 执行渲染
        result, error = await self.renderer.render(data_pipeline, mode, query)

        # 3. 结束撤回提示
        if wait_msg_id:
            await self.msg.recall(event, wait_msg_id)

        # 4. 处理结果
        if result:
            try:
                # 构建消息链
                comps = [Comp.Image.fromFileSystem(p) for p in result.images]
                yield event.chain_result(comps)
            finally:
                # 后台任务清理文件列表
                if result.temp_files:
                    asyncio.create_task(self._cleanup_task(result.temp_files))
        else:
            # 错误处理
            if error == "empty":
                yield event.plain_result(self.hint.msg_empty_result(mode, query))
            else:
                yield event.plain_result(error)

    async def _cleanup_task(self, files: list[Path]):
        """异步清理任务"""
        await asyncio.sleep(InternalCFG.DELAY_SEND)
        for p in files:
            try:
                if p.exists(): p.unlink()
            except Exception as e:
                logger.warning(f"[HelpTypst] 临时文件清理失败 {p}: {e}")

    def _parse_query(self, event: AstrMessageEvent) -> str | None:
        parts = event.message_str.strip().split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else None

    @filter.command("helps")
    async def show_menu(self, event: AstrMessageEvent):
        """显示指令菜单"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.cmd_analyzer, "AstrBot 指令菜单", "command", query):
            yield r

    @filter.command("events")
    async def show_events(self, event: AstrMessageEvent):
        """显示事件监听列表"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.evt_analyzer, "AstrBot 事件监听", "event", query):
            yield r

    @filter.command("filters")
    async def show_filters(self, event: AstrMessageEvent):
        """显示过滤器详情"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.flt_analyzer, "AstrBot 过滤器分析", "filter", query):
            yield r

    async def terminate(self):
        """插件卸载时清理"""
        try:
            for f in self.data_dir.glob("temp_*"):
                try: f.unlink()
                except: pass
        except Exception: pass
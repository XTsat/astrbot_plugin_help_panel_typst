import asyncio
import shutil
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.core.star.filter.command import GreedyStr
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Image

from .domain import DefaultCFG, InternalCFG, RenderFailure, TypstPluginConfig
from .utils import (
    FontManager,
    HelpHint,
    MsgRecall,
    TypstLayout,
    sync_plugin_options,
)
from .core import (
    BaseAnalyzer,
    CommandAnalyzer,
    EventAnalyzer,
    FilterAnalyzer,
    PreviewError,
    PreviewService,
    TypstRenderer,
    list_installed_plugins,
)


class HelpTypst(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        # 1. 静态资源路径
        self.plugin_dir = Path(__file__).parent
        self.data_dir = StarTools.get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.template_path = self.plugin_dir / "templates" / InternalCFG.NAME_TEMPLATE

        # 2. 配置加载
        self.config = config
        self.plugin_config = TypstPluginConfig.load(config)

        # 3. 获取字体
        # 路径项已在 config.load() 归一 (~ 展开 + strip), 这里直接用
        raw_path = self.plugin_config.custom_font_path
        if raw_path:
            self.user_font_dir = Path(raw_path)  # 自定义字体目录
        else:
            self.user_font_dir = self.data_dir / "fonts"  # 缺省值

        try:
            self.user_font_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if not raw_path:
                logger.warning(f"[HelpTypst] 无法创建默认字体目录: {e}")

        self.builtin_font_dir = (
            self.plugin_dir / "resources" / InternalCFG.NAME_FONT_DIR
        )  # 内置
        self.font_dirs = [self.builtin_font_dir, self.user_font_dir]  # 汇总

        # 3.1 默认背景图目录 (与字体目录一致, 只扫描该目录下的图片)
        try:
            default_bg_dir = self.data_dir / InternalCFG.NAME_BACKGROUND_DIR
            default_bg_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[HelpTypst] 无法创建默认背景图目录: {e}")

        # 3.2 安装时导入内置图片到背景目录 (仅首次)
        try:
            self._import_default_backgrounds()
        except Exception as e:
            logger.warning(f"[HelpTypst] 导入内置背景图失败: {e}")

        # 3. 初始化组件
        self.font_manager = FontManager(self.font_dirs)
        self.layout = TypstLayout(self.plugin_config)
        self.hint = HelpHint()
        self.msg = MsgRecall()

        # 4. 渲染器
        # 编译时字体目录 = 项目目录 + 系统字体库 (与扫描保持一致, 否则系统内置字体
        # 虽被扫描进选项, 编译时却未加载而不生效)
        self.renderer = TypstRenderer(
            star=self,
            data_dir=self.data_dir,
            template_path=self.template_path,
            font_dirs=self.font_manager.get_search_paths(),
            config=self.plugin_config,
        )

        # 5. 分析器
        self.cmd_analyzer = CommandAnalyzer(context, self.plugin_config)
        self.evt_analyzer = EventAnalyzer(context, self.plugin_config)
        self.flt_analyzer = FilterAnalyzer(context, self.plugin_config)

        self.prefixes: list[str] = []

        # /typst font 触发的自重载: terminate 跳过重复字体扫描 (新实例 initialize 会再扫)
        self._skip_rescan_on_terminate = False

        # 6. 网页样式预览 (pages/preview): 老版本 AstrBot 没有 register_web_api,
        # 此时跳过注册, 插件其余功能不受影响
        self.preview_service = PreviewService(
            star=self,
            data_dir=self.data_dir,
            template_path=self.template_path,
            font_dirs=self.font_manager.get_search_paths(),
            base_config=self.plugin_config,
            font_manager=self.font_manager,
            renderer=self.renderer,
            provider_builder=self._build_preview_provider,
            persona_getter=self._get_persona_name,
            plugin_lister=lambda: list_installed_plugins(self.context),
        )
        self._register_preview_apis()

    def _register_preview_apis(self) -> None:
        """注册插件页 API；注册失败只影响预览页，不阻断插件加载"""
        register = getattr(self.context, "register_web_api", None)
        if not callable(register):
            logger.info(
                "[HelpTypst] 当前 AstrBot 版本不支持插件页面 Web API，样式预览页不可用"
            )
            return

        plugin_name = self.plugin_dir.name
        for route, handler, methods, desc in (
            (
                f"/{plugin_name}/preview/options",
                self.api_preview_options,
                ["GET"],
                "获取样式预览可选项",
            ),
            (
                f"/{plugin_name}/preview/fonts",
                self.api_preview_fonts,
                ["POST"],
                "重新扫描字体并返回可选字体",
            ),
            (
                f"/{plugin_name}/preview/render",
                self.api_preview_render,
                ["POST"],
                "按样式渲染预览图",
            ),
            (
                f"/{plugin_name}/preview/apply",
                self.api_preview_apply,
                ["POST"],
                "把预览样式写入插件配置",
            ),
        ):
            try:
                register(route, handler, methods, desc)
            except Exception as e:
                logger.warning(f"[HelpTypst] 注册预览接口 {route} 失败: {e}")

    async def initialize(self):
        """异步初始化"""
        self._init_prefixes(self.context)
        await asyncio.to_thread(self._refresh_resources)
        await asyncio.to_thread(self._auto_close_rescan_flag)
        logger.info("[HelpTypst] 初始化完成")

    def _auto_close_rescan_flag(self):
        """「重新扫描字体」一次性开关: 勾选保存后自动关闭

        扫描本体由 _refresh_resources 执行 (initialize 总会触发, terminate 仅在非自重载时触发),
        这里只负责在扫描完成后把开关复位, 避免每次重载都重复扫描。
        """
        try:
            # 开关当前值统一经 plugin_config 读取; 写回仍需落到 raw config 才能持久化
            if not self.plugin_config.appearance.rescan_fonts:
                return
            appearance = self.config.get("appearance", {})
            if not isinstance(appearance, dict):
                return
            # 自动关闭开关 (raw config 持久化 + 同步内存 dataclass, 便于重复调用幂等)
            appearance["rescan_fonts"] = False
            self.plugin_config.appearance.rescan_fonts = False
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            logger.info("[HelpTypst] 已按「重新扫描字体」开关完成扫描并自动关闭该开关")
        except Exception as e:
            logger.warning(f"[HelpTypst] 自动关闭「重新扫描字体」开关失败: {e}")

    def _refresh_resources(self):
        try:
            # 1. 扫描; 失败时 scan_fonts 已记录原因, 仅跳过字体相关的下拉与清洗
            scanned = self.font_manager.scan_fonts()
            if not scanned:
                logger.warning("[HelpTypst] 字体扫描未成功, 已保留原有字体选项")

            # 2. 同步内存 Schema (只改 config.schema, 不写磁盘文件): 新字体无需重载即可出现在配置面板
            #    预设项与字体扫描无关, 扫描失败也要同步; 字体项由 update_json_schema 内部按 _last_scan_ok 守卫
            live_schema = getattr(self.config, "schema", None)
            self.font_manager.update_json_schema(live_schema)

            # 3. 清洗 Config (扫描失败时 prune 内部自行跳过)
            self.font_manager.prune_invalid_config_items(self.config)

        except Exception as e:
            logger.warning(f"[HelpTypst] 资源重载失败: {e}")
        finally:
            # 插件屏蔽选项与字体扫描互不依赖: 扫描失败也要让面板的多选项保持可用
            self._sync_plugin_options()

    def _sync_plugin_options(self) -> None:
        """把已安装插件写进屏蔽项的 Schema 选项 (只改内存 schema)

        额外保留配置里未安装的旧名字: 面板只显示 options 内的值, 缺失会变成
        「看不见也删不掉」的幽灵屏蔽。
        """
        try:
            plugins = list_installed_plugins(self.context)
            installed = {str(item.get("name") or "") for item in plugins}
            extra = sorted(
                name
                for name in self.plugin_config.ignored_plugins
                if name not in installed
            )
            sync_plugin_options(
                getattr(self.config, "schema", None),
                plugins,
                extra,
            )
        except Exception as e:
            logger.warning(f"[HelpTypst] 同步屏蔽插件选项失败: {e}")

    def _import_default_backgrounds(self):
        """安装时从 resources/images 导入内置图片到默认背景图目录。

        只复制背景扫描器支持的栅格格式 (.png/.jpg/.jpeg/.webp/.gif)，
        跳过已存在的文件，避免覆盖用户自行添加的背景图。
        """
        src_dir = self.plugin_dir / "resources" / "images"
        if not src_dir.is_dir():
            return
        dst_dir = self.data_dir / InternalCFG.NAME_BACKGROUND_DIR
        dst_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for f in src_dir.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext not in InternalCFG.BACKGROUND_IMAGE_EXTS:
                continue
            dst = dst_dir / f.name
            if dst.exists():
                continue
            try:
                shutil.copy2(f, dst)
                copied += 1
            except OSError as e:
                logger.warning(f"[HelpTypst] 复制背景图失败 {f.name}: {e}")

        if copied:
            logger.info(f"[HelpTypst] 已导入 {copied} 张内置背景图到 {dst_dir}")

    async def terminate(self) -> None:
        """卸载/重载时执行: 清理临时文件、刷新字体资源与配置面板 schema"""
        # 1. 清理临时文件
        await self._perform_cleanup()

        # 2. [Dirty Hook] 刷新 Schema
        # 时序: 配置页面构建于插件实例化之前, 这是自动维护的最佳时点;
        # 扫描走线程, 卸载/重载期间不阻塞事件循环
        if self._skip_rescan_on_terminate:
            # 本次卸载由 /typst font 的自重载触发, 字体刚在指令里扫过, 跳过重复全盘扫描
            self._skip_rescan_on_terminate = False
        else:
            try:
                await asyncio.to_thread(self._refresh_resources)
            except Exception as e:
                logger.warning(f"[HelpTypst] 卸载时刷新字体资源失败: {e}")

        # 3. 「重新扫描字体」一次性开关: 勾选保存后自动扫描一次并自动关闭
        # 扫描本体已在上面完成, 这里只复位开关
        self._auto_close_rescan_flag()

    async def _perform_cleanup(self):
        try:
            # glob 匹配
            temp_files = list(self.data_dir.glob("temp_*"))
            if not temp_files:
                return

            logger.debug(f"[HelpTypst] 清理 {len(temp_files)} 个缓存文件...")

            for f in temp_files:
                try:
                    if f.exists():  # 双重检查
                        f.unlink()
                except OSError:
                    # 文件可能已被其它请求清理, 或目录只读; 清理失败不影响发送
                    pass

        except Exception as e:
            logger.warning(f"[HelpTypst] 清理失败: {e}")

    @filter.command_group("typst")  # 该指令组留待扩展更多调试功能
    @filter.permission_type(filter.PermissionType.ADMIN)
    def typst(self):
        pass

    @typst.command("font")
    async def cmd_scan_fonts(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """扫描字体并重载插件"""
        # 1. 扫描与更新
        await asyncio.to_thread(self._refresh_resources)
        if not self.font_manager.last_scan_ok:
            # 扫描失败时不重载, 避免用失败的空结果覆盖面板里的字体选项
            yield event.plain_result(
                "❌ 字体扫描失败（详见日志）。已保留原有字体选项，未执行重载"
            )
            return
        count = len(self.font_manager.available_families)

        # 2. 尝试自我重载
        try:
            pm = getattr(
                self.context, "_star_manager", None
            )  # hack: 获取 PluginManager 实例
            if pm:
                # 插件 ID 优先取 AstrBot 注入的 name, 兜底取插件目录名 (与 metadata.yaml 同名)
                plugin_name = getattr(self, "name", None) or self.plugin_dir.name
                yield event.plain_result(
                    f"✅ 扫描完成 ({count} fonts)。正在重载以刷新面板..."
                )
                # 标记本次卸载已扫过字体, 避免 terminate 再全盘扫一遍
                self._skip_rescan_on_terminate = True
                asyncio.create_task(self._safe_reload(pm, plugin_name))  # 异步延迟重载
            else:
                yield event.plain_result(f"✅ 扫描完成 ({count} fonts)。请手动重载插件")
        except Exception as e:
            yield event.plain_result(f"❌ 自动重载失败: {e}")

    async def _safe_reload(self, pm, plugin_name):
        """延迟重载"""
        await asyncio.sleep(InternalCFG.DELAY_SEND)
        try:
            logger.info(f"[HelpTypst] 正在执行自我重载: {plugin_name}")
            await pm.reload(plugin_name)
        except Exception as e:
            logger.error(f"[HelpTypst] 自我重载异常: {e}")

    async def _get_persona_name(self) -> str:
        """获取当前默认人格名称, 用于 Hero 统计卡片第三列。

        - 用户未自定义人格 (默认人格 "default") 或无 persona_manager 时返回空串,
          模板将不渲染第三列 (已用徽标展示品牌)。
        - 失败时返回空串, 不影响渲染。
        """
        try:
            pm = getattr(self.context, "persona_manager", None)
            if pm is None:
                return ""
            # 支持新旧两版方法名: v3 (Pydantic 模型) / 旧版 (dict)
            method = getattr(pm, "get_default_persona_v3", None) or getattr(
                pm, "get_default_persona", None
            )
            if method is None:
                return ""
            persona = await method()
            if persona is None:
                return ""
            # 兼容 dict 和 Pydantic 模型两种返回类型
            if isinstance(persona, dict):
                name = persona.get("name", "")
            else:
                name = getattr(persona, "name", "")
            name = str(name or "").strip()
            # 默认人格 (未自定义) 无展示意义
            if not name or name == "default":
                return ""
            return name
        except Exception as e:
            logger.warning(f"[HelpTypst] 获取人格名称失败: {e}")
            return ""

    async def _handle_request(
        self,
        event: AstrMessageEvent,
        analyzer: BaseAnalyzer,
        title: str,
        mode: str,
        query: str | None,
        is_detail: bool = False,
    ) -> AsyncGenerator[MessageEventResult, None]:
        """通用请求处理逻辑"""
        wait_msg_id = None

        if self.plugin_config.enable_waiting_message:
            # 1. 发送提示
            hint_text = (
                self.hint.msg_searching(query)
                if query and not is_detail
                else self.hint.msg_rendering(mode)
            )
            wait_msg_id = await self.msg.send_wait(event, hint_text)

        # 提前获取人格名称 (async), 供数据流注入 (空串则第三列不渲染)
        persona_name = await self._get_persona_name()
        data_pipeline = self._make_data_pipeline(
            analyzer=analyzer,
            title=title,
            mode=mode,
            query=query,
            is_detail=is_detail,
            layout=self.layout,
            font_order=self.plugin_config.appearance.get_active_font_order(),
            persona_name=persona_name,
        )

        # 2. 执行渲染
        result, error = await self.renderer.render(data_pipeline, mode, query)

        # 3. 处理结果; 等待提示在结果发出后撤回 (finally), 避免用户先等一次撤回延迟
        try:
            if result:
                try:
                    yield event.chain_result(
                        [Image.fromFileSystem(p) for p in result.images]
                    )
                finally:
                    # 后台任务清理文件列表
                    if result.temp_files:
                        asyncio.create_task(self._cleanup_task(result.temp_files))
            else:
                # 错误处理
                if error == RenderFailure.EMPTY:
                    yield event.plain_result(self.hint.msg_empty_result(mode, query))
                else:
                    yield event.plain_result(error)
        finally:
            if wait_msg_id:
                try:
                    await self.msg.recall(event, wait_msg_id)
                except Exception as e:
                    # 撤回失败不影响已发出的结果
                    logger.debug(f"[HelpTypst] 撤回等待提示失败: {e}")

    def _make_data_pipeline(
        self,
        *,
        analyzer: BaseAnalyzer,
        title: str,
        mode: str,
        query: str | None,
        is_detail: bool,
        layout: TypstLayout,
        font_order: list[str],
        persona_name: str,
    ) -> Callable[[Path], int]:
        """构造「分析 → 布局 JSON」数据流

        指令与网页预览共用这段逻辑；预览使用自己的临时布局与字体，
        因此 layout / font_order / persona_name 全部显式传入，不读 self。
        """

        def data_pipeline(save_path: Path) -> int:
            # 数据层：获取对象。意图已由 _parse_menu_query 判定, 此处不再按内容猜测:
            # 编号详情走显式 API, 关键词搜索/全量走 get_plugins
            if is_detail:
                try:
                    order = int(query or "")
                except ValueError:
                    # 纯数字分支之外理论上不会传进来; 转换失败按空结果处理
                    return 0
                plugins = analyzer.get_plugin_by_order(order)
            else:
                plugins = analyzer.get_plugins(query)
            if not plugins:
                return 0

            # 视图层：决定标题 & 计算布局 & 写入JSON
            if is_detail:
                # 数字定位 → 单插件详情页
                display_title = plugins[0].display_name or plugins[0].name
                layout_mode = "plugin_detail"
                # 附加该插件的事件监听器 (含命令式监听); 失败只丢监听区, 不让整页失败
                try:
                    plugins[0].event_nodes = (
                        self.evt_analyzer.get_plugin_event_listeners(plugins[0].name)
                    )
                except Exception as e:
                    logger.warning(f"[HelpTypst] 获取事件监听失败: {e}")
                    plugins[0].event_nodes = []
            else:
                display_title = f'搜索结果: "{query}"' if query else title
                layout_mode = mode
                # 详细指令模式: 为每个插件附加事件监听器
                if layout_mode == "command_detail":
                    for p in plugins:
                        try:
                            p.event_nodes = (
                                self.evt_analyzer.get_plugin_event_listeners(p.name)
                            )
                        except Exception as e:
                            logger.debug(
                                f"[HelpTypst] 获取 {p.name} 的事件监听失败: {e}"
                            )
                            p.event_nodes = []

            final_font_list = self.font_manager.get_render_font_list(font_order)  # 校验

            layout.dump_layout_json(
                plugins=plugins,
                save_path=save_path,
                title=display_title,
                mode=layout_mode,
                prefixes=self.prefixes,
                font_list=final_font_list,
                system_name=persona_name,
            )

            return len(plugins)

        return data_pipeline

    def _build_preview_provider(
        self,
        mode: str,
        query: str | None,
        layout: TypstLayout,
        font_order: list[str],
        persona_name: str,
        cfg: TypstPluginConfig,
    ) -> Callable[[Path], int]:
        """网页预览的数据流构造器 (由 PreviewService 调用)

        分析器按预览合成的 cfg 重建: 屏蔽集/配色等只在预览里改动, 复用插件启动时
        的分析器会拿旧配置过滤插件, 预览图看不到屏蔽项的变化。
        """
        if mode == "command":
            analyzer, title = CommandAnalyzer(self.context, cfg), "AstrBot 指令菜单"
        elif mode == "command_detail":
            analyzer, title = (
                CommandAnalyzer(self.context, cfg),
                "AstrBot 指令菜单(详细)",
            )
        elif mode == "event":
            analyzer, title = EventAnalyzer(self.context, cfg), "AstrBot 事件监听"
        elif mode == "filter":
            analyzer, title = FilterAnalyzer(self.context, cfg), "AstrBot 过滤器分析"
        else:
            raise ValueError(f"不支持的预览模式: {mode}")

        return self._make_data_pipeline(
            analyzer=analyzer,
            title=title,
            mode=mode,
            query=query,
            is_detail=False,
            layout=layout,
            font_order=font_order,
            persona_name=persona_name,
        )

    async def api_preview_options(self) -> Any:
        """插件页 API：返回预览页的全部可调选项"""
        from astrbot.api.web import error_response, json_response

        try:
            data = await asyncio.to_thread(self.preview_service.build_options)
            return json_response(data)
        except Exception as e:
            logger.error(f"[HelpTypst] 读取预览选项失败: {e}", exc_info=True)
            return error_response("读取预览选项失败，请查看插件日志")

    async def api_preview_fonts(self) -> Any:
        """插件页 API：重新扫描字体目录并返回最新可选字体"""
        from astrbot.api.web import error_response, json_response

        try:
            # 与 /typst font 共用同一条扫描链路: 扫描 + 内存 Schema 同步 + 配置清洗
            await asyncio.to_thread(self._refresh_resources)
            data = await asyncio.to_thread(self.preview_service.build_font_state)
            return json_response(data)
        except Exception as e:
            logger.error(f"[HelpTypst] 重新加载字体失败: {e}", exc_info=True)
            return error_response("重新加载字体失败，请查看插件日志")

    async def api_preview_render(self) -> Any:
        """插件页 API：按样式渲染预览图"""
        from astrbot.api.web import error_response, json_response, request

        try:
            payload = await request.json(default={})
        except Exception as e:
            logger.warning(f"[HelpTypst] 解析预览请求失败: {e}")
            return error_response("请求内容解析失败")

        try:
            data = await self.preview_service.render(payload)
            return json_response(data)
        except PreviewError as e:
            return error_response(str(e))
        except Exception as e:
            logger.error(f"[HelpTypst] 预览渲染失败: {e}", exc_info=True)
            return error_response("预览渲染失败，请查看插件日志")

    async def api_preview_apply(self) -> Any:
        """插件页 API：把预览样式写入插件配置并热重载插件"""
        from astrbot.api.web import error_response, json_response, request

        try:
            payload = await request.json(default={})
        except Exception as e:
            logger.warning(f"[HelpTypst] 解析应用配置请求失败: {e}")
            return error_response("请求内容解析失败")

        try:
            plan = await asyncio.to_thread(
                self.preview_service.build_apply_plan, payload
            )
        except PreviewError as e:
            return error_response(str(e))
        except Exception as e:
            logger.error(f"[HelpTypst] 解析待应用样式失败: {e}", exc_info=True)
            return error_response("配置解析失败，请查看插件日志")

        if not plan["changed"]:
            return json_response(
                {
                    "changed": [],
                    "warnings": plan["warnings"],
                    "reload": False,
                    "reload_in_ms": 0,
                }
            )

        try:
            patch = self._build_config_patch(plan)
            await self._save_config_patch(patch)
        except Exception as e:
            logger.error(f"[HelpTypst] 保存预览样式失败: {e}", exc_info=True)
            return error_response("配置保存失败，请查看插件日志")

        logger.info(f"[HelpTypst] 已应用预览样式: {', '.join(plan['changed'])}")
        scheduled = self._schedule_plugin_reload()
        if not scheduled:
            logger.warning(
                "[HelpTypst] 未获取到插件管理器，样式已保存但需手动重载插件后生效"
            )
        return json_response(
            {
                "changed": plan["changed"],
                "warnings": plan["warnings"],
                "reload": scheduled,
                "reload_in_ms": (
                    int(InternalCFG.DELAY_SEND * 1000) if scheduled else 0
                ),
            }
        )

    def _build_config_patch(self, plan: dict[str, Any]) -> dict[str, Any]:
        """把应用计划转成配置补丁：只覆盖计划里的键，其余保持原样"""
        raw: dict[str, Any] = self.config if isinstance(self.config, dict) else {}
        rendering = dict(raw.get("rendering") or {})
        rendering.update(plan["rendering"])
        appearance = dict(raw.get("appearance") or {})
        appearance.update(plan["appearance"])
        if plan["preset_entries"]:
            appearance["presets"] = self._merge_preset_entries(
                appearance.get("presets"),
                plan["preset_entries"],
                plan["enabled_preset"],
            )
        patch: dict[str, Any] = {
            "rendering": rendering,
            "appearance": appearance,
            "hero_header": bool(plan["hero_header"]),
        }
        # 只有面板里明确换了背景图才固定单文件；否则保留原配置（含随机背景）
        if plan["background_path"]:
            patch["header_background"] = plan["background_path"]
        # 屏蔽集分成两个键写入：勾选项与自定义条目各自整体替换
        patch["ignored_plugins"] = list(plan["ignored_plugins"])
        patch["ignored_plugins_custom"] = list(plan["ignored_plugins_custom"])
        # 分类规则由面板整体提供（兜底分类 + 规则列表），未改动时计划里为 None
        category = plan.get("category")
        if category is not None:
            patch["category"] = category
        return patch

    def _merge_preset_entries(
        self,
        raw_presets: Any,
        entries: list[dict[str, Any]],
        enabled_preset: str | None,
    ) -> list[dict[str, Any]]:
        """按面板提交的条目重建 appearance.presets 模板列表。

        - 顺序与面板一致，首条固定取名「自定义」（面板配色改动的落点）
        - 复用原条目的模板字段（__template_key 等），只覆盖名字/颜色/启用开关
        - enabled_preset 对应条目启用，其余取消；为空时全部取消（切回内置预设）
        """
        raw_entries = (
            [item for item in raw_presets if isinstance(item, dict)]
            if isinstance(raw_presets, list)
            else []
        )

        names: list[str] = []
        for index, entry in enumerate(entries):
            name = str(entry.get("name") or "").strip()
            if index == 0:
                name = DefaultCFG.CUSTOM_PRESET_KEY
            elif not name:
                name = f"{DefaultCFG.CUSTOM_PRESET_KEY} {index + 1}"
            names.append(name)

        # 先按名字认领原条目；首条改名后名字对不上，剩余原条目按位置补齐，
        # 这样既保留条目上的其它字段，也不会丢掉用户已有条目
        sources: list[dict[str, Any] | None] = [None] * len(entries)
        used: set[int] = set()
        for index, name in enumerate(names):
            for raw_index, raw in enumerate(raw_entries):
                if raw_index not in used and raw.get("preset_name") == name:
                    sources[index] = raw
                    used.add(raw_index)
                    break
        spare = [raw_index for raw_index in range(len(raw_entries)) if raw_index not in used]
        for index, source in enumerate(sources):
            if source is None and spare:
                sources[index] = raw_entries[spare.pop(0)]

        merged: list[dict[str, Any]] = []
        for index, name in enumerate(names):
            target = (
                dict(sources[index])
                if sources[index] is not None
                else self._preset_entry_template()
            )
            target["preset_name"] = name
            colors = entries[index].get("colors")
            if isinstance(colors, dict):
                for key in DefaultCFG.DEFAULT_COLORS:
                    value = colors.get(key)
                    if isinstance(value, str) and value.strip():
                        target[key] = value.strip()
            target["enabled"] = enabled_preset is not None and name == enabled_preset
            merged.append(target)
        return merged

    def _preset_entry_template(self) -> dict[str, Any]:
        """以 schema 里的预设模板为蓝本，避免手写字段与设置面板脱节"""
        schema = getattr(self.config, "schema", None) or {}
        try:
            defaults = schema["appearance"]["items"]["presets"]["default"]
            if isinstance(defaults, list):
                for item in defaults:
                    if isinstance(item, dict):
                        return dict(item)
        except (KeyError, TypeError):
            # 旧版/残缺 schema 缺 presets 模板时走下方兜底模板, 无需告警
            pass
        template: dict[str, Any] = {
            "__template_key": "standard_theme",
            "preset_name": DefaultCFG.CUSTOM_PRESET_KEY,
            "enabled": True,
        }
        template.update(DefaultCFG.DEFAULT_COLORS)
        return template

    async def _save_config_patch(self, patch: dict[str, Any]) -> None:
        """持久化配置补丁：优先异步保存，旧版本 AstrBot 回落到线程里的同步保存"""
        save_async = getattr(self.config, "save_config_async", None)
        if callable(save_async):
            if not await save_async(patch):
                raise RuntimeError("配置写入被更新的保存请求覆盖")
            return
        save = getattr(self.config, "save_config", None)
        if not callable(save):
            raise RuntimeError("当前 AstrBot 版本不支持保存插件配置")
        try:
            await asyncio.to_thread(save, patch)
        except TypeError:
            # 旧版本 save_config 不接受补丁参数：先合并到内存配置再落盘
            for key, value in patch.items():
                current = self.config.get(key)
                if isinstance(current, dict) and isinstance(value, dict):
                    merged = dict(current)
                    merged.update(value)
                    self.config[key] = merged
                else:
                    self.config[key] = value
            await asyncio.to_thread(save)

    def _schedule_plugin_reload(self) -> bool:
        """延迟重载插件：先让 HTTP 响应返回，避免请求被重载过程打断"""
        pm = getattr(self.context, "_star_manager", None)
        if pm is None:
            return False
        plugin_name = getattr(self, "name", None) or self.plugin_dir.name
        # 字体未变化，重载的卸载阶段无需再全盘扫描
        self._skip_rescan_on_terminate = True
        asyncio.create_task(self._safe_reload(pm, plugin_name))
        return True

    async def _cleanup_task(self, files: list[Path]):
        """异步清理任务"""
        await asyncio.sleep(InternalCFG.DELAY_SEND)
        for p in files:
            try:
                if p.exists():
                    p.unlink()
            except Exception as e:
                logger.warning(f"[HelpTypst] 临时文件清理失败 {p}: {e}")

    def _init_prefixes(self, context: Context):
        """唤醒词"""
        try:
            global_config = context.get_config()
            raw = global_config.get("wake_prefix", ["/"])
            self.prefixes = [raw] if isinstance(raw, str) else list(raw)
        except Exception as e:
            logger.warning(f"[HelpTypst] 获取唤醒词失败，使用默认值 '/': {e}")
            self.prefixes = ["/"]

    def _parse_search_query(self, raw_query: str) -> str | None:
        """解析 `s <关键词>` 搜索子命令: 命中返回关键词, 否则返回 None(不搜索)"""
        query = raw_query.strip()
        if not query or query == "s":
            return None
        if query.startswith("s "):
            keyword = query[2:].strip()
            return keyword or None
        return None

    def _parse_menu_query(self, raw_query: str) -> tuple[str | None, bool]:
        """解析参数: 返回 (搜索关键词, 是否详情页)

        - `s <关键词>` → 搜索模式
        - `<数字>`     → 指定插件详情页
        - 空/其它      → 完整菜单
        """
        query = raw_query.strip()
        if not query:
            return None, False
        if query.isdigit():
            return query, True
        return self._parse_search_query(query), False

    @filter.command("helps", alias={"功能", "菜单", "帮助"})
    async def show_menu(self, event: AstrMessageEvent, query: GreedyStr):
        """显示指令菜单"""
        keyword, is_detail = self._parse_menu_query(query)
        async for r in self._handle_request(
            event, self.cmd_analyzer, "AstrBot 指令菜单", "command", keyword, is_detail
        ):
            yield r

    @filter.command("helpss", alias={"详细帮助", "详细功能", "详细菜单"})
    async def show_menu_detail(self, event: AstrMessageEvent, query: GreedyStr):
        """显示详细指令菜单 (含指令标签组)"""
        keyword, is_detail = self._parse_menu_query(query)
        async for r in self._handle_request(
            event,
            self.cmd_analyzer,
            "AstrBot 指令菜单(详细)",
            "command_detail",
            keyword,
            is_detail,
        ):
            yield r

    @filter.command("events", alias={"事件", "事件监听"})
    async def show_events(self, event: AstrMessageEvent, query: GreedyStr):
        """显示事件监听列表"""
        keyword = self._parse_search_query(query)
        async for r in self._handle_request(
            event, self.evt_analyzer, "AstrBot 事件监听", "event", keyword
        ):
            yield r

    @filter.command("filters", alias={"过滤器", "过滤"})
    async def show_filters(self, event: AstrMessageEvent, query: GreedyStr):
        """显示过滤器详情"""
        keyword = self._parse_search_query(query)
        async for r in self._handle_request(
            event, self.flt_analyzer, "AstrBot 过滤器分析", "filter", keyword
        ):
            yield r

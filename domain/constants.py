from enum import Enum

from astrbot.core.star.star_handler import EventType


class _EventTypeLabelMap(dict[EventType, str]):
    """EventType → 事件监听分组标题

    未知事件类型统一回落「其他事件」: 上游会随版本新增 EventType (Agent/Tool 类),
    把英文枚举名直接展示给用户没有意义。覆盖 get() 的默认值, 消费方无需改动。
    """

    FALLBACK: str = "其他事件"

    def get(self, key: object, default: str | None = None) -> str:
        return super().get(key, self.FALLBACK)


# 事件类型映射表: (EventType 成员名, 中文分组标题)
# 按成员名动态取值, 低版本 AstrBot 缺失的成员自动跳过, 避免 import 期 AttributeError
_EVENT_TYPE_LABELS: tuple[tuple[str, str], ...] = (
    ("OnAstrBotLoadedEvent", "系统启动 (Loaded)"),
    ("OnPlatformLoadedEvent", "平台就绪 (Platform)"),
    ("AdapterMessageEvent", "消息监听 (Message)"),
    ("OnWaitingLLMRequestEvent", "等待 LLM 请求 (Wait-LLM)"),
    ("OnLLMRequestEvent", "LLM 请求前 (Pre-LLM)"),
    ("OnLLMResponseEvent", "LLM 响应后 (Post-LLM)"),
    ("OnAgentBeginEvent", "Agent 开始 (Agent)"),
    ("OnAgentDoneEvent", "Agent 完成 (Agent-Done)"),
    ("OnDecoratingResultEvent", "消息修饰 (Decorate)"),
    ("OnCallingFuncToolEvent", "函数工具调用 (Calling-Tool)"),
    ("OnUsingLLMToolEvent", "工具调用请求 (Using-Tool)"),
    ("OnLLMToolRespondEvent", "工具返回 (Tool-Respond)"),
    ("OnAfterMessageSentEvent", "发送回执 (Sent)"),
    ("OnPluginErrorEvent", "插件异常 (Plugin-Error)"),
    ("OnPluginLoadedEvent", "插件加载 (Plugin-Loaded)"),
    ("OnPluginUnloadedEvent", "插件卸载 (Plugin-Unloaded)"),
)


def _build_event_type_map() -> _EventTypeLabelMap:
    """构建事件类型映射 (成员缺失时跳过, 兼容低版本 AstrBot)"""
    mapping = _EventTypeLabelMap()
    for attr_name, label in _EVENT_TYPE_LABELS:
        event_type = getattr(EventType, attr_name, None)
        if isinstance(event_type, EventType):
            mapping[event_type] = label
    return mapping


class InternalCFG:
    """内部常量"""

    # 映射
    CACHE_FILES: dict[str, str] = {
        "command": "cache_menu_command",
        "command_detail": "cache_menu_command_detail",
        "event": "cache_menu_event",
        "filter": "cache_menu_filter",
    }

    EVENT_TYPE_MAP: _EventTypeLabelMap = _build_event_type_map()

    # 会引起布局变动的配置项 → 缓存失效
    CACHE_SENSITIVE_CONFIGS: list[str] = [
        "giant_threshold",
        "split_height",
        # 直接决定长图切片结果 (是否切、切成几张), 改动后必须重编
        "webp_limit",
        # 换发送格式 = 换产物扩展名, 旧格式文件必须让位
        "output_format",
        "ppi",
        # 页宽与单列阈值直接决定版式与出图像素, 改动后必须重编
        "page_width",
        "single_column_threshold",
        # 插件行双行模式改变行高与文本排布, 同样影响出图
        "plugin_two_lines",
        "ignored_plugins",
        # 自定义屏蔽名与上面的勾选项取并集后生效, 漏登记会让改名后的屏蔽不刷新
        "ignored_plugins_custom",
        "effective_colors",
        "header_background",
        "background_dir",
        "background_random",
        "hero_header",
        "category",
    ]

    # 发送图片格式 → 产物扩展名 (扩展名参与缓存文件命名, 换格式即换文件名)
    FORMAT_EXT: dict[str, str] = {
        "webp": ".webp",
        "png": ".png",
        "jpeg": ".jpg",
    }
    # 各格式单张边长上限: WebP 是硬限制 16383; PNG/JPEG 理论更大, 但再高 Pillow 解码/编码内存会失控,
    # 因此只放开到实用值, 超出部分仍按切片处理
    FORMAT_MAX_SIDE: dict[str, int] = {
        "webp": 16383,
        "png": 32000,
        "jpeg": 65500,
    }
    # 顶层相邻 block 之间的段间距 (Typst par.spacing = 1.2em, 正文 10pt)
    # 模板里用 measure 现算, 这里保存同一数值供图片裁剪对齐
    FLOW_GAP_PT = 12.0

    # 默认设计页宽: 三列布局 (事件/过滤器外栏、卡片内功能块/指令标签) 按该宽度排定,
    # 页宽再窄就退回两列, 避免每列被压到放不下标签/描述
    DESIGN_PAGE_WIDTH: float = 830.0

    # 头部背景图候选扩展名 (扫描背景目录时使用, 缓存文件按前缀排除)
    # 仅保留 Typst 可解码的栅格格式; 新增格式前先确认 Typst 支持
    BACKGROUND_IMAGE_EXTS: tuple[str, ...] = (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
    )
    # 自动扫描时排除的缓存文件前缀
    BACKGROUND_IMAGE_EXCLUDE_PREFIXES: tuple[str, ...] = ("cache_", "temp_")

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"
    # 默认背景图目录 (数据目录下的子目录, 与字体目录一致)
    NAME_BACKGROUND_DIR: str = "backgrounds"

    # ---- 网页实时预览 (pages/preview) ----
    # 预览默认按插件设置里的清晰度渲染, 可在面板里临时调低换取更短等待时间
    PREVIEW_SUPPORTED_MODES: tuple[str, ...] = (
        "command",
        "command_detail",
        "event",
        "filter",
    )
    PREVIEW_MIN_PPI: float = 72.0
    PREVIEW_MAX_PPI: float = 384.0
    # 渲染用测试精度：只决定预览渲染分辨率，调低更快，不写回正式配置
    PREVIEW_TEST_PPI: float = 144.0
    PREVIEW_MIN_PAGE_WIDTH: float = 360.0
    PREVIEW_MAX_PAGE_WIDTH: float = 1200.0
    # 预览的分页高度默认跟随插件配置，保证预览与正式发图的分页位置一致；
    # 上限取配置项全范围，实际值再按输出格式的单图上限收敛
    PREVIEW_MIN_SPLIT_HEIGHT: int = 1000
    PREVIEW_MAX_SPLIT_HEIGHT: int = 65500
    # 实测 40 个插件最多 4 页, 再多只增加 base64 体积
    PREVIEW_MAX_PAGES: int = 4
    PREVIEW_MAX_QUERY_LEN: int = 80
    # 单次编译约 1.1~1.6s, 防抖太短会让拖动过程排起长队
    PREVIEW_DEBOUNCE_MS: int = 550
    # 预览缓存: 同一套样式反复调整时直接复用图片, 避免重复编译
    PREVIEW_CACHE_TTL: float = 600.0
    PREVIEW_CACHE_MAX_ENTRIES: int = 12
    PREVIEW_CACHE_MAX_BYTES: int = 32 * 1024 * 1024
    # 自定义模板: 预览页配色列表可增删改的条目; 首条固定名「自定义」并对应 conf presets 首条
    PREVIEW_CUSTOM_PRESET_MAX: int = 8
    PREVIEW_PRESET_NAME_MAX: int = 20

    # 预览页分类编辑器: 与配置面板 category 一一对应, 但只做预览态校验, 落盘仍走 category
    PREVIEW_CATEGORY_RULES_MAX: int = 30
    PREVIEW_CATEGORY_NAME_MAX: int = 16
    PREVIEW_CATEGORY_KEYWORD_MAX: int = 24
    PREVIEW_CATEGORY_KEYWORDS_MAX: int = 60
    # 热词提取: 统计所有插件「描述 + 插件名 + 显示名」里重复出现的 2~3 字词,
    # 只保留出现次数 >= MIN_COUNT 的词, 避免只出现一次的片段把列表塞满
    PREVIEW_HOT_WORD_LIMIT: int = 48
    PREVIEW_HOT_WORD_MIN_COUNT: int = 2
    PREVIEW_HOT_WORD_MIN_LEN: int = 2
    PREVIEW_HOT_WORD_MAX_LEN: int = 3
    # 前端要按关键词算命中插件的数量, 单条文案过长会撑大 options 响应, 截断即可
    PREVIEW_MATCH_TEXT_LIMIT: int = 400
    # 高频词里没有信息量的通用词: 不排除的话「插件」「功能」「支持」会霸榜
    PREVIEW_HOT_WORD_STOPWORDS: frozenset[str] = frozenset(
        {
            "插件",
            "功能",
            "支持",
            "使用",
            "可以",
            "进行",
            "提供",
            "一个",
            "以及",
            "通过",
            "基于",
            "实现",
            "自动",
            "用户",
            "消息",
            "命令",
            "指令",
            "配置",
            "默认",
            "需要",
            "时候",
            "目前",
            "已经",
            "这个",
            "那个",
            "我们",
            "你们",
            "他们",
            "自己",
            "其他",
            "如果",
            "因为",
            "所以",
            "但是",
            "而且",
            "然后",
            "还是",
            "就是",
            "没有",
            "不能",
            "不会",
            "可能",
            "一些",
            "什么",
            "怎么",
            "如何",
            "非常",
            "简单",
            "方便",
            "快速",
            "高效",
            "强大",
            "完善",
            "丰富",
            "任意",
            "所有",
            "每个",
            "不同",
            "版本",
            "更新",
            "新增",
            "修复",
            "优化",
            "相关",
            "内容",
            "信息",
            "方法",
            "方式",
            "问题",
            "注意",
            "建议",
            "帮助",
            "文档",
            "示例",
            "参数",
            "返回值",
            "接口",
            "调用",
            "监听",
            "触发",
            "事件",
            "类型",
            "名称",
            "机器人",
            "群聊",
            "好友",
            "发送",
            "接收",
            # 英文技术词: 每个插件 ID 都带, 拿来当关键词会命中全部插件
            "astrbot",
            "plugin",
            "plugins",
            "bot",
            "处理",
            "获取",
            "设置",
            "开启",
            "关闭",
            "是否",
            "其中",
            "例如",
            "比如",
            "包括",
            "用于",
            "用来",
            "兼容",
            "适配",
            "版本号",
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "your",
            "you",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "not",
            "but",
            "can",
            "will",
            "all",
            "any",
            "use",
            "used",
            "using",
            "via",
            "into",
            "out",
            "new",
            "old",
            "one",
            "two",
            "also",
            "more",
            "most",
            "such",
            "when",
            "then",
            "than",
            "them",
            "they",
            "its",
            "our",
            "their",
            "plugin",
            "plugins",
            "astrbot",
            "bot",
            "api",
            "http",
            "https",
            "www",
            "com",
            "github",
            "gitee",
            "readme",
            "support",
            "supported",
            "based",
            "built",
            "easy",
            "simple",
            "fast",
            "powerful",
            "feature",
            "features",
            "version",
            "update",
            "config",
            "configuration",
            "command",
            "commands",
            "message",
            "messages",
            "user",
            "users",
            "data",
            "system",
            "service",
            "services",
            "default",
            "auto",
            "automatically",
            "json",
            "yaml",
            "python",
            "async",
        }
    )

    # 时序
    DELAY_SEND: float = 1

    # 分类 (指令模式 /helps) 相关
    # 兜底分类名: 配置缺失/异常时的最终保底 (正常运行时使用 DefaultCFG.DEFAULT_CATEGORY_FALLBACK,
    # 用户可在设置面板通过 category.fallback 自定义, 详见 domain/config.py 的 CategoryConfig)
    CATEGORY_FALLBACK: str = "其他"
    # 默认分类关键词映射已迁移至 DefaultCFG.DEFAULT_CATEGORY_KEYWORDS (设置面板 category.rules 的预置默认值)
    # 两列高度估算系数 (pt): 只参与 utils/view.py 的分列决策, 不参与渲染。
    # 按 base.typ 的排版 (830pt 页宽、分类卡内边距、chip 字号) 折算, 并用真实渲染结果校准;
    # 页宽 / 字号 / 模板结构变化后需重新校准 (详见 utils/view.py 的 _estimate_category_height)。
    EST_CATEGORY_BASE: float = 42.0  # 指令模式: 分类卡片头部 + 列表内边距
    EST_CATEGORY_STACK_GAP: float = 12.0  # 分类卡片之间的 stack spacing
    EST_PLUGIN_ROW: float = 26.0  # 指令模式: 单个插件行 (含行距)
    EST_PLUGIN_NAME_WIDTH: float = 200.0  # 指令模式: 插件名可用宽度, 超出折行
    EST_PLUGIN_NAME_LINE: float = 14.0  # 插件名每多折一行的增量
    EST_DETAIL_CATEGORY_BASE: float = 50.0  # 详细模式: 分类卡片固定开销
    EST_DETAIL_PLUGIN_ROW: float = 40.0  # 详细模式: 插件条目头部行
    EST_DETAIL_CAPABILITY_BLOCK: float = 14.0  # 能力区: 分割线上下的留白
    EST_DETAIL_SECTION_LABEL: float = 20.0  # Commands / Listeners 小节标题
    EST_DETAIL_GROUP_OVERHEAD: float = 24.0  # 指令组容器: 内边距 + 组名
    EST_DETAIL_CHIP_ROW: float = 19.0  # 单行 chip 高度 (含行距)
    EST_DETAIL_CHIP_WIDTH: float = 356.0  # 插件条目内 chip 可用行宽
    EST_DETAIL_GROUP_CHIP_WIDTH: float = 350.0  # 指令组内 chip 可用行宽
    EST_CHIP_PADDING: float = 12.0  # chip 左右内边距 + 边框
    EST_CHIP_GAP: float = 3.0  # 相邻 chip 间距

    # 禁用插件灰化色板 (主题无关的固定值, 供 /helps 指令菜单灰化展示)
    DISABLED_COLORS: dict[str, str] = {
        "disabled_card_bg": "#F5F5F5",  # 禁用插件卡片背景 (极浅灰)
        "disabled_card_border": "#E7E7E7",  # 禁用插件卡片边框 (低对比灰)
        "disabled_badge_bg": "#D6C9CC",  # 编号徽章背景 (低饱和灰粉)
        "disabled_badge_text": "#9B8A8E",  # 编号徽章文字 (深灰粉, 保证可读)
        "disabled_name": "#B8B8B8",  # 插件名称 (浅灰)
        "disabled_cmd": "#C8C8C8",  # 命令名称/次级文本 (更浅灰)
        "disabled_icon": "#B9A5A8",  # 禁用图标 (圆圈 + 斜杠)
    }
    # 深色主题下的禁用灰化色板: 浅灰底在暗色卡片上会变成刺眼白块, 改为「比卡片略亮的低饱和灰紫」
    DISABLED_COLORS_DARK: dict[str, str] = {
        "disabled_card_bg": "#2A2240",  # 禁用插件卡片背景 (略亮于卡片)
        "disabled_card_border": "#3A3152",  # 禁用插件卡片边框
        "disabled_badge_bg": "#3B3155",  # 编号徽章背景
        "disabled_badge_text": "#A79BC2",  # 编号徽章文字
        "disabled_name": "#9A8FB5",  # 插件名称
        "disabled_cmd": "#938AAE",  # 命令名称/次级文本
        "disabled_icon": "#8A80A4",  # 禁用图标
    }


class DefaultCFG:
    """兜底: 配置默认值"""

    # 1. 渲染限制
    LIMIT_TASK: int = 2  # 最大并发编译数
    LIMIT_GIANT: int = 1500
    LIMIT_WEBP: int = 16383
    LIMIT_SIDE: int = 16000
    # 发送图片格式: webp 体积最小, png 无损, jpeg 体积接近 webp
    OUTPUT_FORMAT: str = "webp"
    OUTPUT_FORMATS: tuple[str, ...] = ("webp", "png", "jpeg")
    # 单张高度上限/切片高度的配置上限: 按最大的 JPEG 放开, 实际执行时再按所选格式收敛
    MAX_LIMIT_SIDE: int = 65500
    # 与 _conf_schema.json 的 ppi 默认值一致: 144 / 180 都是历史默认值,
    # 当前面板与兜底统一为 256
    LIMIT_PPI: float = 256.0

    # 1.1 配置值收敛区间 (防御手工改坏的配置; 与设置面板 slider 范围对齐)
    MIN_PPI: float = 72.0
    # 上限受 WebP 单边 16383px 与 Pillow 像素上限约束: 600pt 页宽下 384ppi 已接近单张上限
    MAX_PPI: float = 384.0
    MIN_SPLIT_HEIGHT: int = 200  # image.py 按此高度切片, 过小无意义, 0 会除零
    # 页面总宽度 (pt): 越窄同 PPI 下出图越窄、文字相对越大, 聊天窗口里更易读
    LIMIT_WIDTH: float = 600.0
    # 页面宽度低于该值时改单列 (两列/三列在窄页宽下会挤成一团)
    LIMIT_SINGLE_COLUMN_THRESHOLD: float = 480.0
    # 360 是实测下限: Hero 统计卡 3×76pt + 26pt 左偏移占 274pt, 页面再窄 (≈330pt 以下) 就会溢出
    MIN_PAGE_WIDTH: float = 360.0
    MAX_PAGE_WIDTH: float = 1200.0
    # 插件双行模式: 英文 ID 移到中文名下方, 单行更窄, 窄页宽下不易被截断
    PLUGIN_TWO_LINES: bool = True
    MIN_WEBP_LIMIT: int = 1000
    MIN_GIANT: int = 100
    MAX_GIANT: int = 3000
    # 超时的可编辑范围只有这一份: 设置面板 slider、网页预览 limit 与配置读取夹紧
    # 都取这里, 三处不一致时会出现「面板存得进、预览改不动」的错位
    MIN_TIMEOUT_ANALYSIS: float = 3.0
    MIN_TIMEOUT_COMPILE: float = 3.0
    MAX_TIMEOUT: float = 60.0
    MIN_CONCURRENCY: int = 1
    MAX_CONCURRENCY: int = 10

    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0

    # 3. 全局字体优先级 (appearance.font_order 缺省值)
    # 注意: 表情字体 (EMOJI_FONT) 不在此列, 由渲染时固定追加, 无需用户选择
    DEFAULT_FONT_ORDER: list[str] = ["LXGW Neo XiHei"]

    # 固定表情字体: 始终追加到最终字体列表末尾, 用于渲染 emoji 字形
    # 不出现在配置面板的字体选择项中 (用户无需也不应选择它)
    EMOJI_FONT: str = "Noto Color Emoji"

    # 系统字体目录映射 (扫描时并入选择框选项; ~ 在代码中展开)
    SYSTEM_FONT_DIRS: tuple[str, ...] = (
        # Windows
        "C:/Windows/Fonts",
        # macOS
        "/System/Library/Fonts",
        "/Library/Fonts",
        "~/Library/Fonts",
        # Linux
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "~/.fonts",
        "~/.local/share/fonts",
    )

    # 4. 过滤设置
    # config.py 负责 list → set
    # 只预置一定会出现在插件列表里的项 (本体 / 内置指令组 / 本插件自己):
    # 勾选框只列注册表中的插件, 不在列表里的名字预置进来会变成看不见的勾选
    IGNORED_PLUGINS: set[str] = {
        "astrbot",
        "builtin_commands",
        "astrbot_plugin_help_panel_typst",
    }
    # 其余内置插件由 AstrBot 本体直接承载、不注册为插件, 连同本插件旧名一起
    # 放进自定义条目: 那里是纯文本, 不依赖插件列表
    IGNORED_PLUGINS_CUSTOM: set[str] = {
        "session_controller",
        "astrbot-web-searcher",
        "astrbot-python-interpreter",
        "astrbot-reminder",
        "astrbot_plugin_help_typst",
    }

    # 5. 内置主题预设 (preset_name → 完整配色)
    # 每个配色字典含三类键:
    #   brand_*    : 品牌色板 (主色/结构色/背景/边框等, 13 个, 供指令菜单使用)
    #   cat_slot_N : 通用分类色槽 (0~9, 分类卡片标题栏取色, 分类规则按槽位绑定; 0 为兜底)
    #   c_*        : 通用颜色 (event/filter/detail 视图使用)

    # --- Forest 主题: 墨竹 (森系墨绿 × 竹青 × 琥珀, 浅色) ---
    FOREST_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#3F7D5B",  # 竹青 · 第一主色
        "brand_navy": "#2C4638",  # 墨绿 · 结构色
        "brand_mint": "#A8D5BC",  # 嫩竹 · 高光
        "brand_cream": "#E9D8A0",  # 米黄 · 强调
        "brand_gold": "#9E7222",  # 琥珀 · 暖强调
        "brand_blush": "#CBE3D5",  # 浅苔 · 柔和辅助
        "brand_ink": "#1E2B24",  # 深墨
        "brand_gray": "#6F8177",  # 灰绿 · 次级文字/disabled
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#D9E5DC",  # 卡片边框
        "brand_soft": "#E4EEE7",  # 插件行边框
        "brand_ghost": "#F0F5F1",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底分类(其他) 默认色, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#7C8C82",  # 灰绿 · 兜底「其他」
        "cat_slot_1": "#3F7D5B",  # 竹青 · AI
        "cat_slot_2": "#A87C22",  # 琥珀 · 查询
        "cat_slot_3": "#2F7E86",  # 深青 · 工具
        "cat_slot_4": "#23483A",  # 墨绿 · 管理
        "cat_slot_5": "#5E8F42",  # 橄榄 · 娱乐
        "cat_slot_6": "#4E7FA8",  # 湖蓝 · 消息
        "cat_slot_7": "#A85A38",  # 陶土 · 调试
        "cat_slot_8": "#C9A227",  # 金 · 备用
        "cat_slot_9": "#1E2B24",  # 深墨 · 备用
        # 通用颜色
        "page_fill": "#F4F7F2",
        "c_plugin_name": "#2C4638",
        "c_plugin_id": "#6F8177",
        "c_group_title": "#2C4638",
        "c_bullet": "#3F7D5B",
        "c_event_icon": "#9E7222",
        "c_leaf_text": "#26362C",
        "c_desc_text": "#6F8177",
        "c_group_bg": "#E9F1EB",
        "c_rich_bg": "#FFFFFF",
        "c_box_bg": "#F0F5F1",
        "c_box_stroke": "#E4EEE7",
        "c_text_primary": "#2C4638",
        "c_regex_bg": "#FBF3E2",
        "c_regex_text": "#8A6A1E",
        "c_regex_icon": "#9E7222",
        "c_tag_admin": "#2F7E86",
        "c_tag_event": "#9E7222",
        "c_tag_mcp": "#2C4638",
        "c_tag_id": "#4E6B5A",
        "c_ver_bg": "#E9F1EB",
        "c_ver_text": "#2C4638",
        "c_prio_bg": "#F7EFD9",
        "c_prio_text": "#8A6A1E",
        "c_highlight_bg": "#E9D8A0",
        "c_highlight_text": "#1E2B24",
        "c_on_light": "#1E2B24",
    }
    # --- Sunset 主题: 落日 (落日橙 × 暖棕 × 琥珀, 浅色) ---
    SUNSET_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#D9502C",  # 落日橙 · 第一主色
        "brand_navy": "#5C3A28",  # 暖棕 · 结构色
        "brand_mint": "#F2BFA0",  # 浅桃 · 高光
        "brand_cream": "#F7D08A",  # 沙黄 · 强调
        "brand_gold": "#B07518",  # 琥珀 · 暖强调
        "brand_blush": "#F8D9C4",  # 藕粉 · 柔和辅助
        "brand_ink": "#3B2318",  # 深褐
        "brand_gray": "#8C7663",  # 灰棕 · 次级文字/disabled
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#F1DFD2",  # 卡片边框
        "brand_soft": "#F8EBE1",  # 插件行边框
        "brand_ghost": "#FDF4ED",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底分类(其他) 默认色, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#8C7663",  # 灰棕 · 兜底「其他」
        "cat_slot_1": "#D9502C",  # 落日橙 · AI
        "cat_slot_2": "#C4841C",  # 琥珀 · 查询
        "cat_slot_3": "#2E7F86",  # 深青 · 工具
        "cat_slot_4": "#6E2A1C",  # 深砖 · 管理
        "cat_slot_5": "#D2557E",  # 胭脂 · 娱乐
        "cat_slot_6": "#9A8A2E",  # 橄榄金 · 消息
        "cat_slot_7": "#7E3A6E",  # 梅紫 · 调试
        "cat_slot_8": "#E8A33D",  # 橙金 · 备用
        "cat_slot_9": "#3B2318",  # 深褐 · 备用
        # 通用颜色
        "page_fill": "#FFF8F1",
        "c_plugin_name": "#5C3A28",
        "c_plugin_id": "#8C7663",
        "c_group_title": "#5C3A28",
        "c_bullet": "#D9502C",
        "c_event_icon": "#B07518",
        "c_leaf_text": "#3B2318",
        "c_desc_text": "#8C7663",
        "c_group_bg": "#FBEEDF",
        "c_rich_bg": "#FFFFFF",
        "c_box_bg": "#FDF4ED",
        "c_box_stroke": "#F8EBE1",
        "c_text_primary": "#5C3A28",
        "c_regex_bg": "#FDF0E2",
        "c_regex_text": "#9A5A12",
        "c_regex_icon": "#B07518",
        "c_tag_admin": "#A93B5B",
        "c_tag_event": "#B07518",
        "c_tag_mcp": "#5C3A28",
        "c_tag_id": "#7E5A44",
        "c_ver_bg": "#FBEEDF",
        "c_ver_text": "#5C3A28",
        "c_prio_bg": "#FCEFD7",
        "c_prio_text": "#9A5A12",
        "c_highlight_bg": "#F7D08A",
        "c_highlight_text": "#3B2318",
        "c_on_light": "#3B2318",
    }
    # --- Amethyst 主题: 夜鸢 (深紫 × 霓虹紫 × 金, 深色) ---
    AMETHYST_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#A78BFA",  # 霓虹紫 · 第一主色
        "brand_navy": "#E4DCF5",  # 浅紫白 · 主文字色 (深底用浅色)
        "brand_mint": "#9BE3D8",  # 薄荷青 · 高光
        "brand_cream": "#F5D98B",  # 暖黄 · 强调
        "brand_gold": "#FFC94D",  # 金 · 暖强调
        "brand_blush": "#C9B6F5",  # 浅紫 · 柔和辅助
        "brand_ink": "#EFEAF9",  # 正文文字 (浅色)
        "brand_gray": "#9A8FB5",  # 灰紫 · 次级文字
        "brand_card": "#241C33",  # 卡片背景 (深)
        "brand_border": "#362A4C",  # 卡片边框
        "brand_soft": "#2C2340",  # 插件行边框
        "brand_ghost": "#1F1830",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底分类(其他) 默认色, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#6F6590",  # 灰紫 · 兜底「其他」
        "cat_slot_1": "#8A6BE0",  # 霓虹紫 · AI
        "cat_slot_2": "#FFC94D",  # 金 · 查询
        "cat_slot_3": "#3FA396",  # 青绿 · 工具
        "cat_slot_4": "#3B2E63",  # 深靛 · 管理
        "cat_slot_5": "#C25AAE",  # 品红 · 娱乐
        "cat_slot_6": "#3E93A3",  # 蓝青 · 消息
        "cat_slot_7": "#D06A3C",  # 暖橙 · 调试
        "cat_slot_8": "#FFC94D",  # 金 · 备用
        "cat_slot_9": "#B9A7E8",  # 浅紫 · 备用
        # 通用颜色
        "page_fill": "#191423",
        "c_plugin_name": "#E4DCF5",
        "c_plugin_id": "#9A8FB5",
        "c_group_title": "#E4DCF5",
        "c_bullet": "#A78BFA",
        "c_event_icon": "#FFC94D",
        "c_leaf_text": "#EFEAF9",
        "c_desc_text": "#9A8FB5",
        "c_group_bg": "#241C33",
        "c_rich_bg": "#241C33",
        "c_box_bg": "#1F1830",
        "c_box_stroke": "#362A4C",
        "c_text_primary": "#E4DCF5",
        "c_regex_bg": "#2C2340",
        "c_regex_text": "#F5D98B",
        "c_regex_icon": "#FFC94D",
        "c_tag_admin": "#9BE3D8",
        "c_tag_event": "#FFC94D",
        "c_tag_mcp": "#A78BFA",
        "c_tag_id": "#9A8FB5",
        "c_ver_bg": "#2C2340",
        "c_ver_text": "#9BE3D8",
        "c_prio_bg": "#2C2340",
        "c_prio_text": "#F5D98B",
        "c_highlight_bg": "#4E3F80",
        "c_highlight_text": "#FFFFFF",
        "c_on_light": "#1A1428",
    }
    # --- zhenxun 主题: 柔和马卡龙粉彩 ---
    ZHENXUN_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#F36F88",  # 粉 · 第一主色
        "brand_navy": "#3A3A3A",  # 结构色 · 深灰
        "brand_mint": "#F7C8D0",  # 浅粉
        "brand_cream": "#FADE86",  # 奶油黄
        "brand_gold": "#FFB84D",  # 橙
        "brand_blush": "#E1BEE7",  # 浅紫
        "brand_ink": "#2B2B2B",  # 深色
        "brand_gray": "#9E9E9E",  # 灰 · 次级文字/disabled
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#ECE9E4",  # 卡片边框
        "brand_soft": "#F0EDE8",  # 插件行边框
        "brand_ghost": "#F6F5F3",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#4DB5AD",
        "cat_slot_1": "#F16B86",
        "cat_slot_2": "#A8D77A",
        "cat_slot_3": "#FFB84D",
        "cat_slot_4": "#B45BC5",
        "cat_slot_5": "#4DBCE8",
        "cat_slot_6": "#E97878",
        "cat_slot_7": "#F36F88",
        "cat_slot_8": "#E1BEE7",
        "cat_slot_9": "#FADE86",
        # 通用颜色
        "page_fill": "#FAF9F7",
        "c_plugin_name": "#0d47a1",
        "c_plugin_id": "#546e7a",
        "c_group_title": "#6a1b9a",
        "c_bullet": "#F36F88",
        "c_event_icon": "#ffc72c",
        "c_leaf_text": "#37474f",
        "c_desc_text": "#9e9e9e",
        "c_group_bg": "#f3e5f5",
        "c_rich_bg": "#fcfcfc",
        "c_box_bg": "#f6f5f3",
        "c_box_stroke": "#ece9e4",
        "c_text_primary": "#2b2b2b",
        "c_regex_bg": "#fff3e0",
        "c_regex_text": "#e65100",
        "c_regex_icon": "#f57c00",
        "c_tag_admin": "#c62828",
        "c_tag_event": "#f57c00",
        "c_tag_mcp": "#00695c",
        "c_tag_id": "#283593",
        "c_ver_bg": "#e3f2fd",
        "c_ver_text": "#1565c0",
        "c_prio_bg": "#e8eaf6",
        "c_prio_text": "#283593",
        "c_highlight_bg": "#ffeb3b",
        "c_highlight_text": "#000000",
        "c_on_light": "#3A3A3A",
    }

    # 预设注册表 (preset_name → 配色), 供 config.py 内置注册
    PRESETS: dict[str, dict[str, str]] = {
        "zhenxun": ZHENXUN_COLORS,
        "Forest": FOREST_COLORS,
        "Sunset": SUNSET_COLORS,
        "Amethyst": AMETHYST_COLORS,
    }

    # 预设中文显示名: 配置面板下拉框与预览页共用, 避免两处各写一份导致改名后对不上
    PRESET_LABELS: dict[str, str] = {
        "zhenxun": "真寻",
        "Forest": "墨竹",
        "Sunset": "落日",
        "Amethyst": "夜鸢",
    }

    # 6. 插件分类规则 (指令模式 /helps 分类卡片)
    # 默认分类关键词映射: 作为设置面板 category.rules 的预置默认值导入, 用户可自由增删改。
    # 匹配优先级: 名称/展示名命中优先于简介; 同层级下关键词越长越优先, 长度相同按列表顺序;
    # 全部未命中时归入兜底分类 (详见 CategoryConfig.match)。
    DEFAULT_CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "调试": [
            "调试",
            "日志",
            "诊断",
            "排障",
            "重启",
            "部署",
            "运维",
            "debug",
            "monitor",
            "trace",
            "profiler",
            "dev",
            "log",
            "restart",
        ],
        "管理": [
            "群管",
            "群管理",
            "禁言",
            "踢人",
            "审核",
            "违禁",
            "黑名单",
            "风控",
            "防撤回",
            "撤回",
            "管理员",
            "权限",
            "人机验证",
            "admin",
            "groupadmin",
        ],
        "娱乐": [
            "娱乐",
            "游戏",
            "点歌",
            "音乐",
            "表情包",
            "表情",
            "梗图",
            "笑话",
            "复读",
            "打卡",
            "签到",
            "抽卡",
            "运势",
            "塔罗",
            "占卜",
            "骰子",
            "相册",
            "互动",
            "随机",
            "干饭",
            "game",
            "music",
        ],
        "消息": [
            "消息",
            "转发",
            "防抖",
            "唤醒",
            "上下文",
            "主动",
            "艾特",
            "回复",
            "引用",
            "接话",
            "插话",
            "拟人",
            "人设",
            "记忆",
            "长期记忆",
            "订阅",
            "推送",
            "通知",
            "提醒",
            "播报",
            "输出",
            "rss",
            "news",
            "feed",
            "recall",
        ],
        "AI": [
            "llm",
            "大模型",
            "模型",
            "gpt",
            "deepseek",
            "gemini",
            "claude",
            "openai",
            "生图",
            "绘图",
            "文生图",
            "绘画",
            "图像",
            "画图",
            "diffusion",
            "智能体",
            "agent",
            "autogen",
            "对话",
            "ai",
            "智能",
        ],
        "查询": [
            "查询",
            "搜索",
            "检索",
            "百科",
            "词典",
            "翻译",
            "天气",
            "汇率",
            "快递",
            "新闻",
            "热搜",
            "日历",
            "黄历",
            "漫画",
            "磁力",
            "资源",
            "search",
            "query",
            "wiki",
            "translate",
            "weather",
        ],
        "工具": [
            "工具",
            "解析",
            "下载",
            "上传",
            "文件",
            "网盘",
            "云存储",
            "二维码",
            "短链",
            "压缩",
            "编码",
            "转换",
            "计算",
            "适配器",
            "桥接",
            "面板",
        ],
    }

    # 兜底分类名 (设置面板 category.fallback 的缺省值; 与 InternalCFG.CATEGORY_FALLBACK 保持一致)
    DEFAULT_CATEGORY_FALLBACK: str = InternalCFG.CATEGORY_FALLBACK

    # 兜底分类颜色 (设置面板 category.fallback_color 的缺省值): 绑定主题色槽 slot_0
    # (槽位 0 即原「其他」分类色, 随主题切换变化; 用户可改为其它 slot_N 或固定 #RRGGBB)
    DEFAULT_CATEGORY_FALLBACK_COLOR: str = "slot_0"

    # 默认分类 → 主题色槽绑定 (预置规则随默认配置导入, 用户可自由修改):
    # 与各主题 cat_slot_1~7 的槽位顺序一致, 保证 zhenxun 主题下默认分类保持原配色
    DEFAULT_CATEGORY_SLOT_BINDINGS: dict[str, str] = {
        "AI": "slot_1",
        "查询": "slot_2",
        "工具": "slot_3",
        "管理": "slot_4",
        "娱乐": "slot_5",
        "消息": "slot_6",
        "调试": "slot_7",
    }

    # 默认主题色槽 (zhenxun 的 cat_slot_0~9): 主题未定义任何色槽时的兜底色板
    # (类体内不能用推导式引用类属性, 故用普通循环)
    DEFAULT_CATEGORY_SLOTS: list[str] = []
    for _slot_i in range(0, 10):
        DEFAULT_CATEGORY_SLOTS.append(ZHENXUN_COLORS[f"cat_slot_{_slot_i}"])

    # 默认激活的预设名
    DEFAULT_PRESET: str = "zhenxun"

    # 下拉框中的「自定义」选项 (对应下方 presets 列表中的自定义配置)
    CUSTOM_PRESET_KEY: str = "自定义"

    # 向后兼容: DEFAULT_COLORS 指向默认预设配色
    DEFAULT_COLORS: dict[str, str] = ZHENXUN_COLORS


class RenderMode(str, Enum):
    """历史遗留枚举

    当前调度使用字符串 mode, 以 InternalCFG.CACHE_FILES 为准; 本枚举仅作旧代码兼容,
    新增渲染模式不要只改这里 (还需登记 CACHE_FILES 等, 见 AGENTS §5.4)。
    """

    COMMAND = "command"
    COMMAND_DETAIL = "command_detail"
    EVENT = "event"
    FILTER = "filter"

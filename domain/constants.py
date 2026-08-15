from enum import Enum

from astrbot.core.star.star_handler import EventType


class InternalCFG:
    """内部常量"""

    # 映射
    CACHE_FILES: dict[str, str] = {
        "command": "cache_menu_command",
        "event": "cache_menu_event",
        "filter": "cache_menu_filter",
    }

    EVENT_TYPE_MAP: dict[EventType, str] = {
        EventType.OnAstrBotLoadedEvent: "系统启动 (Loaded)",
        EventType.OnPlatformLoadedEvent: "平台就绪 (Platform)",
        EventType.AdapterMessageEvent: "消息监听 (Message)",
        EventType.OnLLMRequestEvent: "LLM 请求前 (Pre-LLM)",
        EventType.OnLLMResponseEvent: "LLM 响应后 (Post-LLM)",
        EventType.OnDecoratingResultEvent: "消息修饰 (Decorate)",
        EventType.OnAfterMessageSentEvent: "发送回执 (Sent)",
    }

    # 会引起布局变动的配置项 → 缓存失效
    CACHE_SENSITIVE_CONFIGS: list[str] = [
        "giant_threshold",
        "split_height",
        "ppi",
        "ignored_plugins",
        "effective_colors",
    ]

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"

    # 时序
    DELAY_SEND: float = 1

    # 分类 (指令模式 /helps) 相关
    # 兜底分类名, 匹配不到任何关键词时使用
    CATEGORY_FALLBACK: str = "其他"
    # 分类关键词映射: 插入顺序即匹配优先级, 命中即返回
    CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "查询": (
            "查询",
            "搜索",
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
            "search",
            "query",
            "wiki",
            "translate",
            "weather",
        ),
        "娱乐": (
            "娱乐",
            "游戏",
            "抽奖",
            "点歌",
            "音乐",
            "笑话",
            "梗图",
            "表情包",
            "随机",
            "运势",
            "签到",
            "塔罗",
            "占卜",
            "骰子",
            "game",
            "music",
        ),
        "工具": (
            "工具",
            "计算",
            "转换",
            "二维码",
            "短链",
            "短网址",
            "解析",
            "压缩",
            "编码",
            "tool",
            "qrcode",
        ),
        "管理": (
            "管理",
            "群管",
            "禁言",
            "踢人",
            "审核",
            "权限",
            "撤回",
            "违禁词",
            "黑名单",
            "风控",
            "admin",
            "ban",
        ),
        "资讯": (
            "资讯",
            "订阅",
            "推送",
            "通知",
            "提醒",
            "播报",
            "监控",
            "rss",
            "news",
            "feed",
        ),
        "AI": (
            "ai",
            "llm",
            "模型",
            "gpt",
            "大模型",
            "对话",
            "智能",
            "画图",
            "绘图",
            "文生图",
            "图像",
            "绘画",
            "image",
            "diffusion",
        ),
        "调试": (
            "调试",
            "开发",
            "测试",
            "日志",
            "诊断",
            "debug",
            "dev",
        ),
    }
    # 分类主题色板: 按分类顺序循环取色, 保证相邻分类颜色区分
    CATEGORY_PALETTE: tuple[str, ...] = (
        "#e53935",  # 红
        "#8e24aa",  # 紫
        "#3949ab",  # 靛蓝
        "#1e88e5",  # 蓝
        "#00897b",  # 青绿
        "#43a047",  # 绿
        "#f4511e",  # 深橙
        "#6d4c41",  # 棕
        "#546e7a",  # 蓝灰
        "#d81b60",  # 粉
    )
    # 分类卡片布局估算 (pt): 仅用于 2 列平衡, 与模板 spacing 保持近似
    CATEGORY_HEADER_HEIGHT: int = 30
    CATEGORY_ROW_HEIGHT: int = 24


class DefaultCFG:
    """兜底: 配置默认值"""

    # 1. 渲染限制
    LIMIT_TASK: int = 2  # 最大并发编译数
    LIMIT_GIANT: int = 1500
    LIMIT_WEBP: int = 16383
    LIMIT_SIDE: int = 16000
    LIMIT_PPI: float = 144.0

    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0

    # 3. 过滤设置
    # config.py 负责 list → set
    IGNORED_PLUGINS: set[str] = {
        "astrbot",
        "astrbot-web-searcher",
        "astrbot-python-interpreter",
        "session_controller",
        "builtin_commands",
        "astrbot-reminder",
        "astrbot_plugin_help_typst",
    }

    # 4. 默认配色 (Original Palette)
    DEFAULT_COLORS: dict[str, str] = {
        # --- 页面背景 ---
        "page_fill": "#f0f2f5",
        # --- 插件卡片 ---
        "c_plugin_name": "#0d47a1",
        "c_plugin_id": "#546e7a",
        # --- 指令/文本 ---
        "c_group_title": "#6a1b9a",  # 父级/分组标题
        # 子指令/具体项
        "c_bullet": "#d81b60",
        "c_event_icon": "#ffc72c",
        "c_leaf_text": "#37474f",
        # 描述文本
        "c_desc_text": "#757575",
        # --- 容器布局 ---
        "c_group_bg": "#f3e5f5",
        "c_rich_bg": "#fcfcfc",
        # 紧凑块
        "c_box_bg": "#f5f5f5",
        "c_box_stroke": "#e0e0e0",
        # --- 特殊视图 ---
        "c_text_primary": "#1a1a1a",  # 分区大标题
        # 正则表达式视图
        "c_regex_bg": "#fff3e0",
        "c_regex_text": "#e65100",
        "c_regex_icon": "#f57c00",
        # 事件与管理标签
        "c_tag_admin": "#c62828",
        "c_tag_event": "#f57c00",
        "c_tag_mcp": "#00695c",
        "c_tag_id": "#283593",
        # 胶囊
        "c_ver_bg": "#e3f2fd",
        "c_ver_text": "#1565c0",
        "c_prio_bg": "#e8eaf6",
        "c_prio_text": "#283593",
        # --- 搜索高亮 ---
        "c_highlight_bg": "#ffeb3b",
        "c_highlight_text": "#000000",
    }


class RenderMode(str, Enum):
    """枚举"""

    COMMAND = "command"
    EVENT = "event"
    FILTER = "filter"

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
        "effective_colors"
    ]

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"

    # 时序
    DELAY_SEND: float = 1


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
        "c_group_title": "#6a1b9a", # 父级/分组标题
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
        "c_text_primary": "#1a1a1a", # 分区大标题
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
        "c_highlight_text": "#000000"
    }


class RenderMode(str, Enum):
    """枚举"""

    COMMAND = "command"
    EVENT = "event"
    FILTER = "filter"

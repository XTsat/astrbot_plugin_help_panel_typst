# AGENTS.md — 项目工作说明

> 本文件是任何 AI 编码助手（agent）进入本项目时的**必读**工作说明书。
> 它约定插件架构、代码规范、文档维护规则与提交流程。任何对代码、配置、行为的改动，都必须同时遵守本文档的规则。
>
> **来源**：本文件派生自 [agent-templates](https://github.com/XTsat/agent-templates) 的 `templates/astrbot-plugin/AGENTS.md`，上游最新版见该仓库 `main` 分支。
> **更新流程**：用户说「更新 AGENTS」时按以下步骤执行：① 拉取来源模板最新版 → ② 与本地逐节比对 → ③ 合并（保留本项目已回填的插件名、命令前缀、目录结构与项目特有约定）→ ④ 展示 diff 与改动清单，等用户确认后再落盘。**禁止整文件覆盖**。
>
> 与上游的已回填差异：日志前缀使用 `[HelpTypst]`；README 目前为单语历史格式；历史 CHANGELOG（v0.4.3 及以前）沿用旧内联格式。

---

## 1. 项目概览

`astrbot_plugin_help_panel_typst` 是一个 **AstrBot 插件**（`Star` 类型，入口类 `HelpTypst`），仓库与插件目录同名。它把 AstrBot 的插件与指令、事件监听、函数工具（含 MCP）、过滤器渲染成图片界面：

- `/helps` 卡片式帮助面板（分类卡片 + 全局编号），支持 `<编号>` 插件详情页与 `s <关键词>` 搜索。
- `/helpss` 详细面板：在每个插件条目下展开指令 / 别名 / 参数标签组，形成「分类 → 插件 → 指令」三级信息。
- `/events`：按 EventType 分组的事件监听列表，含插件函数工具与 MCP 工具。
- `/filters`：按过滤器类型分组的详情。
- 外观：**Hero 品牌横幅**（背景图 + 人格名统计）、4 套内置主题（真寻 / 墨竹 / 落日 / 夜鸢）+ 10 个分类色槽、可在设置面板自定义的插件分类规则。
- 字体：内置字体 + 自定义目录 + 系统字体库；表情字体固定追加，不出现在选择框。
- 渲染：Typst（子进程）→ PNG → WebP，超高图自动切片。

> 历史名称 `astrbot_plugin_help_typst` 仍保留在默认忽略列表与部分文档路径中（升级兼容）。
> 判断当前插件身份以 `metadata.yaml` 的 `name` 为准。

### 1.1 核心文件清单

| 文件 | 必选 | 职责 |
|---|---|---|
| `main.py` | ✅ | 插件入口：注册指令、组装组件、请求编排与消息收发（含自我重载） |
| `metadata.yaml` | ✅ | 插件元信息（name、version、author、desc、repo、astrbot_version、tags） |
| `_conf_schema.json` | ✅ | WebUI 配置 Schema；字体/插件下拉 `options` 在运行时同步到内存 Schema，**不改写磁盘文件** |
| `README.md` | ✅ | 中文文档（功能、指令、配置、常见问题），面向使用者 |
| `CHANGELOG.md` | ✅ | 变更日志，顶部固定 `[Unreleased]` |
| `LICENSE` | ✅ | 许可证 |
| `logo.png` | ✅ | 插件图标 |
| `requirements.txt` | ✅ | 运行时依赖（`typst`、`pydantic`） |
| `domain/` `utils/` `core/` | ✅ | 分层业务代码（见 §2） |
| `templates/base.typ` | ✅ | Typst 渲染模板：消费 JSON payload 与 sys_inputs |
| `resources/` | ✅ | 内置字体与背景图 |
| `preview/` | 可选 | README 功能预览图 |
| `hero_preview.png` | 可选 | README 顶部横幅图 |
| `.gitignore` | 可选 | Git 忽略规则 |

---

## 2. 目录结构与架构

### 2.1 项目结构

```
main.py              # [入口] 注册指令、组装组件、请求编排与消息收发（含自我重载）
domain/              # [数据定义层] 最底层，不做跨层依赖
  constants.py       #   InternalCFG / DefaultCFG / RenderMode（阈值、默认值、映射、主题色板、两列高度估算系数）
  config.py          #   TypstPluginConfig 及各子配置 + load() 兜底 + 分类匹配 + 配色解析
  schemas.py         #   RenderNode / PluginMetadata（SafeStr/SafeName 输入清洗）
utils/               # [通用工具层] 禁止 import core/ 或 main
  hash.py            #   calculate_hash（MD5，用于缓存内容哈希）
  font.py            #   FontManager：字体扫描、schema 同步、字体列表清洗
  image.py           #   图片头/扩展名校验、尺寸读取、PNG → WebP 切片
  view.py            #   HelpHint(文案) / MsgRecall(发送撤回) / TypstLayout(布局 JSON)
core/                # [核心业务层] 纯 Python 逻辑
  analyzer.py        #   BaseAnalyzer + Command/Event/Filter 分析器（组装 RenderNode 树）
  renderer.py        #   TypstRenderer：路径策略、缓存、背景图解析、子进程调度
  worker.py          #   RenderTask + execute_render_task（typst.compile，即用即销）
templates/base.typ   # 渲染模板
resources/fonts/     # 内置字体（LXGW Neo XiHei、Noto Color Emoji）
resources/images/    # 内置背景图（安装时导入数据目录 backgrounds）
preview/             # README 功能预览图
_conf_schema.json    # 配置面板 schema
metadata.yaml        # 插件元信息与版本号
```

### 2.2 运行时数据目录

`StarTools.get_data_dir()`（按 `metadata.yaml` 的 `name` 定位，当前为 `data/plugin_data/astrbot_plugin_help_panel_typst/`）下的运行期文件：

```
fonts/        # 自定义字体目录（custom_font_path 留空时使用）
backgrounds/  # 缺省背景图目录；安装时自动导入 resources/images 中的栅格图，已存在文件不覆盖
cache_menu_{command,command_detail,event,filter}.json/.png/.webp(_partN)   # 静态缓存
temp_<uuid>.json/.png/.webp(_partN)                                        # 搜索/详情临时文件
```

- 插件初始化时：扫描字体、同步内存 Schema（字体/预设/屏蔽插件下拉）、清洗非法字体选项、导入内置背景图。
- 插件卸载时：清理 `temp_*`，并再次扫描字体以刷新配置面板的字体选项（仅内存）。

### 2.3 架构风格与分层约束

本项目**固定采用分层多文件风格**（不是单文件风格），新增能力按职责落入既有分层，不另起并行结构。

依赖方向**严格单向**：`main.py → core → utils / domain`；`utils → domain`；`domain/` 只依赖自身（内部 `config.py` 可引用 `constants.py`）。

1. **新增常量**（阈值、超时、文件名、映射表）→ 放 `domain/constants.py` 的 `InternalCFG` 或 `DefaultCFG`，**禁止散落硬编码**。
2. **新增配置项** → `_conf_schema.json` 补 schema + `domain/config.py` dataclass 字段 + `load()` 兜底逻辑；默认值回落到 `DefaultCFG`（顺序见 §5.1）。
3. **数据模型** → `domain/schemas.py`，用 `SafeStr/SafeName`（带 `BeforeValidator`）做输入清洗，`model_config` 设 `extra="ignore"`。
4. **`utils/` 只向下依赖 `domain/`**；`core/` 可依赖 `utils` 与 `domain`；`domain/` 内部只允许 `config.py` 引用 `constants.py`。

### 2.4 核心数据流

```
/helps|/helpss|/events|/filters [编号 | s 关键词]
  └─ main.HelpTypst._handle_request(event, analyzer, title, mode, query, is_detail)
       ├─ _get_persona_name()                 # Hero 统计第三列（失败返回空串，不影响渲染）
       ├─ data_pipeline(save_path)            # 经 asyncio.to_thread 执行
       │    ├─ analyzer.get_plugin_by_order(n)    # 编号详情 → 按全局 order 精确命中（main 已判定意图）
       │    ├─ analyzer.get_plugins(query)        # 关键词 → 插件/节点递归剪枝；无参 → 全量
       │    ├─ (详情 / 详细模式) event_analyzer.get_plugin_event_listeners(...)
       │    ├─ font_manager.get_render_font_list(font_order)
       │    └─ layout.dump_layout_json(...)   # 标题/布局/颜色/字体/人格名 → JSON 落盘
       └─ renderer.render(data_pipeline, mode, query)
            ├─ query 非空 → temp_<uuid> 临时路径：不读写缓存，发送后延迟清理
            └─ query 为空 → cache_menu_* 静态路径：
                 ├─ _check_cache（内容 hash + 配置快照 + PNG 头有效性）命中 → 直接返回 WebP
                 └─ 未命中 → RenderTask → ProcessPoolExecutor(1)（全局信号量 + timeout_compile）
                             → typst.compile → process_image_to_webp（quality=80，超高图切 _partN）
                             → 原子替换为 cache_menu_* → 写 AstrBot KV：typst_cache_{mode}
```

**布局模式与缓存模式是两回事**：`plugin_detail` 是「编号」详情页的布局模式，走临时路径、不进静态缓存；静态缓存只对应 `command` / `command_detail` / `event` / `filter` 四种。

### 2.5 渲染契约（payload / sys_inputs）

`utils/view.py` 写出的 payload 按布局模式分支，模板依赖以下键：

- `command` / `command_detail`：`title`、`mode`、`prefixes`、`fonts`、`plugin_count`、`enabled_count`、`category_columns`
- `plugin_detail`：`title`、`mode`、`prefixes`、`fonts`、`plugin`、`admin_commands`、`normal_commands`、`event_listeners`
- `event` / `filter`：`title`、`mode`、`prefixes`、`fonts`、`plugin_count`、`giants`、`columns`、`singles`
- 所有模式统一注入 `colors`（激活配色 + 禁用灰化色板：卡片底色为深色时自动换用 `DISABLED_COLORS_DARK`，否则用 `DISABLED_COLORS`）、`system_name`（人格名，空串时模板不渲染该列）、`page_width`（页面总宽度，pt，模板据此设置 `#set page`；缺键按 830pt 兜底）、`content_columns`（卡片内部小块并排列数：页宽 ≥ 830pt 为 3，更窄为 2；缺键按 3 兜底）与 `plugin_two_lines`（插件行双行模式，缺键按 false 兜底）

`core/worker.py` 向模板传入 `sys_inputs`：恒有 `json_string`、`timestamp`；搜索时额外有 `query_regex`（`re.escape` 后的原始关键词）；背景相关为 `bg_image`（相对模板目录的路径）、`hero_header`（`"true"/"false"`）；品牌资源为 `logo_image`（相对模板目录的路径，空串表示文件缺失）。改 `view.py` / `worker.py` / `base.typ` 时保持键名一致。

**协议约定**：`sys_inputs` 的值一律按字符串传（Typst 侧 `sys.inputs.at(...)` 取回后由模板顶部集中解析成 bool / 数组）；payload 里的键模板必须用 `.at(key, default: ...)` 兜底，缺键不得导致整页编译失败。

---

## 3. 技术栈与依赖

- Python：代码保持 **3.10 兼容语法**（`list[str]`、`X | None`）；但实际运行环境由 AstrBot 决定，上游 `pyproject.toml` 当前要求 **>= 3.12**，因此不要依赖 3.11+ 才有的语义（如 `Flag.__contains__` 之外的 3.11 特性）做正确性判断
- AstrBot **>= 4.9.2**（见 `metadata.yaml`）；使用 `astrbot.api.star`（`Context`、`Star`、`StarTools`）、`astrbot.api.event`（`filter`、`AstrMessageEvent`）、`astrbot.api`（`logger`、`AstrBotConfig`）、`core.star.*`、`core.agent.mcp_client.MCPTool`
- `typst >= 0.14.7`（`typst.compile()` 编译、`typst.Fonts` 扫描字体）
- `pydantic`（V2）
- **Pillow**：图片校验 / 缩放 / 切片（`utils/image.py`），由 AstrBot 运行环境提供，**不在** `requirements.txt`
- 项目**不依赖** `fonttools`，已由 `typst` 新接口取代

**依赖管理**：

- 运行时依赖必须在 `requirements.txt` 中声明；复杂/较重的依赖优先**惰性 import**（在方法内 import），避免插件启动时强制加载。
- AstrBot 运行时已自带的依赖（如 Pillow）可以直接使用；依赖缺失时必须优雅降级，不能导致插件加载失败。
- 禁止引入与原功能无关的依赖；新增依赖需同步 `requirements.txt`、`README.md`、`CHANGELOG.md`，并评估插件市场安装环境是否具备该包。

---

## 4. 核心代码规范

### 4.1 插件骨架

本项目通过 `metadata.yaml` 加载，**不使用** `@register` 装饰器；入口类继承 `Star`：

```python
from collections.abc import AsyncGenerator

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, StarTools


class HelpTypst(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        # 初始化其它资源

    @filter.command_group("typst")
    @filter.permission_type(filter.PermissionType.ADMIN)
    def typst(self) -> None:
        pass

    @typst.command("font")
    async def cmd_scan_fonts(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """扫描字体并重载插件"""
        yield event.plain_result("...")
```

> 历史方法中 `show_menu` / `show_events` / `show_filters` 未使用 `cmd_` 前缀且缺少 `AsyncGenerator` 返回注解，保持不变；**新增**指令方法按上述规范书写。

### 4.2 命名约定

| 元素 | 约定 |
|---|---|
| 模块级常量 | `UPPER_SNAKE`（`DELAY_SEND`、`BACKGROUND_IMAGE_EXTS`） |
| 私有方法 | `_` 前缀 + `snake_case`（`_get_config_snapshot`） |
| 命令方法 | `cmd_` 前缀（`cmd_scan_fonts`；历史 `show_*` 保留） |
| Web API 方法 | `api_` 前缀（本插件暂无 Web API） |
| 类名 | `PascalCase`（`TypstRenderer`、`FontManager`） |
| 文件名 / 模块 | `snake_case`（`renderer.py`、`analyzer.py`） |
| 配置 key | `snake_case`（`background_random`、`rescan_fonts`） |

### 4.3 类型与语法

- 使用 Python 3.10+ 现代联合类型（`dict | None`、`list[str]`、`tuple[str, str]`）。
- 函数签名**必须完整类型注解**（参数 + 返回类型）；用 `yield` 返回结果的指令/事件处理方法标注 `AsyncGenerator[MessageEventResult, None]`（新增代码必须，历史方法逐步补）。
- 除第三方库/动态结构边界外不使用 `Any`；边界处也应收窄后再传递。
- 禁止无理由 `# type: ignore`；类型标注保持诚实。

### 4.4 注释规范

- **注释只写 non-obvious reason**：解释「为什么」，而不是「做了什么」。
  - 坏：`# 设置字体列表`；好：`# 编译与扫描共用同一份路径，避免系统字体选了却不生效`
- 不保留被注释掉的旧代码、未完成的 TODO 方案、调试输出。
- 方法级 docstring 用中文说明用途/参数/返回；`_` 开头的简单私有方法可省略。
- **指令 docstring 就是帮助面板的展示描述**（`_get_desc_safely` 取首行）：用中文、一句话、面向使用者。
- 代码分区用 `# ---- 分区名 ----` 分隔条。

### 4.5 日志

- 统一 `logger.info/warning/error`，**必须带 `[HelpTypst]` 前缀**（本项目约定）。
- 错误信息可带 emoji 前缀（如 `❌`、`⚠️`），用于用户可见提示。
- 精确捕获异常类型（`asyncio.TimeoutError`、`typst.TypstError`、`OSError`），禁止空 `except: pass`（除非注释说明理由）。
- 异常分类记录：非法参数（`ValueError`）、文件/IO（`OSError`）分别记录；单条规则失败不影响其它规则。

### 4.6 错误处理与防御性编程

- 面对不规范的插件元信息必须优雅 fallback（参考 `_get_safe_plugin_info`）。
- 外部 IO 必须 try/except 并记录 `logger.warning/error`，**不允许静默吞异常**。
- 配置值防御式校验：统一走 `domain/config.py` 的 `_as_int` / `_as_float` / `_as_bool`（类型异常→默认值、越界截断、布尔只认 `true/false/1/0` 字符串），**不要在各处散写 `int()` / `bool()`**；`rendering` / `appearance` 等子配置先 `isinstance(v, dict)` 收窄再取键。
- 降级链路清晰：首选方案 → 兜底方案 → 占位文本（例如背景图失效时回退目录扫描/经典布局）。

### 4.7 并发与性能

- 异步方法使用 `async/await`，**禁止阻塞事件循环**；数据分析、编译、图片处理必须走 `asyncio.to_thread` 或子进程。
- 并发限制用 `asyncio.Semaphore(...)`；静态渲染按 mode 持 `asyncio.Lock`，避免同模式重复编译。
- 渲染路径的 `ProcessPoolExecutor` **即用即销**：`max_workers=1`，用 `pool.shutdown(wait=False, cancel_futures=True)` 收尾（不能用 `with` 语句——超时/取消时阻塞等待子进程会卡住事件循环），子进程结束调用 `force_memory_release()`。
- 长任务超时（如 `timeout_analysis`）必须显式处理，返回用户可读的错误提示。

### 4.8 回复消息

- 统一 `yield event.plain_result(...)`；图片结果用 `event.chain_result([Image.fromFileSystem(p) ...])`。
- 用户可读输出用中文 + emoji 图标风格；错误提示说明「发生了什么 + 可以怎么做」。

### 4.9 权限控制

- 管理类指令必须加 `@filter.permission_type(filter.PermissionType.ADMIN)`；只读展示类指令默认对所有人开放。

### 4.10 模板契约

- `templates/base.typ` 只消费 `payload` 与 `sys_inputs`；新增字段在 `utils/view.py` 注入，模板侧对缺失字段提供默认值（旧缓存 JSON 不应导致编译崩溃）。
- 修改 payload 键名时，同步 `view.py`、`worker.py`、`base.typ` 三处。
- **协议解析集中在模板顶部**：`sys_inputs` 的字符串布尔（`hero_header`）与数组（`prefixes`）在文件头部解析成 `hero_header_enabled` / `primary_prefix` 等变量，后续只用变量；不要在渲染路径里散做 `== "false"` 比较。
- **Typst 不能探测文件是否存在**（`image()` 缺文件 = 硬编译错误，无 try/catch）：需要模板引用的可选资源（如品牌徽标）由 Python 侧探测后注入相对路径，缺失时注入空串，模板按空串跳过，保证整页仍能编译。

---

## 5. 配置与数据文件

### 5.1 配置 Schema（schema 先行）

- 新增配置项**先**在 `_conf_schema.json` 补 schema（`type` / `hint` / `default` / `options`），**再**在代码中实现读取。
- 默认值在 **`DefaultCFG` 与 `_conf_schema.json` 的 `default` 两处维护**，修改时必须同步（例如 `ignored_plugins`、字体缺省项）。
- 文档（README 配置说明、CHANGELOG）引用配置项时，统一写成**「中文名（`key`）」**：中文名取自 schema 的 `hint`，key 用反引号包裹，例如「背景图随机选择（`background_random`）」。
- 新增会影响布局/图片输出的配置项，必须同时加入 `InternalCFG.CACHE_SENSITIVE_CONFIGS`（见 §5.4）；`rendering` 下的 `ppi`、`split_height`、`giant_threshold`、`output_format` 均已入表（`webp_limit` 已并入 `split_height`，不再是配置项）。
- 新增主题预设只需在 `DefaultCFG.PRESETS` 登记配色；`active_preset` 与字体下拉 `options` 由 `FontManager.update_json_schema` 在运行时同步到内存 Schema，不要手改 schema 的 `options`。

### 5.2 配置读取与默认值

- 读取配置一律经 `TypstPluginConfig.load()`，缺项回退 `DefaultCFG`；不直接散读 `self.config[...]`。
- `ignored_plugins` 统一转为 `set`，缓存快照中排序后再比较。
- 分类规则由 `CategoryConfig.match(title, desc)` 归类：**名称/展示名命中优先**于简短描述/描述命中，同层级**长关键词优先**，长度相同按列表顺序；中文关键词子串匹配，纯英文关键词按整词匹配；全部未命中用兜底分类。缓存快照使用 `CategoryConfig.to_plain()`。
- 颜色来源：内置主题色板在 `DefaultCFG.PRESETS`，分类色槽为 `cat_slot_0`~`cat_slot_9`；分类规则 `color` 支持 `slot_N`、`#RRGGBB`、留空（按顺序自动分配）。

### 5.3 运行时数据与持久化

- 数据目录通过 `StarTools.get_data_dir()` 获取（见 §2.2），不写死绝对路径。
- 缓存元数据存于 AstrBot KV（`typst_cache_{mode}`）；图片/JSON 存于数据目录。
- 文件读写统一 `encoding="utf-8"` + `ensure_ascii=False`。
- 新增需要持久化的数据文件时：持 `asyncio.Lock`，先写 `.tmp` 再 `os.replace` 原子替换；写入前先读取并保留其它会话/用户已有内容。
- 临时文件用 `temp_` 前缀，任务结束后清理，避免数据目录堆积。

### 5.4 缓存机制（改动渲染逻辑前必读）

- 静态模式 → 文件名映射见 **`InternalCFG.CACHE_FILES`**（`command` / `command_detail` / `event` / `filter`）。
- KV key：`typst_cache_{mode}`；缓存文件以 `CACHE_FILES` 的值命名（如 `cache_menu_command.json/.png/.webp`，超高图为 `_partN.webp`）。
- 缓存命中 = **内容 hash（JSON 的 MD5）+ 配置快照 + PNG 图片头有效** 三重比对（`_check_cache`）；命中后还会复查对应 WebP 是否存在。
- 配置快照包含：`InternalCFG.CACHE_SENSITIVE_CONFIGS` 中的配置项、当前生效的 `effective_fonts` / `effective_colors`、背景图指纹（路径 + 大小 + mtime）、模板指纹（路径 + 大小 + mtime）。
- **新增布局相关配置时必须加入 `CACHE_SENSITIVE_CONFIGS`**（或显式注入快照），否则缓存不会失效。

**缓存相关陷阱**：

1. **模板改动靠指纹失效**：模板自身的 mtime/大小已纳入快照，换模板文件会自动重编；但只改模板**引用的**资源（`resources/` 下的图片、字体）时指纹不变，仍需清掉对应 KV key 与 `cache_menu_*` 文件再验证。
2. **新增渲染模式**：必须同时登记 `InternalCFG.CACHE_FILES`（决定缓存文件名与并发锁）、在 `main.py` 绑定指令、在 `utils/view.py` 生成 payload、在 `templates/base.typ` 消费新字段；漏登记会落到 `cache_unknown` 且无锁。
3. **`RenderMode` 枚举是历史遗留**：当前调度使用字符串 mode，以 `CACHE_FILES` 为准，不要只改枚举就以为新增了模式。四个静态模式现已与枚举成员对齐（新增模式仍需按上一条四处登记）。
4. **静态产物是「临时 stem + 原子替换」**：编译先写 `temp_<uuid>.png/.webp`，成功后 `os.replace` 成 `cache_menu_*`；不要再改回「编译前先删旧文件」，那会删掉在途请求正在发送的图片。
5. `rendering.timeout_compile` 与 `rendering.max_concurrent_tasks` 已接入渲染路径（编译外层全局信号量 + `wait_for` 超时）；不要绕过信号量直接调用 `execute_render_task`。

### 5.5 字体与背景图

**字体**

- 搜索路径 = `resources/fonts` + 自定义字体目录（`custom_font_path`，留空为数据目录 `fonts/`）+ 系统字体目录。**扫描与编译共用** `FontManager.get_search_paths()`，改路径逻辑时两边自动一致。
- `typst.Fonts(font_paths=...)` 扫描字体家族；选择框排除固定表情字体 `DefaultCFG.EMOJI_FONT`。
- 渲染字体列表 = 用户选定且可用的字体 + 兜底（`DefaultCFG.DEFAULT_FONT_ORDER`）+ **固定追加** `Noto Color Emoji`（`get_render_font_list`，保证列表非空）。
- Schema 同步：`FontManager.update_json_schema` 只改写内存 live schema（`config.schema`），不写磁盘 `_conf_schema.json`，使新字体/预设无需重载即出现在面板；`prune_invalid_config_items` 清理已失效选择。
- `appearance.rescan_fonts` 是**一次性开关**：插件初始化/卸载时扫描字体，随后自动复位为 false。
- 新增字体格式支持 → 同步 `font.py` 的扫描过滤、`README.md` 的字体说明，并确认 `typst` 编译侧支持。

**背景图 / Hero**

- 解析优先级：`header_background`（单文件）→ `background_dir`（自定义目录）→ 数据目录 `backgrounds/`。
- 只扫描目录**根层**的栅格图片（`.png/.jpg/.jpeg/.webp/.gif`，即 `InternalCFG.BACKGROUND_IMAGE_EXTS`，仅 Typst 能解码的格式），排除 `cache_` / `temp_` 前缀，并校验图片头与扩展名一致；扩展名按**小写**比较（Linux 区分大小写，`.PNG` 也算），`header_background` 同样受该白名单约束，不支持时回退目录扫描。
- `background_random` 在**每批次渲染开始时只随机一次**（`render()` 内的局部变量 `bg_image`，不存实例属性），快照与本次编译使用同一个值；不要在模板或 worker 内再次随机，也不要把背景图放回 `self` 上（并发请求会互相覆盖）。
- 背景图变更通过快照指纹自动使缓存失效；`hero_header` 关闭或无背景图时回到经典白色卡片布局。
- 背景图注入依赖 Typst `root`：`root = commonpath(模板目录, 数据目录, 插件根目录, 背景图)`。`插件根目录` 必须在内，否则模板里的 `../resources` 徽标会越出沙箱；跨盘符（Windows）或无共同父目录时**只放弃背景图**并回落到插件根目录（整页仍编译），不要假设背景一定可用。

---

## 6. 指令注册与命令清单

### 6.1 指令注册模式

```python
@filter.command("helps", alias={"功能", "菜单", "帮助"})
async def show_menu(
    self, event: AstrMessageEvent, query: GreedyStr
) -> AsyncGenerator[MessageEventResult, None]:
    """显示指令菜单"""
    ...

@filter.command_group("typst")
@filter.permission_type(filter.PermissionType.ADMIN)
def typst(self) -> None:
    pass

@typst.command("font")
async def cmd_scan_fonts(self, event: AstrMessageEvent) -> ...:
    """扫描字体并重载插件"""
    ...
```

- 参数用 `GreedyStr` 接收剩余文本；搜索统一 `s <关键词>` 子命令，编号详情只按全局 `order` 精确命中。
- 本插件**不注册事件监听器**（只分析其它插件的事件）；如后续需要，使用 `@filter.event_message_type(...)` 并在文档中同步说明。

### 6.2 README 命令表格式

README 中的命令表统一为「命令 / 权限 / 说明」三列：

| 命令 | 权限 | 说明 |
|---|---|---|
| `/helps` | 全部 | 显示卡片式帮助面板 |
| `/typst font` | 管理员 | 扫描字体并重载插件 |

### 6.3 当前命令清单

| 指令 | 权限 | 说明 |
|---|---|---|
| `/helps` | 任意 | 卡片式帮助面板（别名：`/功能`、`/菜单`、`/帮助`） |
| `/helps <编号>` | 任意 | 指定插件详情页（作者/版本/简介/管理员指令/普通指令/事件监听） |
| `/helps s <关键词>` | 任意 | 搜索指令（关键词高亮） |
| `/helpss` | 任意 | 详细帮助面板，插件下展开指令标签组（别名：`/详细帮助`、`/详细功能`、`/详细菜单`）；同样支持 `<编号>` 与 `s <关键词>` |
| `/events [s <关键词>]` | 任意 | 事件监听 + 函数工具（含 MCP）列表（别名：`/事件`、`/事件监听`） |
| `/filters [s <关键词>]` | 任意 | 过滤器详情（别名：`/过滤器`、`/过滤`） |
| `/typst font` | 管理员 | 扫描字体并自重载插件 |

> `<编号>` 详情仅 `/helps` 与 `/helpss` 支持；`/events`、`/filters` 只接受 `s <关键词>` 搜索。

---

## 7. 文档维护规范（强制，不可省略）

> 本项目的**硬性要求**：任何改动在合并前，必须同步维护 `README.md` 与 `CHANGELOG.md`。未同步文档 = 任务未完成。

### 7.1 CHANGELOG

**流程**

- 顶部固定 `## [Unreleased]`；日常改动先记在这里，**发版时**再移动到 `## vX.Y.Z (YYYY-MM-DD)`（新版本在上）。
- **先记后合**：记录阶段同一工作周期内的改动各自独立成条（同一功能的多处调整也先各记一条，避免遗漏）；提交或发版前的整理阶段统一过一遍 `[Unreleased]`，把描述同一件事的多条合并成一条，不相关改动保持独立。
- 发版日期填**当前日期**（以发版当天系统时间为准）。
- **多会话并行**：更新前必须先读取当前文件，识别并保留其它会话已写入的条目，只追加自己的条目，**严禁整文件覆盖或删除他人记录**。

**格式（分组式，自 `[Unreleased]` 起启用）**

```markdown
# 变更日志

## [Unreleased]

> 一句话总结本批改动（可选）

### 修复
- 数据目录说明：修正 README 与配置提示中仍使用旧插件名的问题

### 新增
- 功能名：说明
```

- 分类子标题：`### 新增` / `### 修复` / `### 变更` / `### 移除` / `### 性能`，**只写本次有内容的分类**，不留空标题。
- 条目格式 `- 标题：说明`；默认不加粗，**只有重点改动**（核心新功能、重要修复、破坏性变更）才用 `**加粗**` 强调。
- 历史段（v0.4.3 及以前）为旧内联格式，**保持不动**，不要为了统一而重写历史。

**写作视角（面向用户）**

- 读者是插件使用者（服务器管理员、群成员），不是开发者；只写用户能感知的变化。
- 写「用户能做什么 / 会看到什么 / 行为与默认值有什么不同」；不写类名、函数名、数据结构、算法、缓存与并发策略、日志埋点、重构过程。
- 不出现代码标识符与文件路径；用户直接接触的命令名、配置项 key 除外。
- 无用户感知的改动（纯内部重构、格式化、注释调整）不记入 CHANGELOG。
- 只写相对上一版的变化：只讲差异，不复述仍然有效的旧功能，不写「继续优化」「体验更好」这类没有信息量的空话。
- 同一个变化合并成一条：同一功能的多处调整、跨多个提交的同一件事，在提交或发版前的整理阶段合并为一条，不在不同分类或不同版本段重复出现。
- 一句话说清改了什么：按「做了什么 + 用户得到什么」写完，不加背景、动机与实现过程。
- 判断标准：使用者读完一条，能决定「要不要升级、升级后有什么不同」。

**版本号（准备发布时才确认）**

- **日常开发不碰版本号**：只往 `[Unreleased]` 追加条目，`metadata.yaml` 的 `version` 保持原值；每个功能、每个修复各自独立提交，提交里不带版本号变更。
- **发版时一次确认**：把 `[Unreleased]` 移入 `## vX.Y.Z (YYYY-MM-DD)` 的同一次操作里才递增版本号（SemVer 见 §8.3），改 `metadata.yaml` 的 `version`，把 README 的版本信息等辅助位置同步成同一版本号，再打 `git tag vX.Y.Z`。**不能每改一点就递增**，否则版本号会随提交次数突进、与实际发布节奏脱节。
- **唯一版本源**：`metadata.yaml` 的 `version` 字段；README 的版本徽章与正文版本字样属于辅助信息，不是版本源，需要展示版本时以 `metadata.yaml` 为准。

### 7.2 README

**写作视角（面向用户）**

- 读者是插件使用者；只写用户能直接用到的东西。
- 该写：能做什么、怎么装、怎么配（配置表）、怎么用（指令表与示例）、出问题怎么办（常见问题、前置条件与限制）。
- 不写：实现原理与设计理念、架构分层与模块划分、算法与数据结构、内部调用流程、类名/函数名/文件路径、性能优化手段。
- 技术细节翻译成用户语言：不写「用 `asyncio.Semaphore` 限制并发」，写「同时处理的任务数量上限」。
- 判断标准：使用者只读 README，就能独立完成安装 → 配置 → 使用 → 排障。

**四大板块**

| 板块 | 内容 |
|---|---|
| 一、功能/介绍 | 功能介绍、特性列表、使用场景、截图/演示 |
| 二、指令 | 命令表（命令 / 权限 / 说明）、使用示例 |
| 三、配置 | 配置项表（配置项 / 类型 / 默认值 / 说明） |
| 四、其它 | 安装、快速开始、运行环境与依赖、常见问题、许可证、鸣谢 |

**何时必须更新**

| 改动类型 | 必须更新的板块 |
|---|---|
| 功能新增/删除 | 一、功能/介绍 |
| 使用方式/命令变化 | 二、指令 |
| 配置项变化 | 三、配置 |
| 依赖/版本要求变化 | 四、其它（安装/依赖） |
| 已知问题/行为变化 | 四、其它（常见问题） |

纯内部重构、样式调整、不改变用户可见行为的修复，不需要更新 README。

**当前状态与双语文档**

- 本项目目前仅维护中文 `README.md`，头部为历史格式，**本次不重构**。
- 若后续新增英文版 `README_en.md`：中文版为权威版本（源），改动先落中文、再同步英文，**禁止反向**；两版章节结构保持一致，头部语言切换链接互相指向。

**格式与多会话**

- 禁止无意义换行：HTML 头部区块内元素间不留空行；正文一段文字保持一行，空行只用于分隔标题、表格、列表、代码块。
- 多会话并行修改时先读后改，只追加/修改自己的部分，**严禁整文件覆盖**。

### 7.3 PR 描述规范

- **PR 描述只写最终行为**：描述最终完成了什么，而不是过程中尝试了什么。
- 禁止提及被否定的方案、中间状态、未合入的尝试。
- 只写 diff 里看不出来的取舍理由（如「选用方案 A 因为性能比 B 高 20%」）。

---

## 8. 提交与发布流程

### 8.1 提交信息（Conventional Commits）

- 格式：`<type>(<scope>): <中文短句式 subject>`，例如 `feat: 开放颜色配置项`、`fix: 修复系统字体选择后不生效`、`docs: 更新 README 配置说明`。
- 常用 type：`feat` / `fix` / `docs` / `refactor` / `perf` / `test` / `chore` / `build` / `ci` / `style`；`scope` 可选。
- subject 用中文短句、单行；需要解释「为什么」时在正文补充，不要写过程流水账。
- **禁止**把未完成的功能、多轮迭代的中间状态、被废弃的方案写进提交信息。
- 文档更新与代码改动**在同一提交中完成**（不单独拆「补文档」提交）。
- 推荐顺序：完成功能 → 跑通验证 → 更新 CHANGELOG 与 README → 提交。

### 8.2 提交前确认与授权（一次性）

- **提交前必须先向用户展示以下内容，等用户确认后再执行 `git commit`**：
  - 待提交文件清单；
  - 改动概要（如 `git diff --stat` 或等价说明）；
  - **提交标题，尽量给 2–3 个候选**（不同侧重点：做了什么 / 为什么改 / 是否带 scope），逐条注明侧重并标出推荐项；确实只有一种合理写法时才给一个；
  - 用户选定标题（或自拟）后才 commit；涉及推送时另附提交 hash 与目标分支。
- **授权一次性，不延续**：
  - 用户的确认只对当次动作生效；下一次改动必须重新展示、重新确认。
  - 展示后改动内容又变了（用户提了新要求、又改了文件，哪怕只改一行），**原确认立即失效**，必须重新展示并再次确认。
  - 以下情形**都不算授权**：上一轮 / 上一个任务 / 上一个会话说过「提交」「推送」；会话恢复（resume / fork）后继承的历史授权；用户对功能或代码表示满意；用户正在讨论其它需求；用户未回复。
  - 授权范围逐项独立：确认 commit ≠ 授权 push；确认推送某分支 ≠ 授权后续继续提交或推送；确认一个提交 ≠ 授权 `--amend` 或追加提交。
  - 执行前自检：能指出用户**本轮**对**本次改动**的明确同意原话；指不出来就先问，不要执行。
- 只有用户明确要求时才 commit / push；「准备提交」阶段只暂存并等待确认。

### 8.3 版本号与发布

- 采用 **SemVer**：新功能 → `minor` 递增；bug 修复 / 小改进 → `patch` 递增；破坏性变更 → `major`。
- **只在发版时递增一次**（规则见 §7.1）：单个功能/修复提交不碰版本号，逐次递增会让版本号随提交次数突进。
- 发版一致性：`metadata.yaml` 的 `version` = `CHANGELOG.md` 新版本段号 = `git tag vX.Y.Z`；tag 推送同样需用户确认。

### 8.4 验证

- 项目无强制测试框架，改动后至少做语法自检：`python -m compileall -q .`。
- 若项目已补充单测，改动后需保证测试通过。
- 格式化：`python -m ruff format .`（项目历史使用 ruff；未安装可先 `pip install ruff`，不要写入 `requirements.txt`）。
- 涉及渲染的改动需人工核对缓存失效逻辑（见 §5.4），必要时清缓存后重测。
- **不要手改 schema 的 `options`**：字体与屏蔽插件选项由运行时写入内存 Schema，磁盘 `_conf_schema.json` 不再被运行时改写；`git diff` 里出现 `options` 差异说明有人手改过，需要人工核对。

---

## 9. 最终检查清单（每次任务完成前）

- [ ] 架构：改动落在既有分层（`main → core → utils/domain`），未破坏依赖方向
- [ ] 注释：只写 non-obvious reason，无残留旧代码 / 调试输出 / 半成品 TODO
- [ ] 日志：`[HelpTypst]` 前缀，异常分类记录，无空 `except`（或已注释理由）
- [ ] CHANGELOG：`[Unreleased]` 已按分组式追加条目，**只写相对上一版的变化**、同一变化已合并为一条（无重复条目），面向用户，保留了他人既有记录
- [ ] README：涉及用户可见变更时已同步，且面向用户书写（无实现原理与内部细节）
- [ ] 版本号：日常任务不递增版本号；发版时才改 `metadata.yaml` 的 `version`（与 CHANGELOG 新版本段、tag 一致）并同步 README 版本信息
- [ ] 配置：schema 与代码同步，默认值两处一致，布局相关配置已入 `CACHE_SENSITIVE_CONFIGS`
- [ ] 指令：docstring（展示描述）、别名、权限、README 命令表已同步
- [ ] 缓存：改模板后已清缓存；新增渲染模式已登记 `CACHE_FILES`
- [ ] 提交：Conventional Commits 格式；已展示文件清单 / `git diff --stat` / 2–3 个候选提交标题（注明侧重与推荐项），并取得**本轮**对**本次改动**的明确确认
- [ ] 本地自检：`python -m compileall -q .`（及 ruff 格式）通过

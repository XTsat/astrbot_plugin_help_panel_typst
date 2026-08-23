# AGENTS.md — 项目工作说明

本文件是任何 AI 编码助手（agent）进入本项目时的**必读**工作说明书。
它约定项目架构、代码规范、以及**强制性的文档维护规则**（README + CHANGELOG）。
任何对代码、配置、行为的改动，都必须同时遵守本文档的规则。

---

## 1. 项目概述

`astrbot_plugin_help_typst` 是一个 **AstrBot 插件**（`Star` 类型），核心能力：

- 把 AstrBot 的 **插件菜单 / 指令、事件钩子、函数工具(MCP)、过滤器列表** 渲染成友好图片界面。
- 基于 **Typst** 渲染（`typst` Python 包，子进程编译成 PNG → 转 WebP）。
- 提供**搜索**能力：`helps/events/filters s <关键词>`，附关键词高亮。
- 支持自定义字体（`.ttf/.otf/.woff2`）、多套外观预设（字体顺序 + 配色）。

**插件元信息**（`metadata.yaml`）：name=`astrbot_plugin_help_typst`，version 见文件。

## 2. 技术栈 & 依赖

- Python **3.10+**
- AstrBot **>= 4.10.4**（`astrbot.api` / `astrbot.core.star.*`）
- `typst >= 0.14.7`（渲染引擎，注意：通过 `typst.compile()` 的 Python 接口）
- `pydantic`（V2）
- 无其它运行时依赖（见 `requirements.txt`）

> ⚠️ 项目**不依赖** `fonttools`，已由 `typst-py` 新接口取代。

## 3. 目录结构与分层架构

依赖方向**严格单向**：`main.py → core → utils / domain`；`utils → domain`；`domain` 不依赖任何人。

```
main.py            # [入口] 注册指令/事件，组装组件，转发给 core
domain/            # [数据定义层] 最底层，无内部依赖
  constants.py     #   所有「魔术数字」、枚举、默认值统一维护于此
  config.py        #   配置聚合根 + 从 AstrBotConfig 加载 + 兜底逻辑
  schemas.py       #   Pydantic Models & TypedDicts（含输入清洗）
utils/             # [通用工具层] 公开可复用的静态方法，禁止 import core/main
  hash.py          #   calculate_hash
  font.py          #   FontManager 字体扫描 & 管理
  image.py         #   verify_image_header / process_image_to_webp
  view.py          #   HelpHint / MsgRecall / TypstLayout（视图 & 消息）
core/              # [核心业务层] 纯 Python 逻辑
  analyzer.py      #   Command/Event/Filter 三个分析器（获取、组织数据）
  renderer.py      #   TypstRenderer 渲染调度、缓存、路径策略
  worker.py        #   RenderTask + execute_render_task（子进程编译，即用即销）
templates/         # Typst 模板
  base.typ         #   基础库文件（类似 CSS Reset）
resources/         # 静态资源
  fonts/           #   内置开源中文字体
  images/          #   默认背景图、图标（未完成）
```

### 分层约束（务必遵守）

1. **新增常量**（阈值、超时、文件名、映射表）→ 放 `domain/constants.py` 的 `InternalCFG` 或 `DefaultCFG`，**禁止散落硬编码**。
2. **新增配置项** → 在 `domain/config.py` 定义 dataclass 字段 + `load()` 的兜底逻辑 + `_conf_schema.json` 补 schema；默认值回落到 `DefaultCFG`。
3. **数据模型** → `domain/schemas.py`，用 `SafeStr/SafeName`（带 `BeforeValidator`）做输入清洗，`model_config` 设 `extra="ignore"`。
4. **`utils/` 禁止 import `core/` 或 `main.py`**；`core/` 可 import `utils` 与 `domain`。

## 4. 核心数据流

```
用户指令 (helps/events/filters [s <关键词>|<编号>])
  └─ main.py._handle_request()
       ├─ analyzer.get_plugins(query)      # 分析器：从 star_handlers_registry / tools 组织数据
       │     └─ 产出 list[PluginMetadata] → RenderNode 树
       ├─ layout.dump_layout_json(...)     # 视图层：标题/布局/字体，写 JSON 到磁盘
       └─ renderer.render(data_pipeline)   # 渲染调度
             ├─ 静态模式：hash + config 快照 双校验 → KV 缓存命中则直接返回
             ├─ 搜索模式：临时文件 (temp_<uuid>)，用后即删
             ├─ worker.execute_render_task  # ProcessPoolExecutor(子进程) 调 typst.compile
             └─ process_image_to_webp       # PNG → WebP，超长自动切片 _part*.webp
```

## 5. 代码约定

- **注释与日志一律中文**；日志统一前缀 `[HelpTypst]`。
- **类型注解完整**（函数签名、返回类型），Python 3.10 语法（`list[str]`、`X | None`）。
- **防御性编程**：面对不规范的插件元信息必须 fallback（参考 `_get_safe_plugin_info`）；外部 IO 必须 try/except 并记录 `logger.warning/error`，**不允许静默吞异常**（空 `except: pass` 需注释说明理由）。
- **禁止 `as any` / `@ts-ignore` 式的类型作弊**；Python 侧禁止无理由 `# type: ignore`。
- 渲染重活必须走 `asyncio.to_thread` 或子进程，**禁止阻塞事件循环**。
- `ProcessPoolExecutor` 在渲染路径**即用即销**（`with ProcessPoolExecutor(...)`），子进程结束强制 `force_memory_release()`。

## 6. 缓存机制（改动渲染逻辑前必读）

- 静态缓存 key：`typst_cache_{mode}`（`command/event/filter`），存于 AstrBot KV。
- 缓存校验 = **内容 hash + 配置快照 + 图片头有效性** 三重比对（`_check_cache`）。
- **`InternalCFG.CACHE_SENSITIVE_CONFIGS`** 列出会引起布局变动的配置项，**新增此类配置时必须加入该列表**，否则缓存不会失效。

## 7. 指令清单（当前对外暴露）

| 指令 | 权限 | 说明 |
|---|---|---|
| `/helps` | 任意 | 显示卡片式帮助面板（别名：`/功能`、`/菜单`、`/帮助`） |
| `/helps <编号>` | 任意 | 指定插件详情页 |
| `/helps s <关键词>` | 任意 | 搜索指令 |
| `/events [s <关键词>]` | 任意 | 事件监听列表（别名：`/事件`、`/事件监听`） |
| `/filters [s <关键词>]` | 任意 | 过滤器详情（别名：`/过滤器`、`/过滤`） |
| `/typst font` | 管理员 | 扫描字体并自重载 |

---

## 8. 文档维护规则（强制，不可省略）

> 这是本项目的**硬性要求**：任何改动在合并前，必须同步维护 `README.md` 与 `CHANGELOG.md`。

### 8.1 何时必须更新

当改动属于以下任一情况，**必须**同时更新文档：

1. **新增/修改指令、事件、过滤器的行为或用法** → 更新 `README.md` 对应章节（简介、功能预览、常见问题等）。
2. **新增/移除配置项、依赖、字体支持** → 更新 `README.md`（依赖、配置说明、常见问题）。
3. **任何功能、修复、重构合并** → 在 `CHANGELOG.md` 顶部的 `[Unreleased]` 段追加条目。
4. **版本号变更**（发版）→ 三处同步：`metadata.yaml` 的 `version`、`README.md` 的版本徽章、`CHANGELOG.md` 新版本段。

### 8.2 CHANGELOG 格式

- 顶部固定 `## [Unreleased]` 段，日常改动先记在这里；**发版时**再把内容移动到带版本号的新段。
- 版本标题：`## vX.Y.Z (YYYY-MM-DD)`，新版本在上，按时间倒序排列。
- 条目：`- 分类：描述`，分类内联在条目开头（`新增` / `修复` / `变更` / `移除` / `性能`）。
- 版本号遵循 **SemVer**，日期格式 `YYYY-MM-DD`。
- 每条一行一句，面向使用者而非实现细节。

示例：

```markdown
## [Unreleased]

- 新增：媒体本地化转发配置项，开启后转发前将媒体重下载到本地重建
- 修复：修复跨会话转发时源端临时路径不可达的问题

## v0.3.0 (2026-07-06)

- 新增：新插件 logo

## v0.2.1 (2026-06-18)

- 新增：消息过滤系统：支持关键词与正则
```

### 8.3 执行要求

- 文档更新与代码改动**在同一提交中完成**（不单独拆「补文档」提交）。
- 描述必须与实际行为一致，**禁止粘贴未实现的功能**。
- README 的「计划清单」中已完成项要及时勾掉或移除。

---

## 9. 验证与提交

- 改完运行 `python -m ruff format .` 保持格式（项目历史有 `ruff format` 提交）。
- 若项目补充了单测，改动后需保证测试通过。
- **提交信息用中文**，与现有历史风格一致（如 `开放颜色配置项`、`修复其他平台的兼容性`）。
- 只有用户明确要求时才 commit / push / 发 PR。

# 📂︎ Astrbot Plugin Help Panel Typst | 插件帮助面板

---

## ✨ 功能

* 基于 [tinkerbellqwq/astrbot_plugin_help](https://github.com/bylkuse/astrbot_plugin_help_typst) 进行特化修改的插件帮助菜单
* 把插件菜单、事件钩子、函数工具、过滤器列表渲染成友好界面。其中 `/helps` 采用现代 Bot Dashboard 风格：顶部白色 Header 卡片（标题 + 统计）与快捷操作按钮，主体为双栏分类卡片，每个分类一张固定主题色卡片（彩色标题栏 + 插件列表 + 编号徽章）；`/events`、`/filters` 仍保留详细的节点与分组信息，可兼作调试辅助工具。
* 已停用（disabled）插件仍会展示在 `/helps` 中，以低饱和灰粉色板降低视觉权重（浅灰卡片、灰粉编号徽章、右侧「圆圈+斜杠」图标），布局与普通插件一致，一眼可辨「存在但当前不可用」。
* 内置 5 套主题预设：`Ocean Blue`（明亮清爽）、`Night Navy`（深色科技感）、`Soft Mist`（莫兰迪低饱和）、`Vivid Pop`（高饱和活力）与 `zhenxun`（柔和马卡龙粉彩），通过配置面板 `appearance.active_preset` 一键切换，品牌色板与分类色随之变化。
* 针对插件名、指令名、描述内容的泛用搜索工具，附关键词高亮
* `/helps <编号>` 可查看单个插件的详情页（作者/版本/功能简介/管理员指令/普通指令/事件监听）
* 基于 typst 渲染实现，轻量、灵活、高效，你可以使用 typst 语法修改、构建属于自己的渲染模板（WIP）
* 支持自定义字体 .ttf .otf .woff2<br>
  1. 放入 插件目录/resources/fonts 或[自定义字体目录](#-常见问题)<br>
  2. 重载方式三选一(更新 optional scheme)<br>
     1. 在 AstrBot 面板中重载插件<br>
     2. 重启 AstrBot<br>
     3. 使用指令 typst font<br>
  3. 新字体将会出现在配置面板供 勾选 & 排序 (不可用的字体会被自动剔除)

### 🖼️ 功能预览

| `插件菜单` | `事件监听器` |
| :---: | :---: |
| <img src="./preview/helps.jpg" width="400"> | <img src="./preview/events.jpg" width="400"> |

| `过滤器` | `搜索` |
| :---: | :---: |
| <img src="./preview/filters.jpg" width="400"> | <img src="./preview/search.jpg" width="400"> |

## 📖 指令使用

### 基本用法

| 指令 | 说明 |
| :--- | :--- |
| `/helps` | 显示插件卡片式帮助面板 |
| `/helps <编号>` | 查看指定插件的详情页（作者/版本/简介/管理员指令/普通指令/事件监听） |
| `/helps s <关键词>` | 搜索指令（按关键词高亮匹配） |
| `/events` | 显示事件监听列表 |
| `/events s <关键词>` | 搜索事件监听 |
| `/filters` | 显示过滤器详情 |
| `/filters s <关键词>` | 搜索过滤器 |
| `/typst font` | 扫描字体并重载插件（管理员权限） |

### 别名

| 主指令 | 别名（效果等同） |
| :--- | :--- |
| `/helps` | `/帮助`、`/菜单`、`/功能` |
| `/events` | `/事件`、`/事件监听` |
| `/filters` | `/过滤器`、`/过滤` |

## 🏷️ 插件分类规则

`/helps` 按插件元信息（`desc` / `name` / `display_name` / `tags`）中的关键词自动归类：命中第一个匹配的分类即归入该分类，全部未命中则归入「其他」。

> 下表顺序即匹配优先级（从上到下）。关键词以 `domain/constants.py` 的 `CATEGORY_KEYWORDS` 为准，修改后请同步更新此表。「主题色」为默认预设 `Ocean Blue` 的配色，切换预设后随主题变化。

| 分类 | 主题色 | 匹配关键词 |
| :--- | :--- | :--- |
| 查询 | 奶油黄 `#FADE86` | 查询、搜索、百科、词典、翻译、天气、汇率、快递、新闻、热搜、日历、黄历、search、query、wiki、translate、weather |
| 娱乐 | 浅青蓝 `#8AE6E1` | 娱乐、游戏、抽奖、点歌、音乐、笑话、梗图、表情包、随机、运势、签到、塔罗、占卜、骰子、game、music |
| 工具 | 深青 `#2E9BB8` | 工具、计算、转换、二维码、短链、短网址、解析、压缩、编码、tool、qrcode |
| 管理 | 深海蓝 `#355A81` | 管理、群管、禁言、踢人、审核、权限、撤回、违禁词、黑名单、风控、admin、ban |
| 资讯 | 浅天蓝 `#A8E9F2` | 资讯、订阅、推送、通知、提醒、播报、监控、rss、news、feed |
| AI | 天空蓝 `#57CDE3` | ai、llm、模型、gpt、大模型、对话、智能、画图、绘图、文生图、图像、绘画、image、diffusion |
| 调试 | 蓝灰 `#6C8CA8` | 调试、开发、测试、日志、诊断、debug、dev |
| 其他 | 灰蓝 `#808E9D` | 兜底：未命中任何关键词时归入 |

## ❓ 常见问题

### Typst 字体优先级

文档显式指定 > 项目字体目录 > 系统字体库

* 文档显式指定：通过 #set text(font: "font-family-name") 直接指定，优先级最高
* 项目字体目录：即本插件的根目录下的 ./resources/fonts <br>
~~后面会考虑增加额外的目录支持~~已完成，缺省值为 `.../data/plugin_data/astrbot_plugin_help_typst/fonts` 🚨 docker 用户记得确保自定义字体目录已被挂载
* 系统字体库：获取系统默认字体目录 ( Windows、macOS 应该有官方支持，Linux 未测试支持度如何；🚨 docker 环境可能需要安装字体依赖）

## 🌳 目录结构（初步预期）

```
astrbot_plugin_typst_menu/
├── main.py                # [入口] AstrBot 插件主文件，注册指令和事件，转发给 core
├── domain/                # [数据定义层] (最底层，无依赖)
│    ├── constants.py          # 存储 “魔术数字” 统一于此维护调试
│    ├── config.py             # 配置结构
│    └── schemas.py            # Pydantic Models & TypedDicts
├── utils/                 # [通用工具层] (各类公开可复用的静态方法)
│    ├── hash.py               # hash
│    ├── font.py               # 字体扫描 & 管理
│    ├── image.py              # 图片处理
│    └── views.py              # [视图层] 处理通过指令组管理和调试插件时展示给用户的格式化文本
├── core/                  # [核心业务层] (纯 Python 逻辑)
│    ├── analyzer.py           # 获取、组织数据
│    ├── renderer.py           # 渲染调度
│    └── worker.py             # 进程调用（即用即销）
├── templates/             # Typst 模板文件
│    └── base.typ              # 基础库文件 (类似 CSS Reset)
└── resources/             # 静态资源
     └── fonts/                # 内置开源中文字体

```

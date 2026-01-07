# 📂︎ Astrbot Plugin Help Typst | 插件菜单(typst实现)

<div align="center">

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-purple?style=flat-square)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](./LICENSE)
[![Version](https://img.shields.io/badge/Version-0.0.2-orange?style=flat-square)]()

** 以优雅的方式组织你的插件菜单 **
<br>
*轻量  丰富  更多🗃*

</div>

---

## 📖 简介
* 基于 tinkerbellqwq/astrbot_plugin_help 进行重度开发的插件菜单，实现缓存功能
* 把插件菜单、事件钩子、函数工具、过滤器列表渲染成友好界面，智能组织节点和分组，并附上丰富的元信息。不只是面向 bot 用户的说明，也是一份调试辅助工具。
* 针对插件名、指令名、描述内容的泛用搜索工具，附关键词高亮【用法： helps/events/filters <关键词>】
* 基于 typst 渲染实现，轻量、灵活、高效，你可以使用 typst 语法修改、构建属于自己的渲染模板（WIP）

<br>进度：基本功能 √

## ✔ 计划清单
* 配置-自定义项目
* 配置-背景
* 配置-模板
* ~~功能-黑白名单~~
* 指令-黑白名单管理
* 正式的说明文档

## 🖼️ 功能预览

| `插件菜单` | `事件监听器` |
| :---: | :---: |
| <img src="./preview/helps.jpg" width="400"> | <img src="./preview/events.jpg" width="400"> |


| `过滤器` | `搜索` |
| :---: | :---: |
| <img src="./preview/filters.jpg" width="400"> | <img src="./preview/search.jpg" width="400"> |

## 🧱 依赖
AstrBot
<br>typst>=0.11
<br>pydantic

## 🌳 目录结构（初步预期）
```
astrbot_plugin_typst_menu/
├── main.py                # [入口] AstrBot 插件主文件，注册指令和事件，转发给 core
├── domain/                # [数据定义层] (最底层，无依赖)
│    ├── constants.py          # 存储 “魔术数字” 统一于此维护调试
│    └── schemas.py            # Pydantic Models & TypedDicts
├── utils/                 # [通用工具层] (各类公开可复用的静态方法)
│    ├── config.py             # 配置转换 & 读取
│    ├── hash.py               # hash
│    ├── image.py              # 图片处理
│    └── views.py              # [视图层] 处理通过指令组管理和调试插件时展示给用户的格式化文本
├── adapters/              # [适配器] (具体的外部交互实现)
│    ├── astr.py               # 读取astrbot的设置及各类api方法（如 请求插件信息、LLM 请求）
│    └── napcat.py             # napcat的api功能（如获取 bot 自身信息）
├── core/                  # [核心业务层] (纯 Python 逻辑)
│    ├── analyzer.py           # 获取、组织数据
│    ├── renderer.py           # 渲染调度
│    └── worker.py             # 进程调用
├── templates/             # Typst 模板文件
│    └── base.typ              # 基础库文件 (类似 CSS Reset)
└── resources/                 # 静态资源
     ├── fonts/                # 内置开源中文字体
     └── images/               # 默认背景图、图标

```

---

<div align="center">
🔔 Merry Christmas~<br>
Made with 😊 by LilDawn
</div>
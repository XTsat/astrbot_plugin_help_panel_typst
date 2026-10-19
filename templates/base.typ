// ============================================================
// AstrBot 插件帮助面板 · Typst 渲染模板
// 指令菜单 (command) / 插件详情 (plugin_detail) / 事件·过滤器 (event/filter)
// 主题: Modern AstrBot Plugin Dashboard (多主题预设: Ocean Blue / Night Navy / Soft Mist / Vivid Pop / zhenxun)
// ============================================================

// === 🔧 参数传入 ===
#let data            = json(bytes(sys.inputs.at("json_string", default: "{}")))
#let user_fonts      = data.at("fonts", default: ())
#let query_regex_str = sys.inputs.at("query_regex", default: none)
#let generated_time  = sys.inputs.at("timestamp", default: "Unknown Time")

// === 🖼️ 头部 Hero 品牌模式 (可选, 默认开启) ===
// 由 Python 侧注入: bg_image = 相对模板目录的图片路径;
// hero_header 历史上传字符串 "true"/"false", 后续可能直接传 bool, 两种表示都要吃
#let bg_image_path = sys.inputs.at("bg_image", default: "")
#let has_header_bg = bg_image_path != ""
#let raw_hero_header = sys.inputs.at("hero_header", default: true)
#let hero_header_enabled = if type(raw_hero_header) == bool {
  raw_hero_header
} else {
  str(raw_hero_header) != "false"
}

// 品牌徽标路径: Typst 没有文件系统探测, 也没有异常捕获, 缺图只能由 Python 侧判断后注入;
// 未注入 (none) 时沿用内置资源, 注入空串表示文件缺失 → 不画徽标, 保证整页仍能编译
#let logo_image = sys.inputs.at("logo_image", default: none)
#let logo_path = if logo_image == none {
  "../resources/images/astrbot-logo-text.svg"
} else {
  str(logo_image)
}

// 统计卡片第三列显示名 (人格名称, 由 Python 侧注入; 空串则不渲染该列)
#let system_name = data.at("system_name", default: "")
// 卡片内部小块 (功能块 / 指令标签 / 独立工具) 的并排列数: 页宽变窄时 Python 侧降为 2
#let content_cols = data.at("content_columns", default: 3)
// 插件行双行模式: 英文 ID 换到中文名下方 (窄页宽下单行放不下名称+ID)
#let plugin_two_lines = data.at("plugin_two_lines", default: false)

// 编号徽章统一宽度: 徽章若随位数变宽, 9→10 时整列插件名会跟着左右错位
#let order_digits = calc.max(1, str(data.at("plugin_count", default: 0)).len())

// 分类计数徽章同样按最长位数统一宽度: 4 与 14 位数不同时徽章一长一短, 并排看很明显
#let count_digits = {
  let digits = 1
  for column in data.at("category_columns", default: ()) {
    for cat in column {
      let d = str(cat.at("count", default: 0)).len()
      if d > digits { digits = d }
    }
  }
  digits
}
// 页面标题: Hero 搜索提示与 detail/event 视图头部共用, 新模式漏写该键时不至于整页失败
#let panel_title = data.at("title", default: "帮助面板")
// 指令前缀: Python 侧按 wake_prefix 写字符串列表 (如 ["/"]) 供快捷操作文案使用
#let primary_prefix = {
  let raw = data.at("prefixes", default: ())
  let first = if type(raw) == array {
    raw.at(0, default: "")
  } else if type(raw) == str {
    raw
  } else {
    ""
  }
  if first == "" { "/" } else { str(first) }
}

// 颜色参数 (仅 event/filter/detail 视图使用, 默认已对齐新主题)
#let c_map           = data.at("colors", default: (:))
#let get_color(key, default_hex) = {
  rgb(c_map.at(key, default: default_hex))
}

// === 🎨 品牌主题色板 (随预设切换, 由 colors 配置注入) ===
#let c_sky     = get_color("brand_sky", "#57CDE3")  // 天空蓝 · 第一主色
#let c_navy    = get_color("brand_navy", "#355A81")  // 深海蓝 · 结构色
#let c_mint    = get_color("brand_mint", "#8AE6E1")  // 浅青蓝 · 高光
#let c_cream   = get_color("brand_cream", "#FADE86")  // 奶油黄 · 强调
#let c_gold    = get_color("brand_gold", "#F0C14B")  // 金黄 · 暖强调
#let c_blush   = get_color("brand_blush", "#A8E9F2")  // 浅天蓝 · 柔和辅助
#let c_ink     = get_color("brand_ink", "#2E2E35")  // 深色
#let c_gray    = get_color("brand_gray", "#808E9D")  // 灰蓝 · 次级文字/描述/disabled
#let c_card    = get_color("brand_card", "#FFFFFF")  // 卡片背景
#let c_border  = get_color("brand_border", "#DCEFF1")  // 卡片边框
#let c_soft    = get_color("brand_soft", "#E7EFF1")  // 插件行边框 (更浅)
#let c_ghost   = get_color("brand_ghost", "#F3F6F7")  // disabled 行 / 次要背景

// === 🚫 禁用插件灰化色板 (主题无关固定值, 由 DISABLED_COLORS 注入) ===
#let c_dis_card_bg     = get_color("disabled_card_bg", "#F5F5F5")  // 禁用卡片背景
#let c_dis_card_border = get_color("disabled_card_border", "#E7E7E7")  // 禁用卡片边框
#let c_dis_badge_bg    = get_color("disabled_badge_bg", "#D6C9CC")  // 禁用编号徽章背景
#let c_dis_badge_text  = get_color("disabled_badge_text", "#9B8A8E")  // 禁用编号文字
#let c_dis_name        = get_color("disabled_name", "#B8B8B8")  // 禁用插件名称
#let c_dis_cmd         = get_color("disabled_cmd", "#C8C8C8")  // 禁用命令名称/次级文本
#let c_dis_icon        = get_color("disabled_icon", "#B9A5A8")  // 禁用图标 (圆圈 + 斜杠, 左下→右上)

// === 🖼️ 页面设置 ===
#let page_fill = get_color("page_fill", "#F5FBFC")
// 页面总宽度 (pt): Python 侧按 rendering.page_width 注入; 旧缓存/旧配置缺键时沿用默认 830pt。
// 页宽同时决定列宽 (各列按 1fr 等比分配) 与出图像素宽度, 窄页宽在聊天窗口里文字相对更大。
#let page_width_pt = data.at("page_width", default: 830) * 1pt
// 内容区宽度: 页宽减去左右留白, 页眉/页脚与正文共用同一宽度
#let content_width = page_width_pt - 56pt
// 单页高度上限 (pt): Python 侧按「切片高度 ÷ 清晰度」换算后注入; 0 表示不做分页 (单张整图)
#let max_page_height_pt = float(sys.inputs.at("max_page_height", default: "0")) * 1pt
#set page(width: page_width_pt, margin: (x: 28pt, y: 24pt), fill: page_fill)
#set text(size: 10pt)
// 字体: 数据驱动, 未提供时使用 Typst 默认字体 (系统自动回退渲染 CJK)
// 注意: set 规则必须放在顶层 (不能包在 #if 块内), 否则只作用于块内内容, 全局不生效
#let eff_fonts = if user_fonts.len() > 0 { user_fonts } else { ("LXGW Neo XiHei",) }
#set text(font: eff_fonts)

// === 🎨 可配置颜色 (event/filter/detail 视图) ===

// --- 文本 ---
#let c_text_primary  = get_color("c_text_primary", "#355A81")
#let c_leaf_text     = get_color("c_leaf_text", "#2E2E35")
#let c_desc_text     = get_color("c_desc_text", "#808E9D")
#let c_plugin_id     = get_color("c_plugin_id", "#808E9D")

// --- 容器 ---
#let c_card_bg       = get_color("c_card_bg", "#FFFFFF")
#let c_box_bg        = get_color("c_box_bg", "#F3F6F7")
#let c_box_stroke    = get_color("c_box_stroke", "#E7EFF1")

// --- 强调色 ---
#let c_bullet        = get_color("c_bullet", "#57CDE3")

// --- 事件/过滤器视图 ---
#let c_plugin_name   = get_color("c_plugin_name", "#355A81")
#let c_group_title   = get_color("c_group_title", "#355A81")
#let c_group_bg      = get_color("c_group_bg", "#E8F6F9")
#let c_rich_bg       = get_color("c_rich_bg", "#FFFFFF")
#let c_event_icon    = get_color("c_event_icon", "#F0C14B")
#let c_regex_bg      = get_color("c_regex_bg", "#FFF6E3")
#let c_regex_text    = get_color("c_regex_text", "#C99114")
#let c_regex_icon    = get_color("c_regex_icon", "#D4A017")
#let c_tag_admin     = get_color("c_tag_admin", "#2E9BB8")
#let c_tag_event     = get_color("c_tag_event", "#F0C14B")
#let c_tag_mcp       = get_color("c_tag_mcp", "#355A81")
#let c_tag_id        = get_color("c_tag_id", "#355A81")
#let c_ver_bg        = get_color("c_ver_bg", "#E8F6F9")
#let c_ver_text      = get_color("c_ver_text", "#355A81")
#let c_prio_bg       = get_color("c_prio_bg", "#FDF6DC")
#let c_prio_text     = get_color("c_prio_text", "#C99114")

// --- 搜索高亮 ---
#let c_highlight_bg  = get_color("c_highlight_bg", "#FADE86")
#let c_highlight_text = get_color("c_highlight_text", "#2E2E35")

// --- 浅色标题栏/徽章上的深色文字 (不随深色主题变浅) ---
#let c_on_light      = get_color("c_on_light", "#355A81")

// === 🏷️ 图标 ===
#let admin_icon  = text(size: 0.9em, baseline: -1pt)[🔒]
#let tool_icon   = text(size: 0.9em, baseline: -1pt)[🛠️]
#let mcp_icon    = text(size: 0.9em, baseline: -1pt)[🔗]
#let filter_icon = text(size: 0.9em, baseline: -1pt)[⌛]
#let plugin_icon = text(size: 0.9em, baseline: -1pt)[🧩]

#let event_icon  = text(fill: c_event_icon, size: 0.9em, baseline: -1pt)[⚡]
#let regex_icon  = text(fill: c_regex_icon, size: 0.9em, baseline: -1pt)[®]
#let bullet_icon = text(fill: c_bullet, size: 1.2em, baseline: -1.5pt)[•]
#let sub_arrow   = text(fill: c_group_title, weight: "bold")[↳]

#let get_node_icon(node) = {
  if node.tag == "admin" { admin_icon }
  else if node.tag == "event_listener" { event_icon }
  else if node.tag == "tool" { tool_icon }
  else if node.tag == "mcp" { mcp_icon }
  else if node.tag == "filter_criteria" { filter_icon }
  else if node.tag == "plugin_container" { plugin_icon }
  else if node.tag == "regex_pattern" { regex_icon }
  else { bullet_icon }
}

// === 🩼 辅助方法 ===

// --- 通用卡片圆角 / 阴影 ---
#let card_radius        = 16pt
#let card_shadow_radius = 16pt
#let card_shadow_offset = 2pt

// --- 对比度: 深色背景用白字, 浅色背景用深海蓝 ---
// threshold 默认 0.6 用于主题明暗判定; 纯色块前景可单独放低阈值 (见 on_color)
#let is_light(c, threshold: 0.6) = {
  let (r, g, b, _) = c.components()
  (0.299 * float(r) + 0.587 * float(g) + 0.114 * float(b)) > threshold
}
#let on_color(c) = {
  // 亮度 0.58~0.60 的中亮色块上白字只有 ~2.5:1, 压深海蓝才够可读, 故阈值略低于默认值
  if is_light(c, threshold: 0.58) { c_on_light } else { white }
}

// --- 头部背景横幅: 前景文字/统计统一压深以保证在浅色背景图上可读
// (深色主题的浅色文字在浅色背景图上会看不清, 故不直接使用主题色)
#let banner_text_color(c) = {
  if is_light(c) { c.darken(45%) } else { c }
}

// --- 标题着色: 使用分类主题色, 按卡片明暗自动加深/加亮以保证可读性 ---
#let readable_title_color(c) = {
  if is_light(c_card) {
    // 浅色卡片: 浅色标题加深
    if is_light(c) { c.darken(40%) } else { c }
  } else {
    // 深色卡片: 深色标题加亮
    if is_light(c) { c } else { c.lighten(55%) }
  }
}

// --- 高亮 ---
#let hl(content) = {
  if query_regex_str != none and query_regex_str != "" {
    show regex("(?i)" + query_regex_str): it => box(
      fill: c_highlight_bg,
      radius: 2pt,
      inset: (x: 0pt, y: 0pt),
      outset: (y: 2pt),
      text(fill: c_highlight_text)[#it]
    )
    content
  } else {
    content
  }
}

// --- 版本胶囊 ---
#let version_pill(ver) = {
  if ver != none and ver != "" {
    box(fill: c_ver_bg, radius: 4pt, inset: (x: 5pt, y: 2pt), baseline: 1pt)[
      #text(fill: c_ver_text, size: 8pt, weight: "bold")[#ver]
    ]
  }
}

// --- 优先级胶囊 ---
#let priority_pill(prio) = {
  if prio != none {
    box(fill: c_prio_bg, radius: 3pt, inset: (x: 4pt, y: 1pt), baseline: 1pt)[
      #text(fill: c_prio_text, size: 7pt, weight: "bold")[P:#prio]
    ]
  }
}

// --- 可断行 ID (下划线后插入零宽空格, 允许自然断行) ---
#let breakable_id(text_str) = { text_str.replace("_", "_\u{200B}") }

// --- 自适应缩放 ---
// 超宽内容一律等比缩放到容器宽度 (避免原样溢出导致 typst 0.15 布局收敛诊断)
#let adaptive_text(content, max_width) = {
  context {
    let size = measure(content)
    if size.width > max_width and max_width > 0pt {
      let s = max_width / size.width
      scale(x: s * 100%, y: s * 100%, origin: left)[#content]
    } else {
      content
    }
  }
}

// --- 拆分着色 (event/filter 视图) ---
#let format_desc(content) = {
  hl({
    if content.starts-with("@") {
      let parts = content.split(" · ")
      let id_part = parts.at(0)
      let desc_part = if parts.len() > 1 { parts.slice(1).join(" · ") } else { "" }

      if id_part.starts-with("@MCP/") {
         text(size: 9pt, fill: c_tag_mcp, weight: "bold")[#id_part]
      } else {
         text(size: 9pt, fill: c_plugin_id, weight: "bold")[#id_part]
      }

      if desc_part != "" {
         text(size: 9pt, fill: c_desc_text)[ · #desc_part]
      }
    } else {
      text(size: 9pt, fill: c_desc_text)[#content]
    }
  })
}

// ============================================================
// 指令菜单 (command) · 顶部 Header
// ============================================================
#let render_header() = {
  let total = data.at("plugin_count", default: 0)
  let enabled = data.at("enabled_count", default: total)

  let stat(value, label, color, divided: false, label_color: c_gray) = if value == "" {
    none
  } else {
    box(
    height: 44pt,
    inset: (left: if divided { 14pt } else { 0pt }, y: 0pt),
    stroke: if divided { (left: 0.8pt + c_soft) } else { none },
  )[
    #align(center + horizon)[
      #grid(
        columns: (1fr),
        rows: (22pt, 16pt),
        row-gutter: 2pt,
        // Row 1: value — fixed 22pt height, identical center line across all columns
        align(center + horizon)[
          #context {
            let init_sz = 18pt
            let test = text(size: init_sz, weight: "bold", fill: color)[#value]
            let m = measure(test)
            if m.width > 90pt {
              text(size: init_sz * (90pt / m.width), weight: "bold", fill: color)[#value]
            } else {
              test
            }
          }
        ],
        // Row 2: label — fixed 16pt height, identical baseline across all columns
        align(center + horizon)[
          #text(size: 7.5pt, fill: label_color)[#label]
        ],
      )
    ]
  ]
    }

  // ===== Hero 品牌模式 (默认开启, 需检测到背景图) =====
  // 布局: 左侧大号品牌徽标 + 左下统计卡片, 右侧为背景图角色主视觉
  if has_header_bg and hero_header_enabled {
    // 品牌主色: 主题主色自动压深 (浅色背景图上可读)
    let hero_c = banner_text_color(c_sky)

    // 等宽统计单元 (竖线分隔): 数字与标签整体垂直居中
    // value 为纯文本字符串, 内部统一做自适应缩放 (超长等比缩小, 避免溢出)
    // 值为空时返回 none, 便于 grid 跳过空列
    let hero_stat(value, label, divided: false) = if value == "" {
      none
    } else {
      box(
      width: 76pt,
      height: 44pt,
      inset: (x: 4pt, y: 0pt),
      stroke: if divided { (left: 0.8pt + rgb(0, 0, 0, 30)) } else { none },
    )[
      #align(center + horizon)[
        #grid(
          columns: (1fr),
          rows: (22pt, 16pt),
          row-gutter: 2pt,
          // Row 1: value — fixed 22pt height, identical center line across all columns
          align(center + horizon)[
            #context {
              let init_sz = 15pt
              let test = text(size: init_sz, weight: "bold", fill: hero_c)[#value]
              let m = measure(test)
              if m.width > 66pt {
                text(size: init_sz * (66pt / m.width), weight: "bold", fill: hero_c)[#value]
              } else {
                test
              }
            }
          ],
          // Row 2: label — fixed 16pt height, identical baseline across all columns
          align(center + horizon)[
            #text(size: 7.5pt, fill: banner_text_color(c_gray))[#label]
          ],
        )
      ]
    ]
      }

    // 背景图以原始宽高比铺满整卡 (块高度由图片自身决定, 右侧角色完整可见)
    // 圆角与下方卡片保持一致; clip 让图片跟着裁出圆角, 否则图片会盖住圆角
    block(width: 100%, breakable: false, radius: card_radius, clip: true)[
      #image(bg_image_path, width: 100%)

      // 品牌徽标: 官方 AstrBot 文字徽标; 路径为空 (Python 侧判定缺图) 时留白
      #place(left + top, dx: 26pt, dy: 24pt)[
        #stack(spacing: 4pt, align(left)[
          #if logo_path != "" {
            image(logo_path, height: 60pt)
          }
          #if (query_regex_str != none and query_regex_str != "") [
            #v(6pt)
            #text(size: 8.5pt, fill: banner_text_color(c_gray))[#panel_title]
          ]
        ])
      ]
      // 左下统计卡片: 半透明白 + 圆角 + 等宽列 (bottom 对齐, 微抬进横幅内)
      #place(left + bottom, dx: 26pt, dy: -10pt)[
        #block(
          fill: rgb(255, 255, 255, 205),
          radius: 12pt,
          stroke: 0.8pt + rgb(255, 255, 255, 160),
          inset: (x: 10pt, y: 4pt),
        )[
          #grid(
            columns: (auto, auto, auto),
            column-gutter: 0pt,
            hero_stat(str(total), "总插件"),
            hero_stat(str(enabled), "已开启", divided: true),
            hero_stat(system_name, "人格", divided: true),
          )
        ]
      ]
    ]
  } else {
    // ===== 默认模式: 白色卡片 + 右侧统计 =====
    // 极轻阴影层 + 白色卡片
    block(
      width: 100%, breakable: false,
      fill: luma(0, 4%), radius: 18pt,
      inset: (bottom: 2pt, right: 2pt),
    )[
      #block(
        width: 100%, fill: c_card, radius: 17pt, stroke: 1pt + c_border,
        inset: (x: 22pt, y: 16pt),
      )[
        #grid(
          columns: (1fr, auto), gutter: 16pt,
          align(left + horizon)[
            #stack(
              spacing: 4pt,
              text(size: 22pt, weight: "bold", fill: c_navy)[Astrbot 插件面板],
              if (query_regex_str != none and query_regex_str != "") [
                #text(size: 9pt, fill: c_gray)[#panel_title]
              ],
            )
          ],
          align(right + horizon)[
            #grid(
              columns: (auto, auto, auto),
              column-gutter: 12pt,
              stat(str(total), "总插件", c_sky),
              stat(str(enabled), "已开启", c_cream, divided: true),
              stat(system_name, "人格", c_navy, divided: true),
            )
          ],
        )
      ]
    ]
  }
}

// ============================================================
// 快捷操作区
// ============================================================
#let render_quick_actions() = {
  // 胶囊只放「指令 + 四字说明」: 长句会让单个胶囊占两三行, 整行看着全是噪声
  let action(icon, color, cmd, label_str) = {
    box(
      width: 100%, fill: c_card, radius: 11pt,
      stroke: 1pt + c_border,
      inset: (x: 9pt, y: 7pt),
    )[
      #align(center + horizon)[
        #text(size: 9pt, fill: c_navy)[
          #text(fill: color, size: 1.05em)[#icon]
          #text(weight: "bold")[#cmd]
          #text(fill: c_gray)[#label_str]
        ]
      ]
    ]
  }

  // 每个指令一个胶囊; 页宽不足时减少列数, 免得文字被挤成竖条
  let cols = if page_width_pt < 520pt {
    (1fr, 1fr)
  } else if page_width_pt < 600pt {
    (1fr, 1fr, 1fr)
  } else {
    (1fr, 1fr, 1fr, 1fr, 1fr)
  }
  grid(
    columns: cols, column-gutter: 10pt, row-gutter: 8pt,
    // 说明一律两个字: 五列并排时四字会折行, 把胶囊撑成两行高
    action("📋", c_sky, primary_prefix + "helps", "列表"),
    action("📖", c_mint, primary_prefix + "helpss", "详情"),
    action("👑", c_cream, primary_prefix + "events", "事件"),
    action("🧭", c_navy, primary_prefix + "filters", "过滤"),
    action("🔍", c_sky, "s <关键词>", "搜索"),
  )
  // 搜索是四个指令共用的子命令, 单独用一行说明, 免得被当成某一个指令专属
  let search_hint = "以上指令都可以在末尾追加 s <关键词> 搜索，例如 " + primary_prefix + "events s 天气"
  v(5pt)
  align(center, text(size: 8pt, fill: c_gray, search_hint))
}

// ============================================================
// 禁用图标 (圆圈 + 斜杠, 左下→右上, 手绘保证颜色精确且不依赖字体字形)
// ============================================================
#let disabled_icon = box(
  width: 12pt, height: 12pt,
)[
  #place(center + horizon, circle(radius: 4.5pt, stroke: 1pt + c_dis_icon, fill: none))
  // 斜杠以圆心 (6pt, 6pt) 为对称中心: 半长 3.2pt 的轴向分量 3.2/√2 ≈ 2.263pt
  #place(top + left, line(start: (3.737pt, 8.263pt), end: (8.263pt, 3.737pt), stroke: 1pt + c_dis_icon))
]

// ============================================================
// 插件 Item (分类卡片内的一行)
// ============================================================
#let plugin_item(p, theme_color) = {
  let pidx = p.at("id", default: 0)
  let pname = p.at("name", default: "")
  let pdisp = p.at("display_name", default: "")
  let pdisabled = p.at("disabled", default: false)

  // 禁用态: 仅降低饱和度/对比度, 尺寸、圆角、内边距、排列与普通插件完全一致
  let name_fill  = if pdisabled { c_dis_name } else { c_navy }
  let id_fill    = if pdisabled { c_dis_cmd } else { c_gray }
  let badge_bg   = if pdisabled { c_dis_badge_bg } else { theme_color.lighten(82%) }
  let badge_num  = if pdisabled { c_dis_badge_text } else { c_on_light }
  let row_bg     = if pdisabled { c_dis_card_bg } else { c_card }
  let row_stroke = if pdisabled { c_dis_card_border } else { c_soft }

  // 插件名称 (无 display_name 时用插件名兜底)
  let name_content = if pdisp != none and pdisp != "" {
    text(size: 10pt, weight: "bold", fill: name_fill)[#hl(pdisp)]
  } else {
    text(size: 10pt, weight: "bold", fill: name_fill)[#hl(breakable_id(pname))]
  }

  // 插件内部 ID: 有 display_name 时展示在右侧
  let id_content = if pdisp != none and pdisp != "" {
    text(size: 7.5pt, fill: id_fill)[@#hl(breakable_id(pname))]
  } else {
    none
  }

  // 禁用标识: 仅在 disabled 时输出 (⊘ 手绘图标)
  let disabled_mark = if pdisabled {
    disabled_icon
  } else {
    none
  }

  // 双行模式: 没有右侧 ID 的插件 (无 display_name) 本来就只显示一行, 不参与
  let stacked = plugin_two_lines and id_content != none
  // 两行文字之间留出行距, 否则中文字形与 ID 的上下缘几乎贴在一起
  let name_cell = if stacked {
    stack(spacing: 3.5pt, name_content, id_content)
  } else {
    name_content
  }

  box(
    width: 100%, fill: row_bg,
    stroke: 0.75pt + row_stroke, radius: 8pt,
    // 双行时行高随之变大, 上下内边距同步放宽, 避免文字贴住边框
    inset: (x: 8pt, y: if stacked { 8pt } else { 5pt }),
  )[
    #grid(
      columns: (auto, 1fr, auto, auto), gutter: 6pt,
      // ID 徽章
      align(center + horizon)[
        #box(fill: badge_bg, radius: 9pt, inset: (x: 8pt, y: 3pt))[
          // hide 只占位: 用最大位数撑出等宽徽章, 数字本身再居中覆盖上去
          #hide[#text(size: 8.5pt, weight: "bold")[#("0" * order_digits)]]
          #place(center + horizon)[#text(size: 8.5pt, weight: "bold", fill: badge_num)[#pidx]]
        ]
      ],
      // 名称 (双行模式下 ID 跟随在名称下方)
      align(left + horizon)[#name_cell],
      // 插件内部 ID (右侧)
      align(right + horizon)[#if stacked { none } else { id_content }],
      // 禁用标识
      align(right + horizon)[#disabled_mark],
    )
  ]
}

// ============================================================
// 详细指令模式: 能力树组件
// ============================================================

// --- 能力分区标题 ---
#let section_label(icon, text_str) = {
  block(inset: (bottom: 2pt))[
    #grid(
      columns: (auto, 1fr), gutter: 4pt,
      align(left + horizon)[
        #text(size: 9pt, fill: c_gray, weight: "bold")[#icon #text_str]
      ],
      align(left + horizon)[
        #line(length: 100%, stroke: 0.5pt + c_soft)
      ],
    )
  ]
}

// --- 指令 Chip (主指令, 带强调色) ---
#let cmd_chip_detail(name, accent, disabled: false) = {
  let is_light_theme = is_light(c_card)
  let chip_bg = if disabled {
    c_dis_card_bg
  } else if is_light_theme {
    accent.lighten(80%)
  } else {
    accent.darken(45%)
  }
  let chip_text = if disabled {
    c_dis_cmd
  } else if is_light_theme {
    accent.darken(30%)
  } else {
    accent.lighten(20%)
  }
  let chip_stroke = if disabled { c_dis_card_border } else { accent.lighten(65%) }

  box(
    fill: chip_bg, radius: 4pt,
    stroke: 0.5pt + chip_stroke,
    inset: (x: 5.5pt, y: 1.5pt),
    baseline: 1pt,
  )[
    #text(size: 8.5pt, weight: "bold", fill: chip_text, spacing: 0.5pt)[#hl(name)]
  ]
}

// --- 别名 Chip (浅色, ↳ 前缀) ---
#let alias_chip_detail(name, disabled: false) = {
  let chip_bg = if disabled { c_dis_card_bg } else { c_ghost }
  let chip_text = if disabled { c_dis_cmd } else { c_gray }
  let chip_stroke = if disabled { c_dis_card_border } else { c_soft }

  box(
    fill: chip_bg, radius: 4pt,
    stroke: 0.5pt + chip_stroke,
    inset: (x: 5.5pt, y: 1.5pt),
    baseline: 1pt,
  )[
    #text(size: 8pt, fill: chip_text)[↳ #hl(name)]
  ]
}

// --- 监听器 Chip (中性灰) ---
#let listener_chip_detail(name, disabled: false) = {
  let chip_bg = if disabled { c_dis_card_bg } else { c_box_bg }
  let chip_text = if disabled { c_dis_cmd } else { c_gray }
  let chip_stroke = if disabled { c_dis_card_border } else { c_box_stroke }

  box(
    fill: chip_bg, radius: 4pt,
    stroke: 0.5pt + chip_stroke,
    inset: (x: 5.5pt, y: 1.5pt),
    baseline: 1pt,
  )[
    #text(size: 8pt, fill: chip_text, weight: "medium")[#hl(name)]
  ]
}

// --- 指令行 (⚡ Commands) ---
#let commands_section(cmds, accent, disabled: false) = {
  if cmds.len() == 0 { return none }
  section_label("⚡", "Commands")
  v(3pt)
  par(justify: false, leading: 0.55em)[
    #for cmd in cmds {
      // 主指令 Chip
      cmd_chip_detail(cmd.at("name", default: ""), accent, disabled: disabled)
      h(3pt)
      // 别名 Chip
      for alias in cmd.at("aliases", default: ()) {
        alias_chip_detail(alias, disabled: disabled)
        h(3pt)
      }
    }
  ]
  v(6pt)
}

// --- 指令组容器 (📂 Command Group) ---
#let group_section(group, accent, disabled: false) = {
  let cmds = group.at("commands", default: ())
  if cmds.len() == 0 { return none }
  let group_name = group.at("name", default: "")
  let group_bg = if disabled { c_dis_card_bg } else { c_box_bg }
  let group_stroke = if disabled { c_dis_card_border } else { c_box_stroke }

  block(
    width: 100%, fill: group_bg,
    stroke: 0.5pt + group_stroke, radius: 6pt,
    inset: (x: 7pt, y: 6pt),
  )[
    #text(size: 8.5pt, weight: "bold", fill: c_gray)[📂 #hl(group_name)]
    #v(3pt)
    #par(justify: false, leading: 0.55em)[
      #for cmd in cmds {
        cmd_chip_detail(cmd.at("name", default: ""), accent, disabled: disabled)
        h(3pt)
        for alias in cmd.at("aliases", default: ()) {
          alias_chip_detail(alias, disabled: disabled)
          h(3pt)
        }
      }
    ]
  ]
  v(6pt)
}

// --- 监听器行 (◉ Listeners) 监听器提取的指令关键词 ---
#let listeners_section(cmd_names, disabled: false) = {
  if cmd_names.len() == 0 { return none }
  section_label("🔔", "Listeners")
  v(3pt)
  par(justify: false, leading: 0.55em)[
    #for name in cmd_names {
      listener_chip_detail(name, disabled: disabled)
      h(3pt)
    }
  ]
  v(6pt)
}

// ============================================================
// 详细指令模式: 插件 Item (能力树)
// ============================================================
#let plugin_item_detail(p, theme_color) = {
  let pidx = p.at("id", default: 0)
  let pname = p.at("name", default: "")
  let pdisp = p.at("display_name", default: "")
  let pdisabled = p.at("disabled", default: false)
  let capabilities = p.at("capabilities", default: (:))

  // 禁用色
  let row_bg     = if pdisabled { c_dis_card_bg } else { c_ghost }
  let row_stroke = if pdisabled { c_dis_card_border } else { c_soft }
  // 插件名: 深色主题下卡片底本身是深色, 再 darken 会让文字几乎不可见 (Night Navy
  // 的 cat_slot_4 只剩约 1.1:1), 因此底色偏深时改为提亮主题色
  let name_fill  = if pdisabled {
    c_dis_name
  } else if is_light(row_bg) {
    theme_color.darken(30%)
  } else {
    theme_color.lighten(80%)
  }
  let badge_bg   = if pdisabled { c_dis_badge_bg } else { theme_color.lighten(82%) }
  let badge_num  = if pdisabled { c_dis_badge_text } else { c_on_light }

  // 插件名称 (优先 display_name): 抽成变量, 双行模式要把它和 ID 堆叠
  let name_text = if pdisp != none and pdisp != "" {
    text(size: 10.5pt, weight: "bold", fill: name_fill)[#hl(pdisp)]
  } else {
    text(size: 10.5pt, weight: "bold", fill: name_fill)[#hl(breakable_id(pname))]
  }

  // 插件内部 ID (右侧, 极小灰字)
  let id_content = if pdisp != none and pdisp != "" {
    text(size: 7pt, fill: c_gray)[@#hl(breakable_id(pname))]
  } else {
    none
  }

  // 双行模式: 英文 ID 换到名称下方, 行距与行高都要比单行大一档
  let stacked = plugin_two_lines and id_content != none

  // 处理能力数据
  let cmds = capabilities.at("commands", default: ())
  let groups = capabilities.at("groups", default: ())
  let listeners = capabilities.at("listeners", default: ())

  // 确定是否有任何能力内容
  let has_capabilities = cmds.len() > 0 or groups.len() > 0 or listeners.len() > 0

  // 插件卡片整块保留, 分页发生在插件之间; 只有插件自身高于单页上限时才允许拆开
  let card = block(
    width: 100%, fill: row_bg,
    stroke: 0.5pt + row_stroke, radius: 8pt,
    inset: (x: 10pt, y: if stacked { 10pt } else { 7pt }),
  )[
    // 头部: 编号 + 名称 + @id
    #grid(
      columns: (auto, 1fr, auto), gutter: 6pt,
      align(top + left)[
        #box(fill: badge_bg, radius: 9pt, inset: (x: 8pt, y: 3pt), baseline: 2.5pt)[
          #hide[#text(size: 8.5pt, weight: "bold")[#("0" * order_digits)]]
          #place(center + horizon)[#text(size: 8.5pt, weight: "bold", fill: badge_num)[#pidx]]
        ]
      ],
      align(top + left)[
        #if stacked {
          stack(spacing: 3.5pt, name_text, id_content)
        } else {
          name_text
        }
      ],
      align(top + right)[#if stacked { none } else { id_content }],
    )

    // 能力内容
    #if has_capabilities {
      v(5pt)
      line(length: 100%, stroke: 0.5pt + c_soft)
      v(4pt)
      commands_section(cmds, theme_color, disabled: pdisabled)
      for g in groups {
        group_section(g, theme_color, disabled: pdisabled)
      }
      listeners_section(listeners, disabled: pdisabled)
    }
  ]
  context {
    let card_height = measure(card).height
    let must_break = max_page_height_pt > 0pt and card_height > max_page_height_pt
    block(width: 100%, breakable: must_break)[#card]
  }
}

// ============================================================
// 分类卡片 (支持 detail 模式: 指令标签组)
// ============================================================
#let category_card(cat, detail: false) = {
  let name = cat.at("name", default: "")
  let count = cat.at("count", default: 0)
  let plugins = cat.at("plugins", default: ())

  // 主题色: 优先数据传入的 color (Python 侧按主题色槽解析), 兜底灰蓝
  let raw_color = cat.at("color", default: "")
  let color = if raw_color != "" {
    rgb(raw_color)
  } else {
    c_gray
  }

  // 标题栏一律用白字; 橙黄、草绿这类很浅的分类色上白字只有 1.6~2.1:1, 先把底色压深再上白字,
  // 不能像原来那样靠切深色标题来保可读性 (参差的黑白标题看起来像漏改)
  let title_fill = white
  let bar_fill = if is_light(color, threshold: 0.62) { color.darken(30%) } else { color }
  // 徽章沿用 plugin_item 的编号徽章规则: 主题色浅化作底, 数字取该底色上的深色
  let badge_bg   = color.lighten(82%)
  let badge_num  = on_color(badge_bg)

  let inner = block(
    width: 100%, fill: c_card, radius: 15pt, stroke: 1pt + c_border,
  )[
      // 主题色标题栏: 居中加粗标题 + 右侧计数徽章
      #block(
        width: 100%, fill: bar_fill, radius: (top: 14pt),
        inset: (x: 12pt, y: 8pt),
      )[
        // 徽章用 place 贴右侧, 不参与列宽计算: 放进网格右列会把标题的居中位置挤偏
        #place(right + horizon)[
          #box(fill: badge_bg, radius: 10pt, inset: (x: 9pt, y: 3pt))[
            // 同编号徽章: hide 占位按最长位数撑宽度, 数字本身再居中覆盖上去
            #hide[#text(size: 9.5pt, weight: "bold")[#("0" * count_digits)]]
            #place(center + horizon)[#text(fill: badge_num, size: 9.5pt, weight: "bold")[#count]]
          ]
        ]
        // 标题相对整条标题栏居中; 左右各让 20pt 给徽章, 分类名过长时换行而不压到徽章上
        #align(center)[
          #block(
            width: 100% - 40pt,
            align(center, text(fill: title_fill, weight: 800, size: 17pt)[#hl(name)]),
          )
        ]
      ]
      // 插件列表
      #block(inset: (x: 8pt, y: 8pt), spacing: 0pt)[
        #stack(
          spacing: 6pt,
          ..plugins.map(p => if detail { plugin_item_detail(p, color) } else { plugin_item(p, color) })
        )
      ]
  ]

  // 分类卡片默认整体换页 (分页落在分类边界); 单页高度放不下整张卡片时
  // 必须允许跨页拆开, 否则超出页面的内容会被直接裁掉, 表现为指令"没渲染完"
  context {
    let card_height = measure(inner).height
    let must_break = max_page_height_pt > 0pt and card_height > max_page_height_pt
    block(
      width: 100%, breakable: must_break,
      fill: luma(0, 4%), radius: card_radius,
      inset: (bottom: 2pt, right: 2pt),
    )[#inner]
  }
}

// ============================================================
// 双栏分类布局 (支持 detail 模式)
// ============================================================
#let render_categories(detail: false) = {
  let cols = data.at("category_columns", default: ())
  if cols.len() > 0 {
    // 列数由 Python 侧按页宽决定 (窄页宽 → 单列), 每列等分页宽
    grid(
      columns: range(cols.len()).map(_ => 1fr),
      column-gutter: 14pt,
      row-gutter: 12pt,
      ..cols.map(col => {
        align(top)[
          #stack(spacing: 12pt, ..col.map(cat => category_card(cat, detail: detail)))
        ]
      })
    )
  }
}

// ============================================================
// 事件/过滤器视图组件
// ============================================================

// --- 单行模式 ---
#let render_single_row(node) = {
  if node.tag == "regex_pattern" {
    grid(
      columns: (auto, 1fr), gutter: 6pt,
      align(top)[#get_node_icon(node)],
      align(left + horizon)[
         #box(fill: c_regex_bg, radius: 3pt, inset: (x: 4pt, y: 2pt))[
           #text(size: 10pt, fill: c_regex_text)[#hl(node.name)]
         ]
      ]
    )
    v(0pt)
  } else if node.tag == "event_listener" or node.tag == "plugin_container" {
    grid(
      columns: (auto, 1fr), gutter: 6pt,
      align(top)[#get_node_icon(node)],
      align(left)[
          #block(breakable: false, width: 100%)[
             #layout(size => {
                let safe_name = breakable_id(node.name)
                let content = box[
                   #text(weight: "bold", fill: c_leaf_text, size: 11pt)[#hl(safe_name)]
                   #if node.priority != none {
                      h(4pt)
                      priority_pill(node.priority)
                   }
                ]
                adaptive_text(content, size.width)
             })
             #v(2pt)
             #format_desc(node.desc)
          ]
      ]
    )
    v(0pt)
  } else {
    grid(
      columns: (auto, auto, 1fr), gutter: 6pt,
      align(right)[#get_node_icon(node)],
      align(left)[
        #text(weight: "bold", fill: c_leaf_text)[#hl(node.name)]
      ],
      align(left + horizon)[#text(size: 9pt, fill: c_desc_text)[#node.desc]]
    )
    v(0pt)
  }
}

// --- 紧凑块 ---
#let render_compact_block(node) = {
  box(
    width: 100%, fill: c_box_bg, radius: 4pt, stroke: 0.5pt + c_box_stroke, inset: (x: 4pt, y: 6pt),
  )[
    #align(center)[
       #if node.tag != "normal" { get_node_icon(node) }
       #text(size: 10pt, weight: "bold", fill: c_leaf_text)[#hl(node.name)]
    ]
  ]
}

// --- 富文本卡片 (Giant/Singles) ---
#let render_rich_block(node) = {
  box(
    width: 100%, fill: c_rich_bg, radius: 4pt, inset: 8pt, stroke: 0.5pt + c_box_stroke
  )[
    #grid(
         columns: (auto, 1fr), gutter: 4pt,
         get_node_icon(node),
         layout(size => {
            let safe_name = breakable_id(node.name)

            let title_obj = text(weight: "bold", fill: c_leaf_text, hl(safe_name))

            let prio_obj = if node.priority != none {
                h(4pt) + priority_pill(node.priority)
            } else {
                none
            }

            let content = box(title_obj + prio_obj)
            adaptive_text(content, size.width)
         })
    )

    #if node.desc != "" {
         v(2pt)
         format_desc(node.desc)
    }

    #if node.children != none and node.children.len() > 0 {
      v(2pt)
      line(length: 100%, stroke: 0.5pt + c_box_stroke)
      v(2pt)

      let sample = node.children.at(0)

      if sample.tag == "regex_pattern" {
        grid(
          columns: (1fr), row-gutter: 4pt,
          ..node.children.map(child => {
             box(fill: c_regex_bg, radius: 3pt, inset: (x: 4pt, y: 2pt), width: 100%)[
               #text(size: 9pt, fill: c_regex_text)[#hl(child.name)]
             ]
          })
        )
      } else {
        grid(
          columns: (1fr), row-gutter: 10pt,
          ..node.children.map(child => {
             grid(
               columns: (auto, 1fr), gutter: 4pt,
               text(size: 0.8em)[#get_node_icon(child)],
               stack(
                   spacing: 3pt,
                   layout(size => {
                       let child_title = text(size: 9pt, fill: c_leaf_text, weight: "bold", hl(child.name))
                       let child_prio = if child.priority != none {
                           h(2pt) + priority_pill(child.priority)
                       } else {
                           none
                       }
                       box(child_title + child_prio)
                   }),
                   if child.desc != "" {
                      h(3pt)
                      format_desc(child.desc)
                   }
               )
             )
          })
        )
      }
    }
  ]
}

// --- 标准递归 ---
#let render_node_standard(node, indent_level: 0) = {
  if node.is_group {
    let content = [
        #grid(
          columns: (auto, 1fr), gutter: 6pt,
          align(horizon)[#if indent_level == 0 { text(fill: c_group_title)[📂] } else { sub_arrow }],
          align(horizon)[
             #let title_color = if indent_level == 0 { c_group_title } else { c_plugin_id }
             #text(weight: "bold", fill: title_color, size: 11.5pt)[#hl(node.name)]
             #if node.desc != "" { h(0.5em); text(size: 9pt, fill: c_desc_text)[#node.desc] }
          ]
        )

        #v(6pt)

        #let complex = node.children.filter(c => c.is_group or c.desc != "")

        #let simple = node.children.filter(c =>
             not c.is_group
             and c.desc == ""
             and (c.tag == "normal" or c.tag == "admin")
        )

        #let specials = node.children.filter(c =>
             not c.is_group
             and c.desc == ""
             and not (c.tag == "normal" or c.tag == "admin")
        )

        #for child in complex { render_node_standard(child, indent_level: indent_level + 1) }
        #for child in specials { render_node_standard(child, indent_level: indent_level + 1) }

        #if simple.len() > 0 {
           if (complex.len() + specials.len()) > 0 { v(4pt) }
           pad(left: 1em)[
             #grid(columns: range(content_cols).map(_ => 1fr), gutter: 5pt, ..simple.map(c => render_compact_block(c)))
           ]
        }
    ]
    if indent_level == 0 {
      block(width: 100%, fill: c_group_bg, radius: 6pt, inset: 8pt, below: 6pt, above: 6pt)[#content]
    } else {
      block(width: 100%, fill: c_card, inset: (left: 8pt, rest: 6pt), stroke: (left: 3pt + c_group_title), radius: (right: 4pt), below: 4pt, above: 4pt)[#content]
    }
  } else {
    render_single_row(node)
  }
}

// --- 插件卡片头部 ---
#let plugin_header(plugin) = {
  let display = plugin.display_name
  let name = plugin.name
  let ver = plugin.version
  // 卡片头只用数据层给的展示名, 不再给内部 name 拼 "@": 事件/过滤器分组卡片的 name 是
  // event_group / filter_regex 这类容器标识, 拼出来对用户毫无意义
  grid(
    columns: (1fr, auto), gutter: 10pt,
    align(left + horizon)[
      #layout(size => {
        let avail_w = size.width
        if display != none and display != "" {
          text(weight: "black", size: 15pt, fill: c_plugin_name)[#hl(display)]
        } else {
          let safe_name = breakable_id(name)
          let name_content = text(weight: "black", size: 14pt, fill: c_plugin_name)[#hl(safe_name)]
          adaptive_text(name_content, avail_w)
        }
      })
    ],
    align(right + top)[#version_pill(ver)]
  )
}

// --- 插件卡片入口 ---
#let plugin_card(plugin, mode: "standard") = {
  block(
    width: 100%, breakable: false,
    fill: luma(0, 6%), radius: card_shadow_radius,
    inset: (bottom: card_shadow_offset, right: card_shadow_offset),
  )[
    #block(
      width: 100%, radius: card_radius, inset: 12pt,
      fill: c_card, stroke: 0.5pt + c_box_stroke,
    )[
    #plugin_header(plugin)
    #v(3pt)
    #line(length: 100%, stroke: 1pt + c_soft)
    #v(3pt)

    #if mode == "giant" {
       grid(
         columns: range(content_cols).map(_ => 1fr),
         gutter: 8pt,
         ..plugin.nodes.map(n => render_rich_block(n))
       )
    } else {
       let complex = plugin.nodes.filter(c => c.is_group or c.desc != "")
       let simple = plugin.nodes.filter(c =>
            not c.is_group
            and c.desc == ""
            and (c.tag == "normal" or c.tag == "admin")
       )
       let specials = plugin.nodes.filter(c =>
            not c.is_group
            and c.desc == ""
            and not (c.tag == "normal" or c.tag == "admin")
       )

       for node in complex { render_node_standard(node, indent_level: 0) }
       for node in specials { render_node_standard(node, indent_level: 0) }

       if simple.len() > 0 [
          #if (complex.len() + specials.len()) > 0 { v(6pt) }
          #grid(
            columns: range(content_cols).map(_ => 1fr), gutter: 5pt,
            ..simple.map(c => render_compact_block(c))
          )
        ]
     }
     ]
   ]
}

// --- 独立指令区 ---
#let render_singles_section(singles) = {
  if singles.len() > 0 {
    v(15pt)
    let sample = singles.at(0).nodes.at(0)
    let title = "🧩 独立工具指令"
    let sub = "零散的单指令插件合集"
    if sample.tag == "tool" or sample.tag == "mcp" {
       title = "🛠️ 函数工具调用 (Function Tools)"
       sub = "大模型可调用的本地插件工具与 MCP 服务"
    }
    align(center)[
      #text(size: 16pt, weight: "bold", fill: c_text_primary)[#title] \
      #v(5pt)
      #text(size: 10pt, fill: c_desc_text)[#sub]
    ]
    v(10pt)
    block(
      width: 100%, breakable: false,
      fill: luma(0, 6%), radius: card_shadow_radius,
      inset: (bottom: card_shadow_offset, right: card_shadow_offset),
    )[
      #block(
        width: 100%, fill: c_card, radius: card_radius, inset: 15pt, stroke: 0.5pt + c_box_stroke
      )[
      #grid(
        columns: range(content_cols).map(_ => 1fr), gutter: 12pt,
        ..singles.map(plugin => {
          let cmd = plugin.nodes.at(0)
           box(
            width: 100%, fill: c_rich_bg, radius: 4pt, inset: 8pt, stroke: 0.5pt + c_box_stroke
          )[
            #grid(
               columns: (auto, 1fr, auto), gutter: 4pt,
               get_node_icon(cmd),
               layout(size => {
                  let safe_name = breakable_id(cmd.name)
                  let content = text(weight: "bold", fill: c_leaf_text)[#hl(safe_name)]
                  adaptive_text(content, size.width)
               }),
               version_pill(plugin.version)
            )
            #v(0pt)
            #block[
              #text(size: 8pt, fill: c_plugin_id)[来自: ]
              #if plugin.display_name != none and plugin.display_name != "" {
                 text(size: 8pt, fill: c_plugin_id, weight: "bold")[#hl(plugin.display_name)]
                 h(3pt)
                 let safe_id = breakable_id(plugin.name)
                 text(size: 7.5pt, fill: c_desc_text)[@#hl(safe_id)]
              } else {
                 let safe_id = breakable_id(plugin.name)
                 text(size: 8pt, fill: c_plugin_id)[@#hl(safe_id)]
              }
            ]
            #if cmd.desc != "" {
               v(2pt)
               line(length: 100%, stroke: (dash: "dotted", paint: c_soft))
               v(2pt)
               text(size: 9pt, fill: c_desc_text)[#hl(cmd.desc)]
            }
          ]
        })
      )
      ]
    ]
  }
}

// ============================================================
// 插件详情页组件
// ============================================================

// --- 信息胶囊 ---
#let info_pill(label, value, bg, color) = {
  if value != none and value != "" {
    box(fill: bg, radius: 8pt, inset: (x: 8pt, y: 3pt), baseline: 2pt)[
      #text(size: 9pt, fill: color)[#label  ]
      #text(size: 9.5pt, fill: color, weight: "bold")[#value]
    ]
  }
}

// --- 分区标题行 ---
#let section_header(icon, title, en_title) = {
  block[
    #grid(columns: (auto, 1fr, auto), gutter: 6pt,
      align(left + horizon)[
        #box(fill: c_bullet.lighten(85%), radius: 4pt, inset: (x: 5pt, y: 2pt))[#icon]
      ],
      align(left + horizon)[#text(size: 12pt, weight: "bold", fill: c_bullet)[#title]],
      align(right + horizon)[#text(size: 8pt, fill: c_gray, tracking: 0.5em)[#en_title]]
    )
    #v(4pt)
    #line(length: 100%, stroke: 0.6pt + c_bullet.lighten(75%))
    #v(8pt)
  ]
}

// --- 指令条目行 ---
#let command_row(cmd) = {
  block(breakable: false, inset: (bottom: 5pt))[
    #grid(columns: (auto, 1fr), gutter: 6pt,
      align(top + left)[#bullet_icon],
      align(left + horizon)[
        #text(size: 10.5pt, weight: "bold", fill: c_leaf_text)[#hl(breakable_id(cmd.at("name", default: "")))]
        #if cmd.at("desc", default: "") != "" {
          text(size: 9pt, fill: c_desc_text)[  —  #hl(cmd.at("desc", default: ""))]
        }
      ]
    )
  ]
}

// --- 事件监听条目行 ---
#let event_listener_row(listener) = {
  let cmds = listener.at("commands", default: ())
  block(breakable: false, inset: (bottom: 5pt))[
    #grid(columns: (auto, 1fr), gutter: 6pt,
      align(top + left)[#bullet_icon],
      align(left)[
        #text(size: 10.5pt, weight: "bold", fill: c_leaf_text)[#hl(breakable_id(listener.at("name", default: "")))]
        #if listener.at("priority", default: none) != none {
          h(2pt)
          priority_pill(listener.at("priority", default: none))
        }
        #if cmds.len() > 0 {
          h(3pt)
          text(size: 9pt, fill: c_bullet)[#hl(cmds.join("  ·  "))]
        } else if listener.at("desc", default: "") != "" {
          text(size: 9pt, fill: c_desc_text)[#hl(listener.at("desc", default: ""))]
        }
      ]
    )
  ]
}

// --- 插件详情主体 ---
#let render_plugin_detail() = {
  let p = data.at("plugin", default: (:))
  let admin_cmds = data.at("admin_commands", default: ())
  let normal_cmds = data.at("normal_commands", default: ())
  let event_listeners = data.at("event_listeners", default: ())

  // 标题配色: 优先使用插件分类主题色 (与 /helps 分类卡片一致), 缺失回退结构色
  let raw_title_color = p.at("category_color", default: "")
  let title_color = if raw_title_color != "" {
    readable_title_color(rgb(raw_title_color))
  } else {
    c_plugin_name
  }

  v(12pt)

  block(
    width: 100%, breakable: false,
    fill: luma(0, 6%), radius: card_shadow_radius,
    inset: (bottom: card_shadow_offset, right: card_shadow_offset),
  )[
    #block(width: 100%, fill: c_card, radius: card_radius, inset: (x: 18pt, y: 16pt))[
      #align(center)[
        #text(size: 26pt, weight: "bold", fill: title_color)[#p.at("display_name", default: "")]
      ]
      #v(10pt)

      #align(center)[
        #stack(dir: ltr, spacing: 8pt,
          info_pill("作者", p.at("author", default: ""), c_ver_bg, c_ver_text),
          info_pill("版本", p.at("version", default: ""), c_prio_bg, c_prio_text),
          info_pill("编号", str(p.at("order", default: 0)), c_box_bg, c_leaf_text),
        )
      ]
      #v(14pt)

      #if p.at("desc", default: "") != "" {
        section_header(text(size: 0.9em)[📄], "功能简介", "ABOUT")
        text(size: 10.5pt, fill: c_leaf_text)[#hl(p.at("desc", default: ""))]
        v(12pt)
      }

      #if normal_cmds.len() > 0 {
        section_header(text(size: 0.9em)[⚡], "指令", "COMMANDS")
        stack(spacing: 0pt, ..normal_cmds.map(cmd => command_row(cmd)))
        v(6pt)
      }

      #if admin_cmds.len() > 0 {
        section_header(text(size: 0.9em)[🛡️], "管理员指令", "ADMIN COMMANDS")
        stack(spacing: 0pt, ..admin_cmds.map(cmd => command_row(cmd)))
        v(4pt)
      }

      #if event_listeners.len() > 0 {
        section_header(text(size: 0.9em)[🔔], "事件监听", "EVENT LISTENERS")
        stack(spacing: 0pt, ..event_listeners.map(listener => event_listener_row(listener)))
        v(4pt)
      }

      #v(6pt)
      #align(right)[
        #text(size: 8.5pt, fill: c_gray)[共 #(admin_cmds.len() + normal_cmds.len()) 条指令]
      ]
    ]
  ]
}

// ============================================================
// 主布局
// ============================================================

#let mode = data.at("mode", default: "command")

// ---- 分页渲染 ----
// 长图不再按像素硬切: 头部与尾部改为页眉/页脚, 每一页都完整重复;
// 分类卡片本身 breakable: false, 因此只会在分类边界换页, 不会被截成两半。
#let render_page_header() = {
  if mode == "command" or mode == "command_detail" {
    // 指令模式: 横幅 + 快捷操作
    render_header()
    v(6pt)
    render_quick_actions()
    v(8pt)
  } else if mode == "plugin_detail" {
    align(center)[
      #block(inset: (top: 16pt, bottom: 8pt))[
        #text(size: 24pt, weight: "bold", fill: c_text_primary)[#panel_title] \
        #v(5pt)
        #text(size: 9.5pt, fill: c_desc_text)[
          插件详情  ·  #generated_time
        ]
      ]
    ]
  } else {
    align(center)[
      #block(inset: (top: 16pt, bottom: 8pt))[
        #text(size: 24pt, weight: "bold", fill: c_text_primary)[#panel_title] \
        #v(5pt)
        #text(size: 9.5pt, fill: c_desc_text)[
          已加载 #data.at("plugin_count", default: 0) 个插件/监听组  ·  #generated_time
        ]
      ]
    ]
    v(12pt)
  }
}

#let render_page_body() = {
  if mode == "command" or mode == "command_detail" {
    render_categories(detail: mode == "command_detail")
  } else if mode == "plugin_detail" {
    render_plugin_detail()
  } else {
    // --- 巨型块 ---
    if data.at("giants", default: ()).len() > 0 {
      stack(spacing: 10pt, ..data.at("giants", default: ()).map(plugin => plugin_card(plugin, mode: "giant")))
      v(15pt)
    }

    // --- Columns ---
    // 列数由 Python 侧按页宽决定 (默认三列, 页宽变窄时退回两列/单列)
    let ev_cols = data.at("columns", default: ())
    if ev_cols.len() > 0 {
      grid(
        columns: range(ev_cols.len()).map(_ => 1fr), gutter: 15pt,
        ..ev_cols.map(col_plugins => {
          align(top)[
            #stack(spacing: 10pt, ..col_plugins.map(plugin => plugin_card(plugin, mode: "standard")))
          ]
        })
      )
    }

    // --- Singles ---
    render_singles_section(data.at("singles", default: ()))
  }
}

#let render_page_footer() = {
  align(center)[
    #text(size: 7.5pt, fill: c_gray)[
      Powered by #text(fill: c_sky)[AstrBot] & Typst Engine  ·  #generated_time
    ]
  ]
}

#let body_block = block(width: content_width)[#render_page_body()]

// 页眉/页脚放进页边距区域后, 「页面外沿的呼吸位」只能写在块内部:
// 页眉上方 24pt、页脚上下各 24pt。这样页眉与正文之间的间距 (头部自带的 8pt)
// 才和单页整图完全一致 —— 如果改用 margin 撑开外沿, 正文会被一并推开。
// 相邻两个 block 之间 Typst 会插入段间距 (par.spacing = 1.2em)。单页整图里
// 头部↔正文、正文↔页脚都吃到了这段间距; 页眉/页脚挪进页边距后它就不存在了,
// 所以量出来手动补上, 否则分页页会比单页整图紧一截。
#let panel_header = block(width: content_width)[#render_page_header()]
#let panel_footer = block(width: content_width)[#render_page_footer()]

// 内容高度用 measure 拿: 放得下就保持原来的「单张整图」, 放不下才切成多页
#context {
  // 页眉/页脚要放进页边距, 24pt 外沿呼吸位只能写在块内部:
  // 页眉上方 24pt、页脚上下各 24pt, 再把上面量出的段间距补回去
  let flow_gap = (
    measure(block(width: content_width)[#body_block #body_block]).height
      - 2 * measure(body_block).height
  )
  let page_header_block = block(width: content_width)[
    #v(24pt)
    #panel_header
    #v(flow_gap)
  ]
  let page_footer_block = block(width: content_width)[
    #v(24pt + flow_gap)
    #panel_footer
    #v(24pt)
  ]
  let header_h = measure(page_header_block).height
  let footer_h = measure(page_footer_block).height
  let body_h = measure(body_block).height
  let cap = max_page_height_pt
  // 留 8pt 余量, 避免整页高度恰好压线时反复在「单张/分页」之间抖动
  let paginate = cap > 0pt and header_h + footer_h + body_h + 8pt > cap

  set page(
    width: page_width_pt,
    height: if paginate { cap } else { auto },
    margin: if paginate {
      (x: 28pt, top: header_h, bottom: footer_h)
    } else {
      (x: 28pt, y: 24pt)
    },
    header: if paginate { page_header_block } else { none },
    footer: if paginate { page_footer_block } else { none },
    // 0pt: 页眉底边/页脚顶边贴在正文区边界上, 位置完全由 margin 决定;
    // 用默认值 (按首/末行基线推算) 会把页眉顶出页面上沿、页脚下沿被裁掉。
    // 不分页时 header/footer 为 none, 这两个值不起作用
    header-ascent: 0pt,
    footer-descent: 0pt,
    fill: page_fill,
  )

  if paginate {
    body_block
  } else {
    panel_header
    body_block
    v(24pt)
    panel_footer
  }
}

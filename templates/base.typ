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

// === 🗂️ 分类主题色 (按分类名固定匹配, 随预设切换, 兜底灰蓝) ===
#let category_colors = (
  "AI":   get_color("cat_AI", "#57CDE3"),
  "工具": get_color("cat_工具", "#2E9BB8"),
  "管理": get_color("cat_管理", "#355A81"),
  "娱乐": get_color("cat_娱乐", "#8AE6E1"),
  "查询": get_color("cat_查询", "#FADE86"),
  "其他": get_color("cat_其他", "#808E9D"),
  "资讯": get_color("cat_资讯", "#A8E9F2"),
  "调试": get_color("cat_调试", "#6C8CA8"),
)

// === 🖼️ 页面设置 ===
#let page_fill = get_color("page_fill", "#F5FBFC")
#set page(width: 900pt, height: auto, margin: (x: 32pt, y: 26pt), fill: page_fill)
#set text(size: 10pt)
// 字体: 数据驱动, 未提供时使用 Typst 默认字体 (系统自动回退渲染 CJK)
#if user_fonts.len() > 0 {
  set text(font: user_fonts)
}

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
#let is_light(c) = {
  let (r, g, b, _) = c.components()
  (0.299 * float(r) + 0.587 * float(g) + 0.114 * float(b)) > 0.6
}
#let on_color(c) = {
  if is_light(c) { c_on_light } else { white }
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

  let stat(value, label, color, divided: false) = box(
    inset: (left: if divided { 14pt } else { 0pt }, y: 0pt),
    stroke: if divided { (left: 0.8pt + c_soft) } else { none },
  )[
    #align(center + horizon)[
      #text(size: 18pt, weight: "bold", fill: color)[#value]
      #v(2pt)
      #text(size: 7.5pt, fill: c_gray)[#label]
    ]
  ]

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
              #text(size: 9pt, fill: c_gray)[#data.title]
            ],
          )
        ],
        align(right + horizon)[
          #stack(
            dir: ltr, spacing: 14pt,
            stat(str(total), "总插件", c_sky),
            stat(str(enabled), "已开启", c_cream, divided: true),
            stat("AstrBot", "System", c_navy, divided: true),
          )
        ],
      )
    ]
  ]
}

// ============================================================
// 快捷操作区
// ============================================================
#let render_quick_actions() = {
  let action(icon, color, label_str) = {
    box(
      width: 100%, fill: c_card, radius: 11pt,
      stroke: 1pt + c_border,
      inset: (x: 12pt, y: 8pt),
    )[
      #align(center + horizon)[
        #text(size: 9pt, fill: c_navy)[
          #text(fill: color, size: 1.05em)[#icon]  #label_str
        ]
      ]
    ]
  }

  grid(
    columns: (1fr, 1fr, 1fr), column-gutter: 10pt,
    action("📌", c_sky, "发送 /helps <编号> 查看插件详情"),
    action("📋", c_mint, "发送 /helps s <关键词> 搜索指令"),
    action("👑", c_cream, "发送 /events /filters 查看事件与过滤器"),
  )
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

  box(
    width: 100%, fill: row_bg,
    stroke: 0.75pt + row_stroke, radius: 8pt,
    inset: (x: 10pt, y: 7pt),
  )[
    #grid(
      columns: (auto, 1fr, auto, auto), gutter: 8pt,
      // ID 徽章
      align(center + horizon)[
        #box(fill: badge_bg, radius: 10pt, inset: (x: 9pt, y: 2.5pt))[
          #text(size: 8.5pt, weight: "bold", fill: badge_num)[#pidx]
        ]
      ],
      // 名称
      align(left + horizon)[#name_content],
      // 插件内部 ID (右侧)
      align(right + horizon)[#id_content],
      // 禁用标识
      align(right + horizon)[#disabled_mark],
    )
  ]
}

// ============================================================
// 分类卡片
// ============================================================
#let category_card(cat) = {
  let name = cat.at("name", default: "")
  let count = cat.at("count", default: 0)
  let plugins = cat.at("plugins", default: ())

  // 主题色: 优先数据传入的 color, 否则按名称固定映射, 最后兜底灰蓝
  let raw_color = cat.at("color", default: "")
  let color = if raw_color != "" {
    rgb(raw_color)
  } else {
    category_colors.at(name, default: c_gray)
  }
  let title_fill = on_color(color)

  block(
    width: 100%, breakable: false,
    fill: luma(0, 4%), radius: card_radius,
    inset: (bottom: 2pt, right: 2pt),
  )[
    #block(
      width: 100%, fill: c_card, radius: 15pt, stroke: 1pt + c_border,
    )[
      // 主题色标题栏
      #block(
        width: 100%, fill: color, radius: (top: 14pt),
        inset: (x: 14pt, y: 10pt),
      )[
        #grid(
          columns: (1fr, auto), gutter: 8pt,
          align(left + horizon)[#text(fill: title_fill, weight: "bold", size: 15pt)[#hl(name)]],
          align(right + horizon)[
            #box(fill: white, radius: 10pt, inset: (x: 9pt, y: 3pt))[
              #text(fill: c_on_light, size: 9.5pt, weight: "bold")[#count]
            ]
          ],
        )
      ]
      // 插件列表
      #block(inset: (x: 10pt, y: 10pt), spacing: 0pt)[
        #stack(
          spacing: 7pt,
          ..plugins.map(p => plugin_item(p, color))
        )
      ]
    ]
  ]
}

// ============================================================
// 双栏分类布局
// ============================================================
#let render_categories() = {
  let cols = data.at("category_columns", default: ())
  if cols.len() > 0 {
    grid(
      columns: (1fr, 1fr),
      column-gutter: 18pt,
      row-gutter: 16pt,
      ..cols.map(col => {
        align(top)[
          #stack(spacing: 16pt, ..col.map(cat => category_card(cat)))
        ]
      })
    )
  }
}

// ============================================================
// 事件/过滤器视图组件
// ============================================================

// --- 语法指引 ---
#let render_syntax_guide() = {
  let prefixes = data.at("prefixes", default: ("/"))
  let prefix_str = if type(prefixes) == array { prefixes.join(" 或 ") } else { prefixes }

  let pill(content, bg, color) = box(
    fill: bg, radius: 4pt, inset: (x: 6pt, y: 3pt), baseline: 2pt,
    text(weight: "bold", fill: color, size: 10pt)[#content]
  )

  let joint = text(fill: c_gray, size: 10pt, baseline: 2pt)[(空格)]

  align(center)[
    #block(
      fill: c_card, stroke: 1pt + c_box_stroke, radius: 6pt, inset: 10pt, below: 15pt
    )[
      #stack(dir: ltr, spacing: 8pt,
        text(size: 10pt, fill: c_desc_text, baseline: 2pt)[指令格式:],
        pill(prefix_str, c_ver_bg, c_ver_text),
        pill("父指令", c_group_bg, c_group_title),
        joint,
        pill("子指令", c_box_bg, c_leaf_text),
        joint,
        pill("<参数>", c_prio_bg, c_gold)
      )
    ]
  ]
}

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
             #grid(columns: (1fr, 1fr, 1fr), gutter: 5pt, ..simple.map(c => render_compact_block(c)))
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
  grid(
    columns: (1fr, auto), gutter: 10pt,
    align(left + horizon)[
      #layout(size => {
        let avail_w = size.width
        if display != none and display != "" {
          text(weight: "black", size: 15pt, fill: c_plugin_name)[#hl(display)]
          linebreak()
          v(0pt)
          let safe_id = breakable_id(name)
          text(weight: "medium", size: 9pt, fill: c_plugin_id)[@#hl(safe_id)]
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
         columns: (1fr, 1fr, 1fr),
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
            columns: (1fr, 1fr, 1fr), gutter: 5pt,
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
        columns: (1fr, 1fr, 1fr), gutter: 12pt,
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
      align(top + left)[#event_icon],
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
        section_header(text(size: 0.9em)[📋], "指令", "COMMANDS")
        stack(spacing: 0pt, ..normal_cmds.map(cmd => command_row(cmd)))
        v(6pt)
      }

      #if admin_cmds.len() > 0 {
        section_header(text(size: 0.9em)[🛡️], "管理员指令", "ADMIN COMMANDS")
        stack(spacing: 0pt, ..admin_cmds.map(cmd => command_row(cmd)))
        v(4pt)
      }

      #if event_listeners.len() > 0 {
        section_header(text(size: 0.9em)[⚡], "事件监听", "EVENT LISTENERS")
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

#if mode == "command" {
  // 指令模式: Header + 快捷操作 + 分类卡片
  render_header()
  v(14pt)
  render_quick_actions()
  v(18pt)
  render_categories()
} else if mode == "plugin_detail" {
  // 插件详情页
  align(center)[
    #block(inset: (top: 16pt, bottom: 8pt))[
      #text(size: 24pt, weight: "bold", fill: c_text_primary)[#data.title] \
      #v(5pt)
      #text(size: 9.5pt, fill: c_desc_text)[
        插件详情  ·  #generated_time
      ]
    ]
  ]
  render_plugin_detail()
} else {
  // 事件/过滤器模式
  align(center)[
    #block(inset: (top: 16pt, bottom: 8pt))[
      #text(size: 24pt, weight: "bold", fill: c_text_primary)[#data.title] \
      #v(5pt)
      #text(size: 9.5pt, fill: c_desc_text)[
        已加载 #data.at("plugin_count", default: 0) 个插件/监听组  ·  #generated_time
      ]
    ]
  ]
  v(12pt)

  // --- 巨型块 ---
  if data.at("giants", default: ()).len() > 0 {
    stack(spacing: 10pt, ..data.at("giants", default: ()).map(plugin => plugin_card(plugin, mode: "giant")))
    v(15pt)
  }

  // --- Columns ---
  grid(
    columns: (1fr, 1fr, 1fr), gutter: 15pt,
    ..data.at("columns", default: ()).map(col_plugins => {
      align(top)[
        #stack(spacing: 10pt, ..col_plugins.map(plugin => plugin_card(plugin, mode: "standard")))
      ]
    })
  )

  // --- Singles ---
  render_singles_section(data.at("singles", default: ()))
}

#v(24pt)
#align(center)[
  #text(size: 7.5pt, fill: c_gray)[
    Powered by #text(fill: c_sky)[AstrBot] & Typst Engine  ·  #generated_time
  ]
]

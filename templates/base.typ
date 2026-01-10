// === 🔧 全局配置 ===
#set page(width: 900pt, height: auto, margin: 20pt, fill: rgb("#f0f2f5"))
#set text(font: ("Maple Mono NF"), size: 12pt)

#let data = json.decode(sys.inputs.json_string)
#let query_regex_str = sys.inputs.at("query_regex", default: none)
#let generated_time = sys.inputs.at("timestamp", default: "Unknown Time")

// === 🎨 调色板 ===

// --- 插件卡片 ---
#let c_plugin_name   = rgb("#0d47a1")
#let c_plugin_id     = rgb("#546e7a")

// --- 指令内容 ---
// 父级/分组标题
#let c_group_title   = rgb("#6a1b9a") 
// 子指令/具体项
#let c_bullet        = rgb("#d81b60")
#let c_event_icon    = rgb("#ffc72c")
#let c_leaf_text     = rgb("#37474f")
// 描述文本
#let c_desc_text     = rgb("#757575")

// --- 容器布局 ---
#let c_group_bg      = rgb("#f3e5f5")
#let c_rich_bg      = rgb("#fcfcfc")
// 紧凑块
#let c_box_bg        = rgb("#f5f5f5")
#let c_box_stroke    = rgb("#e0e0e0")

// --- 特殊视图 ---
// 分区大标题
#let c_text_primary = rgb("#1a1a1a")
// 正则表达式视图
#let c_regex_bg      = rgb("#fff3e0")
#let c_regex_text    = rgb("#e65100")
#let c_regex_icon    = rgb("#f57c00")
// 事件与管理标签
#let c_tag_admin     = rgb("#c62828")
#let c_tag_event     = rgb("#f57c00")
#let c_tag_mcp       = rgb("#00695c")
#let c_tag_id        = rgb("#283593")
// 胶囊
#let c_ver_bg        = rgb("#e3f2fd")
#let c_ver_text      = rgb("#1565c0")
#let c_prio_bg       = rgb("#e8eaf6")
#let c_prio_text     = rgb("#283593")

// --- 搜索高亮 ---
#let c_highlight_bg  = rgb("#ffeb3b")
#let c_highlight_text = black

// === 🏷︎ 图标 ===
#let admin_icon  = text(size: 0.9em, baseline: -1pt)[🔒]
#let tool_icon   = text(size: 0.9em, baseline: -1pt)[🛠️]
#let mcp_icon    = text(size: 0.9em, baseline: -1pt)[🔗] 
#let filter_icon = text(size: 0.9em, baseline: -1pt)[⌛︎]
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

// === 🩼︎ 辅助方法 ===

// --- 高亮 ---
#let hl(content) = {
  if query_regex_str != none and query_regex_str != "" {
    // 构造正则: (?i) 忽略大小写 + 转义后的查询词
    show regex("(?i)" + query_regex_str): it => box(
      fill: c_highlight_bg,
      radius: 2pt,
      inset: (x: 0pt, y: 0pt),
      outset: (y: 2pt), // 稍微外扩，形成荧光笔效果
      text(fill: c_highlight_text)[#it]
    )
    content
  } else {
    content
  }
}

// --- 胶囊 ---

// 版本
#let version_pill(ver) = {
  if ver != none and ver != "" {
    box(fill: c_ver_bg, radius: 4pt, inset: (x: 5pt, y: 2pt), baseline: 1pt)[
      #text(fill: c_ver_text, size: 8pt, weight: "bold")[#ver]
    ]
  }
}
// 优先级
#let priority_pill(prio) = {
  if prio != none {
    box(fill: c_prio_bg, radius: 3pt, inset: (x: 4pt, y: 1pt), baseline: 1pt)[
      #text(fill: c_prio_text, size: 7pt, weight: "bold")[P:#prio]
    ]
  }
}

// --- 自适应换行 ---
#let breakable_id(text_str) = { text_str.replace("_", "_\u{200B}") }

#let adaptive_text(content, max_width) = {
  context {
    let size = measure(content)
    // 缩放不够就换行
    if size.width > max_width { 
       let s = max_width / size.width
       if s > 0.7 {
         scale(x: s * 100%, y: s * 100%, origin: left)[#content] 
       } else {
         content
       }
    } else { 
       content 
    }
  }
}

// --- 拆分着色 ---
#let format_desc(content) = {
  hl({
    if content.starts-with("@") {
      let parts = content.split(" · ")
      let id_part = parts.at(0)
      let desc_part = if parts.len() > 1 { parts.slice(1).join(" · ") } else { "" }

      // 区分
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

// === ⚙️ 组件核心 ===

// --- 语法指引 ---
#let render_syntax_guide() = {
  let prefixes = data.at("prefixes", default: ("/"))
  let prefix_str = if type(prefixes) == array { prefixes.join(" / ") } else { prefixes }

  // 样式胶囊
  let pill(content, bg, color) = box(
    fill: bg, radius: 4pt, inset: (x: 6pt, y: 3pt), baseline: 2pt,
    text(weight: "bold", fill: color, size: 10pt)[#content]
  )

  // 连接符
  let joint = text(fill: silver, size: 10pt, baseline: 2pt)[(空格)]

  align(center)[
    #block(
      fill: white, stroke: 1pt + c_box_stroke, radius: 6pt, inset: 10pt, below: 15pt
    )[
      #stack(dir: ltr, spacing: 8pt,
        text(size: 10pt, fill: c_desc_text, baseline: 2pt)[指令格式:],

        // 1. 唤醒词
        pill(prefix_str, c_ver_bg, c_ver_text),

        // 2. 指令
        pill("父指令", c_group_bg, c_group_title),
        joint,
        pill("子指令", c_box_bg, c_leaf_text),

        // 3. 参数
        joint,
        pill("<参数>", rgb("#fff8e1"), rgb("#ff8f00"))
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
         #box(fill: c_regex_bg, radius: 3pt, inset: (x:4pt, y:2pt))[
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
    // 普通指令模式
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

// --- 富文本卡片(Giant/Singles) ---
#let render_rich_block(node) = {
  box(
    width: 100%, fill: c_rich_bg, radius: 4pt, inset: 8pt, stroke: 0.5pt + c_box_stroke
  )[
    #grid(
         columns: (auto, 1fr), gutter: 4pt,
         get_node_icon(node),
         layout(size => {
            let safe_name = breakable_id(node.name)

            // 1. 构建标题对象
            let title_obj = text(weight: "bold", fill: c_leaf_text, hl(safe_name))

            // 2. 构建优先级对象 (如果有)
            let prio_obj = if node.priority != none {
                h(4pt) + priority_pill(node.priority)
            } else {
                none
            }

            // 3. 使用 + 号拼接内容对象，并包裹在 box 中
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
		     // 正则样式
             box(fill: c_regex_bg, radius: 3pt, inset: (x:4pt, y:2pt), width: 100%)[
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

                   // 子项标题
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
	  // 子分组样式
      block(width: 100%, fill: white, inset: (left: 8pt, rest: 6pt), stroke: (left: 3pt + c_group_title), radius: (right: 4pt), below: 4pt, above: 4pt)[#content]
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
    width: 100%, breakable: false, radius: 8pt, inset: 12pt, 
    fill: white, stroke: 0.5pt + luma(220), 
  )[
    #plugin_header(plugin)
    #v(3pt)
    #line(length: 100%, stroke: 1pt + luma(240))
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
      width: 100%, fill: white, radius: 8pt, inset: 15pt, stroke: 0.5pt + luma(200)
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
               line(length: 100%, stroke: (dash: "dotted", paint: luma(200)))
               v(2pt)
               text(size: 9pt, fill: c_desc_text)[#hl(cmd.desc)]
            }
          ]
        })
      )
    ]
  }
}

// === 🏭 组装视图 ===

// --- 主布局 ---
#align(center)[
  #block(inset: (top: 20pt, bottom: 5pt))[
    #text(size: 36pt, weight: "black", fill: c_text_primary)[#data.title] \
    #v(6pt)
    #text(size: 11pt, fill: c_desc_text)[
      已加载 #data.plugin_count 个插件/监听组  ·  #generated_time
    ]
  ]
]

// 语法指引
#if data.at("mode", default: "command") == "command" {
  render_syntax_guide()
} else {
  v(15pt) // 如果不是指令模式，补回一点间距
}

// --- 巨型块 --- 
#if data.giants.len() > 0 {
  stack(spacing: 10pt, ..data.giants.map(plugin => plugin_card(plugin, mode: "giant")))
  v(15pt)
}

// --- Columns ---
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 15pt,
  ..data.columns.map(col_plugins => {
    align(top)[
      #stack(spacing: 10pt, ..col_plugins.map(plugin => plugin_card(plugin, mode: "standard")))
    ]
  })
)

// --- Singles ---
#render_singles_section(data.singles)

#v(20pt)
#align(center + bottom)[
  #text(size: 10pt, fill: silver)[Powered by AstrBot & Typst Engine]
]
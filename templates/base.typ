// 1. 全局配置
#set page(width: 900pt, height: auto, margin: 20pt, fill: rgb("#f0f2f5"))
#set text(font: ("Maple Mono NF"), size: 12pt)

#let data = json.decode(sys.inputs.json_string)
#let query_regex_str = sys.inputs.at("query_regex", default: none)
#let generated_time = sys.inputs.at("timestamp", default: "Unknown Time")

// --- 🎨 调色板 ---
#let c_text_primary = rgb("#1a1a1a")
#let c_text_secondary = rgb("#666666")
#let c_text_tertiary  = rgb("#999999")

#let c_version_bg = rgb("#e0f2f1")
#let c_version_text = rgb("#00695c")
#let c_prio_bg   = rgb("#e8eaf6")
#let c_prio_text = rgb("#283593")

#let c_top_group_bg   = rgb("#f4f6f8") 
#let c_top_group_text = rgb("#2c3e50") 

#let c_sub_group_bg   = rgb("#ffffff") 
#let c_sub_border     = rgb("#7e57c2") 
#let c_sub_text       = rgb("#5e35b1") 

#let c_accent      = rgb("#d81b60")
#let c_cmd_text    = rgb("#333333") 
#let c_admin       = rgb("#e53935") 
#let c_event_src   = rgb("#0288d1") 
#let c_event_icon  = rgb("#f57c00") 
#let c_id_tag      = rgb("#3949ab") 
#let c_mcp_tag     = rgb("#00796b") 
#let c_regex_bg    = rgb("#fff3e0") 
#let c_regex_text  = rgb("#e65100")
#let c_filter_icon = rgb("#7e57c2")

#let c_compact_bg = rgb("#ffffff") 
#let c_compact_stroke = rgb("#e0e0e0")
#let c_rich_bg = rgb("#fcfcfc")

// 搜索高亮
#let c_highlight_bg = rgb("#ffeb3b") 
#let c_highlight_text = rgb("#000000")

// --- 图标 ---
#let admin_icon = text(fill: c_admin, size: 0.9em, baseline: -1pt)[🔒]
#let event_icon = text(fill: c_event_icon, size: 0.9em, baseline: -1pt)[⚡]
#let src_icon   = text(fill: c_event_src, size: 0.9em, baseline: -1pt)[⚡]
#let tool_icon  = text(fill: c_admin, size: 0.9em, baseline: -1pt)[🛠️]
#let mcp_icon   = text(fill: c_mcp_tag, size: 0.9em, baseline: -1pt)[🔌] 
#let filter_icon = text(fill: c_filter_icon, size: 0.9em, baseline: -1pt)[🌪️]
#let regex_icon  = text(fill: c_event_icon, size: 0.9em, baseline: -1pt)[®]
#let plugin_icon = text(fill: c_id_tag, size: 0.9em, baseline: -1pt)[🧩] 
#let bullet_icon = text(fill: c_accent, size: 1.2em, baseline: -1.5pt)[•]
#let sub_arrow = text(fill: c_sub_border, weight: "bold")[↳] 

#let get_node_icon(node) = {
  if node.tag == "admin" { admin_icon } 
  else if node.tag == "event" { event_icon } 
  else if node.tag == "event_listener" { src_icon } 
  else if node.tag == "tool" { tool_icon } 
  else if node.tag == "mcp" { mcp_icon } 
  else if node.tag == "filter_criteria" { filter_icon } 
  else if node.tag == "plugin_container" { plugin_icon }
  else if node.tag == "regex_pattern" { regex_icon }
  else { bullet_icon }
}

// ==========================================
// 辅助函数: 高亮逻辑
// ==========================================

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

// ==========================================
// 辅助函数 (提前定义以供全局使用)
// ==========================================

#let version_pill(ver) = {
  if ver != none and ver != "" {
    box(fill: c_version_bg, radius: 4pt, inset: (x: 5pt, y: 2pt), baseline: 1pt)[
      #text(fill: c_version_text, size: 8pt, weight: "bold")[#ver]
    ]
  }
}

#let priority_pill(prio) = {
  if prio != none {
    box(fill: c_prio_bg, radius: 3pt, inset: (x: 4pt, y: 1pt), baseline: 1pt)[
      #text(fill: c_prio_text, size: 7pt, weight: "bold")[P:#prio]
    ]
  }
}

#let breakable_id(text_str) = { text_str.replace("_", "_\u{200B}") }

#let adaptive_text(content, max_width) = {
  context {
    let size = measure(content)
    // 如果宽度不够，进行缩放，最小缩放到 70%，如果还不够就让它换行(保持原样)
    if size.width > max_width { 
       let s = max_width / size.width
       if s > 0.7 {
         scale(x: s * 100%, y: s * 100%, origin: left)[#content] 
       } else {
         content // 放弃缩放，允许折行
       }
    } else { 
       content 
    }
  }
}

// 如果描述以 @ 开头（说明是插件ID），则进行拆分着色
#let format_desc(content) = {
  hl({
    if content.starts-with("@") {
      let parts = content.split(" · ")
      let id_part = parts.at(0)
      let desc_part = if parts.len() > 1 { parts.slice(1).join(" · ") } else { "" }

      if id_part.starts-with("@MCP/") {
         text(size: 9pt, fill: c_mcp_tag, weight: "bold")[#id_part]
      } else {
         text(size: 9pt, fill: c_id_tag, weight: "bold")[#id_part]
      }

      if desc_part != "" {
         text(size: 9pt, fill: c_text_tertiary)[ · #desc_part]
      }
    } else {
      text(size: 9pt, fill: c_text_tertiary)[#content]
    }
  })
}

// ==========================================
// 核心 1: 单行模式 (Standard List Row)
// ==========================================
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
                   #text(weight: "bold", fill: c_cmd_text, size: 11pt)[#hl(safe_name)]
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
        #text(weight: "bold", fill: c_cmd_text)[#hl(node.name)]
      ],
      align(left + horizon)[#format_desc(node.desc)]
    )
    v(0pt)
  }
}

// ==========================================
// 核心 2: 紧凑块 (Compact Block)
// ==========================================
#let render_compact_block(node) = {
  box(
    width: 100%, fill: c_compact_bg, radius: 4pt, stroke: 0.5pt + c_compact_stroke, inset: (x: 4pt, y: 6pt),
  )[
    #align(center)[
       #if node.tag != "normal" { get_node_icon(node) }
       #text(size: 10pt, weight: "bold", fill: c_cmd_text)[#hl(node.name)]
    ]
  ]
}

// ==========================================
// 核心 3: 富文本卡片 (Rich Block - Giant/Singles)
// ==========================================
#let render_rich_block(node) = {
  box(
    width: 100%, fill: c_rich_bg, radius: 4pt, inset: 8pt, stroke: 0.5pt + luma(230)
  )[
    #grid(
         columns: (auto, 1fr), gutter: 4pt,
         get_node_icon(node),
         layout(size => {
            let safe_name = breakable_id(node.name)

            // 1. 构建标题对象
            let title_obj = text(weight: "bold", fill: c_cmd_text, hl(safe_name))
            
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
      line(length: 100%, stroke: 0.5pt + luma(220))
      v(2pt)
      
      let sample = node.children.at(0)
      
      if sample.tag == "regex_pattern" {
        grid(
          columns: (1fr), row-gutter: 4pt,
          ..node.children.map(child => {
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
                       let child_title = text(size: 9pt, fill: c_cmd_text, weight: "bold", hl(child.name))
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

// ==========================================
// 核心 4: 标准递归
// ==========================================
#let render_node_standard(node, indent_level: 0) = {
  if node.is_group {
    let content = [
        #grid(
          columns: (auto, 1fr), gutter: 6pt,
          align(horizon)[#if indent_level == 0 { text(fill: c_top_group_text)[📂] } else { sub_arrow }],
          align(horizon)[
             #let title_color = if indent_level == 0 { c_top_group_text } else { c_sub_text }
             #text(weight: "bold", fill: title_color, size: 11.5pt)[#hl(node.name)]
             #if node.desc != "" { h(0.5em); format_desc(node.desc) }
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
      block(width: 100%, fill: c_top_group_bg, radius: 6pt, inset: 8pt, below: 6pt, above: 6pt)[#content]
    } else {
      block(width: 100%, fill: c_sub_group_bg, inset: (left: 8pt, rest: 6pt), stroke: (left: 3pt + c_sub_border), radius: (right: 4pt), below: 4pt, above: 4pt)[#content]
    }
  } else {
    render_single_row(node)
  }
}

// ==========================================
// 插件卡片头部
// ==========================================
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
          text(weight: "black", size: 15pt, fill: c_text_primary)[#hl(display)]
          linebreak()
          v(0pt)
          let safe_id = breakable_id(name)
          text(weight: "medium", size: 9pt, fill: c_text_tertiary)[@#hl(safe_id)]
        } else {
          let safe_name = breakable_id(name)
          let name_content = text(weight: "black", size: 14pt, fill: c_text_primary)[#hl(safe_name)]
          adaptive_text(name_content, avail_w)
        }
      })
    ],
    align(right + top)[#version_pill(ver)]
  )
}

// ==========================================
// 插件卡片入口
// ==========================================
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

// ==========================================
// 独立指令区
// ==========================================
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
      #text(size: 10pt, fill: c_text_tertiary)[#sub]
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
            width: 100%, fill: c_rich_bg, radius: 4pt, inset: 8pt, stroke: 0.5pt + luma(230)
          )[
            #grid(
               columns: (auto, 1fr, auto), gutter: 4pt,
               get_node_icon(cmd),
               layout(size => {
                  let safe_name = breakable_id(cmd.name)
                  let content = text(weight: "bold", fill: c_cmd_text)[#hl(safe_name)]
                  adaptive_text(content, size.width)
               }),
               version_pill(plugin.version)
            )
            #v(0pt)
            #block[
              #text(size: 8pt, fill: c_sub_text)[来自: ]
              #if plugin.display_name != none and plugin.display_name != "" {
                 text(size: 8pt, fill: c_sub_text, weight: "bold")[#hl(plugin.display_name)]
                 h(3pt)
                 let safe_id = breakable_id(plugin.name)
                 text(size: 7.5pt, fill: c_text_tertiary)[@#hl(safe_id)]
              } else {
                 let safe_id = breakable_id(plugin.name)
                 text(size: 8pt, fill: c_sub_text)[@#hl(safe_id)]
              }
            ]
            #if cmd.desc != "" {
               v(2pt)
               line(length: 100%, stroke: (dash: "dotted", paint: luma(200)))
               v(2pt)
               text(size: 9pt, fill: c_text_secondary)[#hl(cmd.desc)]
            }
          ]
        })
      )
    ]
  }
}

// --- 主布局 ---
#align(center)[
  #block(inset: (top: 20pt, bottom: 15pt))[
    #text(size: 36pt, weight: "black", fill: c_text_primary)[#data.title] \
    #v(10pt)
    #text(size: 11pt, fill: c_text_tertiary)[
      已加载 #data.plugin_count 个插件/监听组  ·  #generated_time
    ]
  ]
]

// 巨型块
#if data.giants.len() > 0 {
  stack(spacing: 10pt, ..data.giants.map(plugin => plugin_card(plugin, mode: "giant")))
  v(15pt)
}

// Columns
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 15pt,
  ..data.columns.map(col_plugins => {
    align(top)[
      #stack(spacing: 10pt, ..col_plugins.map(plugin => plugin_card(plugin, mode: "standard")))
    ]
  })
)

// Singles
#render_singles_section(data.singles)

#v(20pt)
#align(center + bottom)[
  #text(size: 10pt, fill: silver)[Powered by AstrBot & Typst Engine]
]
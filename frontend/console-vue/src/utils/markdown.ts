// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

/**
 * 轻量 Markdown 渲染器（会话气泡专用）。
 *
 * 安全模型：
 * 1. 先对全文做 HTML 实体转义 —— 任何原始标签都不可能进入输出；
 * 2. 仅在转义后的文本上做标记替换，输出标签全部由本文件生成；
 * 3. 链接仅放行 http/https（协议白名单），javascript:/data: 等伪协议一律
 *    降级为纯文本，永不出现在 href 中。
 * 4. 代码段以 NUL 哨兵占位（不可能与自然文本冲突），最后再回填。
 */

function escapeHtml(src: string): string {
  return src
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 协议白名单：仅 http/https，返回 null 表示不允许作为链接 */
export function sanitizeUrl(url: string): string | null {
  const trimmed = url.trim()
  return /^https?:\/\/[^\s]+$/i.test(trimmed) ? trimmed : null
}

function renderInline(escaped: string): string {
  let out = escaped
  // 行内代码（先于其他规则抽出，内容不再参与后续替换）
  const codeSpans: string[] = []
  out = out.replace(/`([^`\n]+)`/g, (_m, code: string) => {
    codeSpans.push(`<code class="md-ic">${code}</code>`)
    return `\x00C${codeSpans.length - 1}\x00`
  })
  // 链接 [text](url)：url 过白名单；失败则只保留文本
  out = out.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_m, text: string, url: string) => {
    const safe = sanitizeUrl(url)
    return safe
      ? `<a href="${safe}" target="_blank" rel="noopener noreferrer">${text}</a>`
      : text
  })
  // 裸 URL 自动链接（同样过白名单）
  out = out.replace(/(?<![="'\w])((?:https?):\/\/[^\s<>"')]+)/gi, (m) => {
    const safe = sanitizeUrl(m)
    return safe ? `<a href="${safe}" target="_blank" rel="noopener noreferrer">${m}</a>` : m
  })
  // 粗体 / 斜体
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(?<!\w)\*([^*\n]+)\*(?!\w)/g, '<em>$1</em>')
  // 回填行内代码
  out = out.replace(/\x00C(\d+)\x00/g, (m, i: string) => codeSpans[Number(i)] ?? m)
  return out
}

/** 将 Markdown 源文本渲染为安全 HTML */
export function renderMarkdown(src: string): string {
  const escaped = escapeHtml(src)
  const blocks: string[] = []
  // 代码块整体抽出，避免块内文本被段落规则处理
  const rest = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang: string, code: string) => {
    const langClass = lang ? ` data-lang="${lang}"` : ''
    blocks.push(`<pre class="md-pre"${langClass}><code>${code.replace(/\n$/, '')}</code></pre>`)
    return `\n\x00B${blocks.length - 1}\x00\n`
  })

  const paragraphs = rest.split(/\n{2,}/)
  const html = paragraphs.map((para) => {
    const trimmed = para.trim()
    if (!trimmed) return ''
    const blockMatch = trimmed.match(/^\x00B(\d+)\x00$/)
    if (blockMatch) return blocks[Number(blockMatch[1])] ?? ''
    const lines = trimmed.split('\n')
    const rendered = lines.map((line) => {
      const blockLine = line.trim().match(/^\x00B(\d+)\x00$/)
      if (blockLine) return blocks[Number(blockLine[1])] ?? ''
      const h = line.match(/^(#{1,4})\s+(.*)$/)
      if (h) return `<strong class="md-h">${renderInline(h[2])}</strong>`
      const li = line.match(/^\s*[-*]\s+(.*)$/)
      if (li) return `<span class="md-li">${renderInline(li[1])}</span>`
      const ol = line.match(/^\s*(\d+)[.、]\s+(.*)$/)
      if (ol) return `<span class="md-li"><b class="md-ol">${ol[1]}.</b> ${renderInline(ol[2])}</span>`
      const quote = line.match(/^&gt;\s?(.*)$/)
      if (quote) return `<span class="md-quote">${renderInline(quote[1])}</span>`
      return renderInline(line)
    })
    return `<p class="md-p">${rendered.join('<br>')}</p>`
  }).filter(Boolean)

  return html.join('')
}
